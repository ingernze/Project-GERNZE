"""Transactional notes + retained revision graph. No networking or background work."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid

if __package__:
    from .companion_memory import CompanionMemory, SCHEMA, validate, identifier
    from . import memory_merge as mm
else:
    from companion_memory import CompanionMemory, SCHEMA, validate, identifier
    import memory_merge as mm


SYNC_SCHEMA = (
    'CREATE TABLE memory_sync_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
    'CREATE TABLE memory_sync_revisions(revision TEXT PRIMARY KEY,id TEXT NOT NULL,parents_json TEXT NOT NULL,deleted INTEGER NOT NULL CHECK(deleted IN(0,1)),record_digest TEXT NOT NULL)',
    'CREATE TABLE memory_sync_pending(revision TEXT PRIMARY KEY,id TEXT NOT NULL,record_json TEXT NOT NULL)',
)


class PersistentMemory(CompanionMemory):
    """One authenticated scope/local identity binding per notes file, passed by host."""
    def __init__(self,path,*,expected_scope,device_id,fault_hook=None):
        super().__init__(path)
        self.scope=mm.identifier(expected_scope);self.device_id=mm.identifier(device_id)
        self.fault_hook=fault_hook

    def _scope(self,expected_scope):
        if mm.identifier(expected_scope)!=self.scope:mm.fail('scope_mismatch')

    def _fault(self,stage):
        if self.fault_hook is not None:self.fault_hook(stage)

    @staticmethod
    def _meta(db,key):
        row=db.execute('SELECT value FROM memory_sync_meta WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _set(db,key,value):db.execute('INSERT OR REPLACE INTO memory_sync_meta VALUES (?,?)',(key,value))

    @staticmethod
    def _rows(db):
        # Same strict SQLite 0/1 conversion as the supplied companion_adapter.
        rows=[dict(r) for r in db.execute('SELECT * FROM notes ORDER BY id')]
        for row in rows:
            if set(row)!=mm.RECORD_FIELDS:mm.fail('unexpected_fields')
            for key in ('chat_enabled','important','deleted'):
                if type(row[key]) is not int or row[key] not in (0,1):mm.fail('invalid_sqlite_boolean')
                row[key]=bool(row[key])
        return rows

    def _initialize(self,db):
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sync={n for n in tables if n.startswith('memory_sync_')}
        if sync:
            if sync!={'memory_sync_meta','memory_sync_revisions','memory_sync_pending'}:mm.fail('unknown_sync_schema')
            if self._meta(db,'schema_version')!='1':mm.fail('unknown_sync_version')
            if self._meta(db,'scope_id')!=self.scope:mm.fail('scope_mismatch')
            if self._meta(db,'device_id')!=self.device_id:mm.fail('local_identity_mismatch')
            return
        initial=mm.export_records(self._rows(db),expected_scope=self.scope)
        if mm.inspect(initial,expected_scope=self.scope)['limits']:mm.fail('legacy_limits_need_review')
        for statement in SYNC_SCHEMA:db.execute(statement)
        for key,value in [('schema_version','1'),('scope_id',self.scope),('device_id',self.device_id)]:self._set(db,key,value)
        self._persist(db,initial)

    @contextmanager
    def connection(self):
        with self.guard:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            db=sqlite3.connect(self.path,timeout=2,isolation_level=None);db.row_factory=sqlite3.Row
            try:
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0,1):raise ValueError('记忆文件版本较新，未改写，请更新莉宝。')
                mode=db.execute('PRAGMA journal_mode').fetchone()[0].lower()
                if mode in ('off','memory'):mm.fail('unsafe_journal_mode')
                db.execute('PRAGMA secure_delete=ON');db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                if version==0:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():mm.fail('unrecognized_legacy_schema')
                    # Unlike executescript(), individual statements do not force an early COMMIT.
                    for statement in SCHEMA.split(';'):
                        if statement.strip():db.execute(statement)
                db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('device_id',self.device_id))
                self._initialize(db);self._load(db)
                yield db
                self._load(db)  # Reject bypass writes which did not maintain graph/projection.
                self._fault('before_commit');db.commit()
            except BaseException:
                db.rollback();raise
            finally:db.close()

    def _load(self,db):
        rows=self._rows(db)
        if self._meta(db,'projection_digest')!=mm.digest(rows):mm.fail('notes_projection_changed_outside_adapter')
        by_revision={r['revision']:r for r in rows}
        for item in db.execute('SELECT * FROM memory_sync_pending'):
            row=json.loads(item['record_json'])
            if row['revision']!=item['revision'] or row['id']!=item['id']:mm.fail('corrupt_sync_store')
            if row['revision'] in by_revision:mm.fail('corrupt_sync_store')
            by_revision[row['revision']]=row
        nodes=[{'revision':r['revision'],'id':r['id'],'parents':json.loads(r['parents_json']),
                'deleted':bool(r['deleted']),'digest':r['record_digest']} for r in db.execute('SELECT * FROM memory_sync_revisions')]
        return mm.validate_snapshot({'format':mm.FORMAT,'version':mm.VERSION,'scope_id':self.scope,
                'records':list(by_revision.values()),'revisions':nodes},expected_scope=self.scope)

    def _persist(self,db,state):
        state=mm.validate_snapshot(state,expected_scope=self.scope);report=mm.inspect(state,expected_scope=self.scope)
        # Legacy notes remains a safe, capacity-bounded current projection. All unresolved
        # leaf bodies are explicit pending records; no synthetic tombstone is fabricated.
        projection={} if report['limits'] else {r['id']:r for r in report['active_records']}
        for row in state['records']:
            if row['deleted'] and (row['id'] not in projection or row['revision']<projection[row['id']]['revision']):projection[row['id']]=row
        ordered=[projection[k] for k in sorted(projection)]
        if self._rows(db)!=ordered:
            db.execute('DELETE FROM notes')
            columns=sorted(mm.RECORD_FIELDS)
            db.executemany('INSERT INTO notes('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                           [tuple(row[k] for k in columns) for row in ordered])
        self._fault('after_notes')
        db.execute('DELETE FROM memory_sync_revisions');db.execute('DELETE FROM memory_sync_pending')
        db.executemany('INSERT INTO memory_sync_revisions VALUES (?,?,?,?,?)',[(n['revision'],n['id'],mm.canonical(n['parents']).decode(),int(n['deleted']),n['digest']) for n in state['revisions']])
        projected={r['revision'] for r in ordered}
        db.executemany('INSERT INTO memory_sync_pending VALUES (?,?,?)',[(r['revision'],r['id'],mm.canonical(r).decode()) for r in state['records'] if r['revision'] not in projected])
        self._set(db,'projection_digest',mm.digest(ordered));self._fault('after_graph')

    @staticmethod
    def _manual_limits(state,scope):
        for limit in mm.inspect(state,expected_scope=scope)['limits']:
            if limit['code']=='record_limit':raise ValueError('本轮最多保存100条记忆，请先整理已有记录。')
            if limit['code']=='chat_limit':raise ValueError('聊天最多参考6条记忆，请先取消一条的“用于聊天”。')

    def save(self,note,*,record_id=None,revision=None):
        note=validate(note);mm.validate_note(note)
        if (record_id is None)!=(revision is None):raise ValueError('纠正记忆需要原编号和版本。')
        if record_id is not None:identifier(record_id);identifier(revision)
        with self.connection() as db:
            state=self._load(db);timestamp=datetime.now(timezone.utc).isoformat(timespec='microseconds')
            if record_id is None:
                row={'id':str(uuid.uuid4()),'revision':str(uuid.uuid4()),'parent_revision':None,'device_id':self.device_id,
                     **note,'created_at':timestamp,'updated_at':timestamp,'deleted':False}
                new=mm.merge(state,mm.export_records([row],expected_scope=self.scope),expected_scope=self.scope)
            else:
                old=db.execute('SELECT revision FROM notes WHERE id=? AND deleted=0',(record_id,)).fetchone()
                if not old or old[0]!=revision:raise ValueError('这条记忆已经变化，请刷新后再修改。')
                new=mm.commit_decision(state,record_id,expected_scope=self.scope,expected_fingerprint=mm.digest(state),
                    device_id=self.device_id,revision=str(uuid.uuid4()),timestamp=timestamp,note=note)
                row=next(r for r in new['records'] if r['id']==record_id and r['revision']!=revision)
            self._manual_limits(new,self.scope);self._persist(db,new);return row

    def forget(self,record_id,revision):
        identifier(record_id);identifier(revision)
        with self.connection() as db:
            old=db.execute('SELECT revision FROM notes WHERE id=? AND deleted=0',(record_id,)).fetchone()
            if not old or old[0]!=revision:raise ValueError('这条记忆已经变化，请刷新后再操作。')
            state=self._load(db)
            new=mm.commit_decision(state,record_id,expected_scope=self.scope,expected_fingerprint=mm.digest(state),
                device_id=self.device_id,revision=str(uuid.uuid4()),timestamp=datetime.now(timezone.utc).isoformat(timespec='microseconds'),delete=True)
            self._persist(db,new)
        return {'forgotten':True}

    def _remote(self,remote,scope):
        return mm.load_snapshot(remote,expected_scope=scope) if type(remote) in (bytes,str) else mm.validate_snapshot(remote,expected_scope=scope)

    def export_exchange(self,*,expected_scope):
        self._scope(expected_scope)
        with self.connection() as db:return self._load(db)

    def export_json(self,*,expected_scope):return mm.canonical(self.export_exchange(expected_scope=expected_scope))

    def status(self,*,expected_scope):
        state=self.export_exchange(expected_scope=expected_scope)
        return {'fingerprint':mm.digest(state),'report':mm.inspect(state,expected_scope=expected_scope)}

    def preview(self,remote,*,expected_scope):
        self._scope(expected_scope);remote=self._remote(remote,expected_scope)
        with self.connection() as db:return mm.make_plan(self._load(db),remote,expected_scope=expected_scope)

    def apply(self,remote,plan,*,expected_scope):
        self._scope(expected_scope);remote=self._remote(remote,expected_scope)
        with self.connection() as db:
            current=self._load(db);result=mm.apply_plan(current,remote,plan,expected_scope=expected_scope)
            if result['applied'] and result['snapshot']!=current:self._persist(db,result['snapshot'])
            return result

    def stage_conflicts(self,remote,plan,*,expected_scope):
        """Explicit acceptance into quarantine, distinct from apply_plan's fact commit."""
        self._scope(expected_scope);remote=self._remote(remote,expected_scope)
        with self.connection() as db:
            current=self._load(db);checked=mm.apply_plan(current,remote,plan,expected_scope=expected_scope)
            if checked['status']=='needs_refresh':return checked
            if checked['status']!='needs_decision':mm.fail('staging_requires_conflict_or_limit')
            proposed=plan['proposed']
            if proposed!=current:self._persist(db,proposed)
            return {'status':'needs_decision','applied':False,'staged':True,'fingerprint':mm.digest(proposed),
                    'conflicts':plan['report']['conflicts'],'limits':plan['report']['limits']}

    def decide(self,record_id,*,expected_scope,expected_fingerprint,note=None,delete=False,confirmed=False):
        self._scope(expected_scope)
        if confirmed is not True:mm.fail('explicit_confirmation_required')
        if note is not None:note=validate(note)
        with self.connection() as db:
            state=self._load(db)
            new=mm.commit_decision(state,record_id,expected_scope=expected_scope,expected_fingerprint=expected_fingerprint,
                device_id=self.device_id,revision=str(uuid.uuid4()),timestamp=datetime.now(timezone.utc).isoformat(timespec='microseconds'),note=note,delete=delete)
            self._persist(db,new)
            return {'status':mm.inspect(new,expected_scope=expected_scope)['status'],'fingerprint':mm.digest(new)}
