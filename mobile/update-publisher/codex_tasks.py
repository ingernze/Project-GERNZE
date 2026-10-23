"""Optional Codex completion adapter. No model calls or monitoring loop."""
from pathlib import Path
import json
import time
import uuid
from event_outbox import EventOutbox, AuthenticatedPeer, EventError, require, uid, integer


class CodexTasks:
    def __init__(self, directory, manifest, server_id, *, clock=None):
        self.manifest = Path(manifest) if manifest else None
        self.server_id = uid(server_id)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.box = EventOutbox(Path(directory) / 'codex-events.sqlite3', clock=self.clock)
        with self.box.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS codex_subscriptions (peer TEXT PRIMARY KEY,enabled INTEGER NOT NULL,revision INTEGER NOT NULL,expires INTEGER NOT NULL)')

    def available(self):
        if not self.manifest:
            return False
        try:
            data = self.manifest.read_bytes()
            require(len(data) <= 4096)
            value = json.loads(data)
            return value.get('id') == 'gernze-codex' and value.get('enabled') is True and 'task-reminders-v1' in value.get('capabilities', [])
        except (OSError, ValueError, AttributeError, TypeError, EventError):
            return False

    def info(self, peer):
        require(isinstance(peer, AuthenticatedPeer), 'authentication_failed')
        with self.box.db() as db:
            row = db.execute('SELECT enabled,revision,expires FROM codex_subscriptions WHERE peer=?', (peer.pairing_id,)).fetchone()
        return {'serverId': self.server_id, 'available': self.available(),
                'enabled': bool(row and row['enabled'] and row['expires'] > self.clock() and self.available()),
                'revision': row['revision'] if row else 0}

    def subscribe(self, peer, enabled, expected_revision, *, renew=False):
        require(isinstance(peer, AuthenticatedPeer), 'authentication_failed')
        require(type(enabled) is bool)
        require(type(renew) is bool and (not renew or enabled))
        integer(expected_revision)
        require(not enabled or self.available(), 'plugin_unavailable')
        with self.box.db() as db:
            scope = self.box._peer(db, peer)
            row = db.execute('SELECT enabled,revision,expires FROM codex_subscriptions WHERE peer=?', (scope,)).fetchone()
            revision = row['revision'] if row else 0
            # Lost-response retry is harmless; an older contrary command must never undo a newer one.
            same = bool(row['enabled'] and row['expires'] > self.clock()) == enabled if row else not enabled
            require(not renew or (row and row['enabled'] and row['expires'] > self.clock()), 'subscription_expired')
            require(expected_revision == revision or same, 'subscription_conflict')
            if not same:
                revision += 1
            # A lease is checked on demand; no desktop timer is needed while idle.
            db.execute('INSERT OR REPLACE INTO codex_subscriptions VALUES (?,?,?,?)',
                       (scope, int(enabled), revision, self.clock() + 45000 if enabled else 0))
            if not enabled or (row and row['expires'] <= self.clock()):
                db.execute('UPDATE events SET acked=1,payload=NULL WHERE peer=?', (scope,))
        return self.info(peer)

    def revoke(self, pairing_id):
        uid(pairing_id)
        with self.box.db() as db:
            db.execute('DELETE FROM codex_subscriptions WHERE peer=?', (pairing_id,))
            db.execute('DELETE FROM events WHERE peer=?', (pairing_id,))
            db.execute('DELETE FROM peers WHERE id=?', (pairing_id,))

    def complete(self, task_id, completed_at):
        """Called by the optional local plugin only on a completion event, never by a timer."""
        uid(task_id); integer(completed_at, 1)
        if not self.available():
            return {'queued': 0}
        with self.box.db() as db:
            peers = [row['peer'] for row in db.execute('SELECT peer FROM codex_subscriptions WHERE enabled=1 AND expires>?', (self.clock(),))]
        count = 0
        for peer_id in peers:
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'gernze-codex:' + task_id))
            event = {'event_id': event_id, 'created_at': completed_at, 'expires_at': completed_at + 86400000,
                     'type': 'task_completed', 'title': 'Codex 本轮处理已结束',
                     'body': '电脑上的 Codex 已结束本轮处理，回来查看结果吧。', 'target': {'page': 'messages'}}
            def accept(db):
                row = db.execute('SELECT enabled,expires FROM codex_subscriptions WHERE peer=?', (peer_id,)).fetchone()
                old = db.execute('SELECT id FROM events WHERE peer=? AND id=?', (peer_id, event_id)).fetchone()
                return self.available() and bool(row and row['enabled'] and row['expires'] > self.clock()) and old is None
            try:
                answer = self.box.enqueue({'peer_id': peer_id, 'event': event}, accept=accept)
                count += answer['status'] == 'enqueued'
            except EventError as error:
                if error.code not in ('queue_full', 'event_expired'):
                    raise
        return {'queued': count}

    def dispatch(self, path, body, peer):
        require(isinstance(peer, AuthenticatedPeer), 'authentication_failed')
        if path == '/v1/codex/info':
            require(body is None)
            return self.info(peer)
        if path == '/v1/codex/subscription':
            require(type(body) is dict and set(body) == {'enabled', 'expectedRevision', 'renew'})
            return self.subscribe(peer, body['enabled'], body['expectedRevision'], renew=body['renew'])
        require(self.available(), 'plugin_unavailable')
        require(self.info(peer)['enabled'], 'subscription_disabled')
        if path == '/v1/codex/events':
            require(type(body) is dict and set(body) == {'cursor', 'streamId'})
            result = self.box.fetch(peer, body['cursor'], stream_id=body['streamId'])
        elif path == '/v1/codex/ack':
            require(type(body) is dict and set(body) == {'eventIds'})
            result = self.box.ack(peer, body['eventIds'])
        else:
            raise EventError('invalid_input')
        return {'serverId': self.server_id, **result}
