"""Scoped delta summaries. Never copied into legacy L3/approval/sync tables.

Metadata gates precede all summary/raw body reads. Model output supplies only
text: permissions, exact sources and ancestry come from the host transaction.
"""
from datetime import datetime, timezone
import json
import uuid

from .conversation_store import encoded, stamp, uid
from .research_catalog import ResearchAccess, ResearchError, digest
from .research_context import merge_exposures


SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS rc_summary_meta(id TEXT PRIMARY KEY,revision TEXT NOT NULL,
       session_id TEXT NOT NULL,group_key TEXT NOT NULL,version INTEGER NOT NULL,
       manifest TEXT NOT NULL,raw_refs TEXT NOT NULL,parents TEXT NOT NULL,
       source_turn_ids TEXT NOT NULL,body_hash TEXT NOT NULL,body_bytes INTEGER NOT NULL,
       epoch INTEGER NOT NULL,created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS rc_summary_bodies(id TEXT PRIMARY KEY REFERENCES rc_summary_meta(id),body TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS rc_summary_coverage(turn_id TEXT PRIMARY KEY,summary_id TEXT NOT NULL REFERENCES rc_summary_meta(id))''',
    '''CREATE TABLE IF NOT EXISTS rc_summary_attempt(session_id TEXT NOT NULL,group_key TEXT NOT NULL,
       last_seq INTEGER NOT NULL,status TEXT NOT NULL,clock TEXT,PRIMARY KEY(session_id,group_key))''',
    '''CREATE TABLE IF NOT EXISTS rc_turn_summary_links(turn_id TEXT NOT NULL,summary_id TEXT NOT NULL,
       revision TEXT NOT NULL,body_hash TEXT NOT NULL,PRIMARY KEY(turn_id,summary_id))''',
    'CREATE INDEX IF NOT EXISTS rc_summary_session ON rc_summary_meta(session_id,version)',
)
META = 'id,revision,session_id,group_key,version,manifest,raw_refs,parents,source_turn_ids,body_hash,body_bytes,epoch,created_at'


def normalized_refs(refs):
    if type(refs) not in (list, tuple) or len(refs) > 64:
        raise ResearchError('invalid_summary_refs')
    result = {}
    for ref in refs:
        if type(ref) is not dict or set(ref) != {'id', 'revision', 'body_hash'}:
            raise ResearchError('invalid_summary_refs')
        uid(ref['id']); uid(ref['revision'])
        h = ref['body_hash']
        if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise ResearchError('invalid_summary_refs')
        if ref['id'] in result and result[ref['id']] != ref:
            raise ResearchError('inconsistent_summary_refs')
        result[ref['id']] = dict(ref)
    return [result[key] for key in sorted(result)]


def reference(meta):
    return {key: meta[key] for key in ('id', 'revision', 'body_hash')}


def group_key(manifest):
    courses = sorted({c for item in manifest for c in item['courses']})
    study = any(item['restriction'] == 'study' for item in manifest)
    return encoded({'scene': 'study' if study else 'casual', 'courses': courses})


class ResearchSummaries:
    def __init__(self, journal):
        self.journal = journal

    @staticmethod
    def initialize(db):
        row = db.execute("SELECT value FROM rc_meta WHERE key='summary_schema'").fetchone()
        if row and row[0] not in ('1', '2'):
            raise ResearchError('unsupported_summary_schema')
        for statement in SCHEMA:
            db.execute(statement)
        db.execute("CREATE TABLE IF NOT EXISTS rc_summary_reviews(summary_id TEXT PRIMARY KEY,revision TEXT NOT NULL,body_hash TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,at TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('summary_schema','2')")

    def access(self):
        scope = self.journal.scope.get()
        return scope.access if scope else ResearchAccess()

    @staticmethod
    def links(db, turn_id):
        return [{'id': r['summary_id'], 'revision': r['revision'], 'body_hash': r['body_hash']}
                for r in db.execute('SELECT summary_id,revision,body_hash FROM rc_turn_summary_links WHERE turn_id=? ORDER BY summary_id', (turn_id,))]

    @staticmethod
    def turn_stamp(db, turn_id, session_id):
        # Metadata only. Legitimate raw edits retire messages/epoch through the
        # journal barrier; source content hashes are checked again at commit.
        turn = db.execute('SELECT id,session_id,status,origin,epoch,user_id,assistant_id FROM lc_turns WHERE id=? AND session_id=?', (turn_id, session_id)).fetchone()
        session = db.execute('SELECT deleted FROM lc_sessions WHERE id=?', (session_id,)).fetchone()
        messages = [dict(r) for r in db.execute('SELECT id,role,allowed,reason,time FROM lc_messages WHERE turn_id=? ORDER BY role DESC', (turn_id,))]
        if not turn or turn['status'] != 'complete' or not session or session[0] or len(messages) != 2 or any(m['allowed'] != 1 for m in messages):
            raise ResearchError('summary_raw_source_retired')
        exposure = db.execute('SELECT scope,payload FROM rc_exposures WHERE turn_id=?', (turn_id,)).fetchone()
        return digest(encoded({'turn': dict(turn), 'messages': messages,
                               'exposure': dict(exposure) if exposure else None,
                               'summaries': ResearchSummaries.links(db, turn_id)}))

    def verify(self, db, ref, access):
        ref = normalized_refs([ref])[0]
        row = db.execute('SELECT ' + META + ' FROM rc_summary_meta WHERE id=?', (ref['id'],)).fetchone()
        if not row or reference(row) != ref:
            raise ResearchError('summary_revision_changed')
        data = dict(row)
        self.review_allowed(db, ref)
        if type(data['body_bytes']) is not int or not 1 <= data['body_bytes'] <= 6000:
            raise ResearchError('invalid_summary_size')
        manifest = merge_exposures([json.loads(data['manifest'])])
        if not manifest or group_key(manifest) != data['group_key']:
            raise ResearchError('invalid_summary_manifest')
        # Course authorization and current entry/source revisions FIRST.
        self.journal._verify(db, manifest, access)
        raw = json.loads(data['raw_refs'])
        if type(raw) is not dict or not 1 <= len(raw) <= 256:
            raise ResearchError('invalid_summary_raw_refs')
        sources = json.loads(data['source_turn_ids'])
        if type(sources) is not list or not 1 <= len(sources) <= 8 or len(set(sources)) != len(sources) or not set(sources) <= set(raw):
            raise ResearchError('invalid_summary_sources')
        for ident in sources:
            uid(ident)
        for parent in normalized_refs(json.loads(data['parents'])):
            self.review_allowed(db, parent)
            row = db.execute('SELECT id,revision,body_hash FROM rc_summary_meta WHERE id=?', (parent['id'],)).fetchone()
            if not row or reference(row) != parent:
                raise ResearchError('summary_parent_changed')
        for ident, expected in raw.items():
            uid(ident)
            if self.turn_stamp(db, ident, data['session_id']) != expected:
                raise ResearchError('summary_raw_source_changed')
        data.update(manifest=manifest, raw_refs=raw)
        return data

    @staticmethod
    def review_allowed(db, ref):
        row = db.execute('SELECT revision,body_hash,status FROM rc_summary_reviews WHERE summary_id=?', (ref['id'],)).fetchone()
        if row and (row['revision'] != ref['revision'] or row['body_hash'] != ref['body_hash'] or row['status'] not in ('supported', 'defer')):
            raise ResearchError('summary_review_rejected_or_changed')

    def metadata(self, session_id):
        current = self.journal.scope.get()
        if current and current.input_only:
            return []
        if current:
            current.validate_host()
        result = []
        with self.journal.read_connection() as db:
            self.journal._session(db, session_id)
            # Coarse ordinary filter occurs in SQL before LIMIT. verify() still
            # validates all fields and sources, including unknown/malformed data.
            where = 'session_id=?'
            if self.access().scene != 'study':
                where += " AND manifest NOT LIKE '%\"restriction\":\"study\"%'"
            rows = db.execute('SELECT ' + META + ' FROM rc_summary_meta WHERE ' + where + ' ORDER BY version DESC LIMIT 64', (session_id,)).fetchall()
            for row in rows:
                try:
                    meta = self.verify(db, reference(row), self.access())
                    result.append(meta)
                    if len(result) == 16:
                        break
                except (ValueError, KeyError, TypeError):
                    continue
        return result

    def read(self, ref):
        current = self.journal.scope.get()
        if current:
            current.validate_host()
            if current.input_only:
                raise ResearchError('summary_current_input_only')
        with self.journal.read_connection() as db:
            meta = self.verify(db, ref, self.access())
            row = db.execute('SELECT body FROM rc_summary_bodies WHERE id=?', (meta['id'],)).fetchone()
            if not row or digest(row[0]) != meta['body_hash'] or len(row[0].encode('utf-8')) != meta['body_bytes']:
                raise ResearchError('summary_body_integrity_failed')
            return {'id': meta['id'], 'revision': meta['revision'], 'version': meta['version'],
                    'text': row[0], 'source_turn_ids': json.loads(meta['source_turn_ids']),
                    'category': 'unconfirmed_research_summary'}

    def proxy(self, keep_recent, batch, minimum=3):
        current = self.journal.scope.get()
        if not current or current.input_only:
            return None
        current.validate_host()
        return SummaryWriter(self, keep_recent, batch, minimum)


class SummaryWriter:
    """Reuse ContextManager's bounded worker and SummaryAdapter unchanged.

    Summaries are independent delta blocks: no older summary text is sent as
    background, avoiding unreported summary-of-summary inputs. Actual raw turns
    can themselves depend on earlier summaries; their ancestry is flattened.
    """
    def __init__(self, summaries, keep_recent, batch, minimum):
        self.summaries = summaries
        self.journal = summaries.journal
        self.layers = getattr(self.journal, 'layers', None)  # preferences only
        self.keep_recent, self.batch = keep_recent, batch
        self.minimum = minimum
        self.group = None
        self.snapshot = {}
        self.content_hashes = {}

    def _candidates(self, db, due_days=None):
        sid = self.journal.scope.get().session_id
        recent = db.execute("SELECT seq FROM lc_turns WHERE session_id=? AND status='complete' ORDER BY seq DESC LIMIT ?", (sid, self.keep_recent)).fetchall()
        cutoff = min((r[0] for r in recent), default=0)
        where = "t.session_id=? AND t.status='complete' AND t.origin='user' AND t.seq<? AND r.payload!='[]' AND NOT EXISTS (SELECT 1 FROM rc_summary_coverage c WHERE c.turn_id=t.id)"
        if self.summaries.access().scene != 'study':
            where += " AND r.payload NOT LIKE '%\"restriction\":\"study\"%'"
        groups, due = {}, {}
        now = datetime.now(timezone.utc)
        for row in db.execute('SELECT t.* FROM lc_turns t JOIN rc_exposures r ON r.turn_id=t.id WHERE ' + where + ' ORDER BY t.seq LIMIT 512', (sid, cutoff)):
            if not self.journal._allowed(db, row['id']):
                continue
            record = self.journal._record(db, row['id'])
            key = group_key(record['manifest'])
            if due_days is not None:
                if key not in due:
                    attempt = db.execute('SELECT clock FROM rc_summary_attempt WHERE session_id=? AND group_key=?', (sid, key)).fetchone()
                    created = db.execute('SELECT created_at FROM lc_sessions WHERE id=?', (sid,)).fetchone()[0]
                    last = attempt[0] if attempt and attempt[0] else created
                    due[key] = (now - datetime.fromisoformat(last.replace('Z', '+00:00'))).total_seconds() >= due_days * 86400
                if not due[key]:
                    continue
            groups.setdefault(key, []).append(row)
        if self.group is None:
            self.group = next((key for key, rows in groups.items() if len(rows) >= self.minimum), next(iter(groups), None))
        return groups.get(self.group, [])

    def summary_due(self, session_id, days):
        with self.journal.read_connection() as db:
            self.journal._session(db, session_id)
            return bool(self._candidates(db, due_days=days))

    def summary_view(self, session_id, **kwargs):
        with self.journal.connection() as db:
            self.journal._owner(db); self.journal._session(db, session_id)
            rows = self._candidates(db)
            selected = rows[:self.batch]
            pairs = self.journal._pairs_from_rows(db, selected)
            self.snapshot = {p['id']: self.summaries.turn_stamp(db, p['id'], session_id) for p in pairs}
            self.content_hashes = {p['id']: digest(encoded(p['messages'])) for p in pairs}
            attempt = db.execute('SELECT last_seq,status FROM rc_summary_attempt WHERE session_id=? AND group_key=?', (session_id, self.group)).fetchone()
            latest = db.execute("SELECT MAX(seq) FROM lc_turns WHERE session_id=? AND status='complete'", (session_id,)).fetchone()[0] or 0
            return {'epoch': int(self.journal._get(db, 'epoch')), 'latest_seq': latest,
                    'new_turns': pairs, 'segments': [], 'old_unsummarized_turns': len(rows),
                    'last_attempt_seq': attempt[0] if attempt else 0,
                    'last_attempt_status': attempt[1] if attempt else 'never', 'owner': self.journal.owner}

    def summary_attempt(self, session_id, seq, status, *, epoch=None):
        with self.journal.connection() as db:
            self.journal._owner(db)
            if int(self.journal._get(db, 'epoch')) != epoch:
                return False
            db.execute('INSERT INTO rc_summary_attempt VALUES (?,?,?,?,NULL) ON CONFLICT(session_id,group_key) DO UPDATE SET last_seq=excluded.last_seq,status=excluded.status',
                       (session_id, self.group, seq, status))
        return True

    def commit_summary(self, session_id, view, turns, text):
        if type(text) is not str or not text.strip() or len(text) > 1500 or '\0' in text:
            return False
        if not turns or len(turns) > self.batch or len({t['id'] for t in turns}) != len(turns):
            return False
        current = self.journal.scope.get()
        if current is None:
            return False
        with current.publication_guard(), self.journal.connection() as db:
            self.journal._owner(db); self.journal._session(db, session_id)
            current.validate_host()
            if current.session_id != session_id or int(self.journal._get(db, 'epoch')) != view['epoch']:
                return False
            manifests, raw_refs, parents = [], {}, []
            for turn in turns:
                ident = turn['id']
                if ident not in self.snapshot or self.summaries.turn_stamp(db, ident, session_id) != self.snapshot[ident]:
                    return False
                if not self.journal._allowed(db, ident) or db.execute('SELECT 1 FROM rc_summary_coverage WHERE turn_id=?', (ident,)).fetchone():
                    return False
                record = self.journal._record(db, ident)
                if record is None or not record['manifest'] or group_key(record['manifest']) != self.group:
                    return False
                row = db.execute('SELECT * FROM lc_turns WHERE id=?', (ident,)).fetchone()
                actual = self.journal._pairs_from_rows(db, [row])
                if not actual or digest(encoded(actual[0]['messages'])) != self.content_hashes[ident] or digest(encoded(turn['messages'])) != self.content_hashes[ident]:
                    return False
                manifests.append(record['manifest'])
                raw_refs[ident] = self.snapshot[ident]
                for ref in record['summary_refs']:
                    meta = self.summaries.verify(db, ref, current.access)
                    manifests.append(meta['manifest']); parents.append(ref)
                    parents.extend(json.loads(meta['parents']))
                    for key, value in meta['raw_refs'].items():
                        if key in raw_refs and raw_refs[key] != value:
                            return False
                        raw_refs[key] = value
            manifest = merge_exposures(manifests)
            if len(raw_refs) > 256 or group_key(manifest) != self.group:
                return False
            self.journal._verify(db, manifest, current.access)
            version = (db.execute('SELECT MAX(version) FROM rc_summary_meta').fetchone()[0] or 0) + 1
            ident, revision = str(uuid.uuid4()), str(uuid.uuid4())
            db.execute('INSERT INTO rc_summary_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, revision, session_id, self.group, version, encoded(manifest), encoded(raw_refs),
                        encoded(normalized_refs(parents)), encoded([t['id'] for t in turns]), digest(text),
                        len(text.encode('utf-8')), view['epoch'], stamp()))
            db.execute('INSERT INTO rc_summary_bodies VALUES (?,?)', (ident, text))
            db.executemany('INSERT INTO rc_summary_coverage VALUES (?,?)', [(t['id'], ident) for t in turns])
            db.execute('UPDATE rc_summary_attempt SET clock=? WHERE session_id=? AND group_key=?', (stamp(), session_id, self.group))
        return True
