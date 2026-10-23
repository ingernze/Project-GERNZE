"""Agent-side journal and pending summaries. Existing desktop stores are read-only."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import uuid


def stamp():
    return datetime.now(timezone.utc).isoformat()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('内容为空或超出长度限制。')
    return value


class Bridge:
    def __init__(self, config):
        self.config = config
        self.path = Path(config['state_db']).resolve()
        self.persona = Path(config['persona']).resolve()
        self.foundation = Path(config['foundation']).resolve()
        self.desktop = Path(config['desktop_journal']).resolve() if config.get('desktop_journal') else None
        if self.path in {self.persona, self.foundation, self.desktop}:
            raise ValueError('新模块存储必须独立，不能接管现有文件。')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS agent_sessions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS agent_turns(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              id TEXT UNIQUE NOT NULL,session_id TEXT NOT NULL,turn_key TEXT NOT NULL,
              user_text TEXT NOT NULL,assistant_text TEXT NOT NULL,created_at TEXT NOT NULL,
              UNIQUE(session_id,turn_key));
            CREATE TABLE IF NOT EXISTS agent_working(key TEXT PRIMARY KEY,revision TEXT NOT NULL,
              body TEXT NOT NULL,sources_json TEXT NOT NULL,source_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,updated_at TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def core(self):
        persona = text(self.persona.read_text(encoding='utf-8'), 8000)
        value = json.loads(self.foundation.read_text(encoding='utf-8'))
        if value.get('schemaVersion') != 1 or not isinstance(value.get('entries'), list) or len(value['entries']) > 20:
            raise ValueError('第一层基础格式不正确。')
        keys = set()
        for row in value['entries']:
            key = text(row.get('key'), 100)
            text(row.get('body'), 1000)
            if key in keys:
                raise ValueError('第一层键重复。')
            keys.add(key)
        return {'persona': persona, 'foundation': value['entries'], 'readOnly': True}

    def session(self, db, session_id):
        if not db.execute('SELECT 1 FROM agent_sessions WHERE id=?', (session_id,)).fetchone():
            raise ValueError('没有这个莉宝会话，请先开启会话。')

    def begin(self):
        self.core()  # Fail before creating a session if mandatory L1 cannot be loaded.
        session_id = str(uuid.uuid4())
        with self.db() as db:
            db.execute('INSERT INTO agent_sessions VALUES (?,?)', (session_id, stamp()))
        return {'sessionId': session_id, 'context': self.context(session_id)}

    def record(self, session_id, turn_key, user_text, assistant_text):
        turn_key = text(turn_key, 100)
        user_text, assistant_text = text(user_text, 12000), text(assistant_text, 12000)
        with self.db() as db:
            self.session(db, session_id)
            old = db.execute('SELECT * FROM agent_turns WHERE session_id=? AND turn_key=?', (session_id, turn_key)).fetchone()
            if old:
                if (old['user_text'], old['assistant_text']) != (user_text, assistant_text):
                    raise ValueError('这个轮次编号已有不同内容，未覆盖。')
                return {'turnId': old['id'], 'alreadySaved': True}
            turn_id = str(uuid.uuid4())
            db.execute('INSERT INTO agent_turns(id,session_id,turn_key,user_text,assistant_text,created_at) VALUES (?,?,?,?,?,?)',
                       (turn_id, session_id, turn_key, user_text, assistant_text, stamp()))
        return {'turnId': turn_id, 'alreadySaved': False, 'provenance': 'agent_reported'}

    @staticmethod
    def row(row):
        return {'key': row['key'], 'revision': row['revision'], 'body': row['body'],
                'sourceRefs': json.loads(row['sources_json']), 'sourceHash': row['source_hash'],
                'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
                'deleted': bool(row['deleted']), 'tier': 3, 'status': 'pending',
                'provenance': 'agent_reported', 'approved': False}

    def pending(self):
        with self.db() as db:
            return [self.row(r) for r in db.execute('SELECT * FROM agent_working ORDER BY updated_at DESC')]

    def sources(self, session_id, limit=12):
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError('每批读取1到30轮。')
        with self.db() as db:
            self.session(db, session_id)
            rows = db.execute('SELECT * FROM agent_turns WHERE session_id=? ORDER BY seq DESC LIMIT ?', (session_id, limit)).fetchall()
        # Display order is chronological; source IDs are immutable.
        turns = [dict(r) for r in reversed(rows)]
        for t in turns:
            t['provenance'] = 'agent_reported'
        return {'sessionId': session_id, 'turns': turns, 'sourceHash': digest(turns)}

    def remember(self, session_id, turn_ids, body, expected_revision=None):
        body = text(body, 1000)
        if not isinstance(turn_ids, list) or not 1 <= len(turn_ids) <= 12 or len(set(turn_ids)) != len(turn_ids) or any(not isinstance(i, str) for i in turn_ids):
            raise ValueError('请提供1到12个不同来源轮次。')
        with self.db() as db:
            self.session(db, session_id)
            rows = []
            for turn_id in turn_ids:
                r = db.execute('SELECT * FROM agent_turns WHERE id=? AND session_id=?', (turn_id, session_id)).fetchone()
                if not r:
                    raise ValueError('来源不属于本次莉宝会话。')
                rows.append(dict(r))
            rows.sort(key=lambda r: r['seq'])
            refs = [{'client': 'codex', 'sessionId': session_id, 'turnId': r['id']} for r in rows]
            key = 'agent:' + digest(refs)
            old = db.execute('SELECT * FROM agent_working WHERE key=?', (key,)).fetchone()
            if old and old['deleted']:
                raise ValueError('这组来源已撤回，不能重放恢复。')
            if old and old['body'] == body:
                return {**self.row(old), 'alreadySaved': True}
            if (old['revision'] if old else None) != expected_revision:
                raise ValueError('第三层版本已变化，请读取最新版本再整理。')
            now, revision = stamp(), str(uuid.uuid4())
            db.execute('INSERT OR REPLACE INTO agent_working VALUES (?,?,?,?,?,?,?,0)',
                       (key, revision, body, packed(refs), digest(rows), old['created_at'] if old else now, now))
            return self.row(db.execute('SELECT * FROM agent_working WHERE key=?', (key,)).fetchone())

    def retract(self, key, expected_revision):
        with self.db() as db:
            r = db.execute('SELECT * FROM agent_working WHERE key=?', (key,)).fetchone()
            if not r or r['revision'] != expected_revision or r['deleted']:
                raise ValueError('第三层版本已变化，未撤回。')
            db.execute('UPDATE agent_working SET body=?,deleted=1,revision=?,updated_at=? WHERE key=?',
                       ('', str(uuid.uuid4()), stamp(), key))
        return {'key': key, 'deleted': True, 'tier': 3}

    def desktop_summaries(self):
        if not self.desktop or not self.desktop.is_file():
            return [], 'unavailable'
        # No ConversationStore construction: it would retire the running desktop owner.
        db = sqlite3.connect(self.desktop.as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            epoch = db.execute("SELECT value FROM lc_meta WHERE key='epoch'").fetchone()
            if epoch is None:
                return [], 'unavailable'
            rows = db.execute('SELECT s.* FROM lc_summaries s JOIN lc_sessions c ON c.id=s.session_id WHERE s.epoch=? AND c.deleted=0 ORDER BY s.created_at DESC LIMIT 16', (int(epoch[0]),)).fetchall()
            return [{'key': 'desktop:' + r['id'], 'body': r['text'], 'tier': 3,
                     'status': 'legacy-summary', 'sourceRefs': json.loads(r['source_ids']),
                     'createdAt': r['created_at']} for r in rows], 'read-only'
        except sqlite3.DatabaseError:
            return [], 'unsupported-schema'
        finally:
            db.close()

    def context(self, session_id, query=''):
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('检索内容过长。')
        first = self.core()
        with self.db() as db:
            self.session(db, session_id)
        legacy, desktop_status = self.desktop_summaries()
        approved, tier2_status = self.approved()
        blocked = {r['key'] for r in approved}
        working = [r for r in self.pending() if not r['deleted'] and r['key'] not in blocked] + legacy
        terms = set(re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2}', query.lower()))
        working.sort(key=lambda r: sum(t in r['body'].lower() for t in terms), reverse=True)
        approved = [r for r in approved if not r.get('deleted')]
        approved.sort(key=lambda r: sum(t in r['body'].lower() for t in terms), reverse=True)
        return {'tier1': first, 'tier2': approved[:6], 'tier3': working[:6],
                'tier2Status': tier2_status, 'desktopStatus': desktop_status,
                'sessionId': session_id, 'desktopWrites': False,
                'desktopConsumesAgentTier3': False,
                'notice': '第三层是未审核资料，不能覆盖第一、二层；未接通的第二层不能当成空库。'}

    def approved(self):
        path = self.config.get('approved_snapshot')
        if not path or not Path(path).is_file():
            if self.desktop and self.desktop.is_file():
                db=sqlite3.connect(self.desktop.as_uri()+'?mode=ro',uri=True,timeout=2)
                db.row_factory=sqlite3.Row
                try:
                    db.execute('PRAGMA query_only=ON')
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lm_approved'").fetchone():
                        blocked={r[0] for r in db.execute('SELECT key FROM lm_sync_conflicts WHERE tier=2')} if db.execute("SELECT 1 FROM sqlite_master WHERE name='lm_sync_conflicts'").fetchone() else set()
                        return [dict(r) for r in db.execute('SELECT key,revision,body,deleted FROM lm_approved WHERE deleted=0') if r['key'] not in blocked], 'read-only-desktop'
                finally:db.close()
            return [], 'awaiting_desktop_layer_adapter'
        p = Path(path).resolve()
        if p == self.path or p.stat().st_size > 1024 * 1024:
            raise ValueError('第二层只读快照无效。')
        value = json.loads(p.read_text(encoding='utf-8'))
        if value.get('format') != 'gernze-approved-snapshot-v1' or value.get('tier') != 2 or not isinstance(value.get('entries'), list) or len(value['entries']) > 1000:
            raise ValueError('第二层只读快照格式无效。')
        keys = set()
        for r in value['entries']:
            key = text(r.get('key'), 150)
            text(r.get('revision'), 100)
            if not isinstance(r.get('body'), str) or len(r['body']) > 2000 or key in keys or type(r.get('deleted', False)) is not bool:
                raise ValueError('第二层条目无效。')
            keys.add(key)
        return value['entries'], 'read-only'


def read_agent_working(path):
    """Read-only desktop adapter. Does not initialize or claim any runtime."""
    p = Path(path).resolve()
    if not p.is_file():
        return {'format': 'gernze-agent-working-v1', 'tier': 3, 'entries': [], 'available': False}
    db = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        return {'format': 'gernze-agent-working-v1', 'tier': 3,
                'entries': [Bridge.row(r) for r in db.execute('SELECT * FROM agent_working ORDER BY updated_at DESC')],
                'available': True}
    finally:
        db.close()
