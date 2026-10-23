"""Bounded SQLite outbox. Local API only; authentication belongs to the existing TLS host."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

MAX_SAFE = 9007199254740991
MAX_EVENT_BYTES = 2048
MAX_RESPONSE_BYTES = 16384
MAX_LIMIT = 6
MAX_RETENTION_MS = 7 * 24 * 60 * 60 * 1000


class EventError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code='invalid_input'):
    if not condition:
        raise EventError(code)


def integer(value, lo=0, hi=MAX_SAFE):
    require(type(value) is int and lo <= value <= hi)
    return value


def uid(value):
    require(type(value) is str and len(value) == 36)
    try:
        require(str(uuid.UUID(value)) == value)
    except ValueError:
        raise EventError('invalid_input') from None
    return value


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def parse(raw, max_bytes=4096):
    require(type(raw) is bytes and len(raw) <= max_bytes)
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result)
            result[k] = v
        return result
    def bad(_):
        raise EventError('invalid_input')
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_float=bad, parse_constant=bad)
        require(type(result) is dict)
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise EventError('invalid_input') from None


def text(value, limit):
    require(type(value) is str and 0 < len(value) <= limit and value == value.strip())
    require(all(ord(c) >= 32 and not 127 <= ord(c) <= 159 and not 0xD800 <= ord(c) <= 0xDFFF for c in value))
    return value


def validate_event(event):
    keys(event, ('event_id', 'created_at', 'expires_at', 'type', 'title', 'body', 'target'))
    uid(event['event_id'])
    integer(event['created_at'], 1)
    integer(event['expires_at'], event['created_at'] + 1)
    require(event['expires_at'] - event['created_at'] <= MAX_RETENTION_MS)
    require(event['type'] in ('task_completed', 'file_ready'))
    text(event['title'], 60)
    text(event['body'], 400)
    target = event['target']
    require(type(target) is dict and set(target) in ({'page'}, {'page', 'event_id'}))
    require(target['page'] in ('companion', 'messages'))
    if 'event_id' in target:
        require(uid(target['event_id']) == event['event_id'])
    require(len(canonical(event)) <= MAX_EVENT_BYTES)
    return event


@dataclass(frozen=True)
class AuthenticatedPeer:
    """Trusted host capability, constructed AFTER existing TLS pairing authorization.

    Not a wire object or an alternative authenticator. Never deserialize it from an event.
    Scope is the existing pairing UUID; a replacement pairing gets a new queue scope.
    """
    pairing_id: str

    def __post_init__(self):
        uid(self.pairing_id)


class EventOutbox:
    def __init__(self, path, *, clock=None, max_per_peer=256, max_peers=64):
        self.path = Path(path)
        require(self.path.parent.is_dir() and not self.path.is_symlink(), 'storage_failed')
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.max_per_peer = integer(max_per_peer, 1, 256)
        self.max_peers = integer(max_peers, 1, 64)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS peers (id TEXT PRIMARY KEY,high INTEGER NOT NULL,lost INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (peer TEXT NOT NULL,seq INTEGER NOT NULL,id TEXT NOT NULL,expires INTEGER NOT NULL,digest TEXT NOT NULL,payload TEXT,acked INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(peer,seq),UNIQUE(peer,id))')
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('schema', '1'))
            require(db.execute('SELECT value FROM meta WHERE key=?', ('schema',)).fetchone()[0] == '1', 'storage_failed')
            db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)', ('stream_id', str(uuid.uuid4())))
        # Host supplies a dedicated PRIVATE directory (Windows ACL handled by existing publisher).
        if __import__('os').name != 'nt':
            __import__('os').chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        try:
            connection = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        except sqlite3.Error:
            raise EventError('storage_failed') from None
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA busy_timeout=3000')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA max_page_count=16384')  # Typically 64 MiB; row bounds apply too.
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise EventError('storage_failed') from None
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _peer(self, db, peer):
        require(isinstance(peer, AuthenticatedPeer), 'authentication_failed')
        row = db.execute('SELECT * FROM peers WHERE id=?', (peer.pairing_id,)).fetchone()
        if row is None:
            require(db.execute('SELECT count(*) FROM peers').fetchone()[0] < self.max_peers, 'queue_full')
            db.execute('INSERT INTO peers VALUES (?,0,0)', (peer.pairing_id,))
        return peer.pairing_id

    def _prune(self, db, now):
        # Retain ACK tombstones until expiry for idempotent producer retries, but remove their text.
        # Expired UNACKed events record a gap, including non-prefix holes. Never silently skip live rows.
        for row in db.execute('SELECT peer,max(seq) AS lost FROM events WHERE expires<=? AND acked=0 GROUP BY peer', (now,)).fetchall():
            db.execute('UPDATE peers SET lost=max(lost,?) WHERE id=?', (row['lost'], row['peer']))
        db.execute('DELETE FROM events WHERE expires<=?', (now,))

    def enqueue(self, value, *, accept=None):
        keys(value, ('peer_id', 'event'))
        peer = AuthenticatedPeer(uid(value['peer_id']))  # Local producer selects a verified recipient.
        event = validate_event(value['event'])
        payload = canonical(event)
        now = integer(self.clock(), 1)
        require(event['created_at'] <= now + 60000)
        require(event['expires_at'] > now, 'event_expired')
        with self.db() as db:
            # Optional local producer guard runs in the SAME write transaction as enqueue.
            # A confirmed unsubscribe therefore cannot race a later event insertion.
            if accept is not None and not accept(db):
                return {'status': 'skipped'}
            self._prune(db, now)
            scope = self._peer(db, peer)
            old = db.execute('SELECT seq,digest,acked FROM events WHERE peer=? AND id=?', (scope, event['event_id'])).fetchone()
            digest = hashlib.sha256(payload).hexdigest()
            if old is not None:
                require(old['digest'] == digest, 'event_conflict')
                return {'status': 'duplicate', 'cursor': old['seq'], 'acked': bool(old['acked'])}
            require(db.execute('SELECT count(*) FROM events WHERE peer=?', (scope,)).fetchone()[0] < self.max_per_peer, 'queue_full')
            high = db.execute('SELECT high FROM peers WHERE id=?', (scope,)).fetchone()[0]
            require(high < MAX_SAFE, 'queue_full')
            seq = high + 1
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,0)', (scope, seq, event['event_id'], event['expires_at'], digest, payload.decode('utf-8')))
            db.execute('UPDATE peers SET high=? WHERE id=?', (seq, scope))
            return {'status': 'enqueued', 'cursor': seq}

    def fetch(self, authenticated_peer, cursor, limit=6, *, stream_id=None):
        integer(cursor)
        integer(limit, 1, MAX_LIMIT)
        if stream_id is not None:
            uid(stream_id)
        with self.db() as db:
            self._prune(db, integer(self.clock(), 1))
            scope = self._peer(db, authenticated_peer)
            stream = db.execute('SELECT value FROM meta WHERE key=?', ('stream_id',)).fetchone()[0]
            require(stream_id is None or stream_id == stream, 'stream_reset')
            peer = db.execute('SELECT high,lost FROM peers WHERE id=?', (scope,)).fetchone()
            require(cursor <= peer['high'], 'cursor_ahead')
            rows = db.execute('SELECT seq,payload FROM events WHERE peer=? AND seq>? AND acked=0 ORDER BY seq LIMIT ?', (scope, cursor, limit + 1)).fetchall()
            more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = rows[-1]['seq'] if more else peer['high']
            result = {'schema': 1, 'stream_id': stream, 'peer_id': scope,
                      'events': [{'cursor': r['seq'], 'event': json.loads(r['payload'])} for r in rows],
                      'next_cursor': next_cursor, 'high_watermark': peer['high'], 'has_more': more,
                      'gap': {'lost_through': peer['lost']} if cursor < peer['lost'] else None}
            require(len(canonical(result)) <= MAX_RESPONSE_BYTES, 'payload_too_large')
            return result

    def ack(self, authenticated_peer, event_ids):
        require(type(event_ids) is list and 1 <= len(event_ids) <= MAX_LIMIT)
        require(len(set(uid(i) for i in event_ids)) == len(event_ids))
        with self.db() as db:
            self._prune(db, integer(self.clock(), 1))
            scope = self._peer(db, authenticated_peer)
            # Unknown/already-ACKed/expired IDs are idempotent no-ops, without revealing other peers.
            for event_id in event_ids:
                db.execute('UPDATE events SET acked=1,payload=NULL WHERE peer=? AND id=?', (scope, event_id))
            return {'schema': 1, 'status': 'acknowledged', 'event_ids': event_ids}

    def drop_revoked_peer(self, authenticated_peer):
        """Host calls ONLY after revocation, not an event HTTP endpoint. Old capability must no longer authenticate."""
        require(isinstance(authenticated_peer, AuthenticatedPeer), 'authentication_failed')
        with self.db() as db:
            db.execute('DELETE FROM events WHERE peer=?', (authenticated_peer.pairing_id,))
            db.execute('DELETE FROM peers WHERE id=?', (authenticated_peer.pairing_id,))
