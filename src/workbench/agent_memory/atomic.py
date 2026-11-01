"""Independent Agent journal: reply and exposure share one transaction; no legacy migration."""
from contextlib import contextmanager
from pathlib import Path
import hashlib,json,sqlite3
from workbench.conversation_store import ConversationStore,SCHEMA,ChatStateError,encoded,uid

SCHEMA_VERSION=6
DDL=(
 'CREATE TABLE ag_seals(request_id TEXT PRIMARY KEY,reply_hash TEXT NOT NULL,manifest TEXT NOT NULL)',
 'CREATE TABLE ag_roots(request_id TEXT NOT NULL,scope TEXT NOT NULL,source_key TEXT NOT NULL,revision TEXT NOT NULL,source_hash TEXT NOT NULL,PRIMARY KEY(request_id,scope,source_key))',
)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def roots(value):
    if type(value) is not list or not 0<=len(value)<=8:raise ValueError('Explicit dependencies required')
    seen=set();result=[]
    for r in value:
        if type(r) is not dict or set(r)!={'scope','key','revision','hash'}:raise ValueError('Invalid dependency')
        uid(r['scope']);uid(r['revision'])
        if type(r['key']) is not str or not 1<=len(r['key'])<=150:raise ValueError('Invalid source key')
        if type(r['hash']) is not str or len(r['hash'])!=64 or any(c not in '0123456789abcdef' for c in r['hash']):raise ValueError('Invalid hash')
        key=(r['scope'],r['key'])
        if key in seen:raise ValueError('Duplicate dependency')
        seen.add(key);result.append(dict(r))
    return sorted(result,key=lambda r:(r['scope'],r['key']))

class AtomicJournal(ConversationStore):
    SUPPORTED_VERSIONS=(6,)
    def __init__(self,path,*,profile,core_loader=None):
        from .profile import validate_profile,profile_id
        self.profile=validate_profile(profile)
        self.profile_id=profile_id(self.profile)
        self.core_loader=core_loader
        path=Path(path)
        if path!=self.profile/'workbench/agent-chat-sessions.sqlite3':
            raise ValueError('Agent会话库须位于明确指定的独立资料目录。')
        path.parent.mkdir(parents=True,exist_ok=True)
        super().__init__(path)
    @contextmanager
    def connection(self):
        from .profile import validate_profile
        validate_profile(self.profile,self.profile_id)
        with self.guard:
            db=sqlite3.connect(self.path,timeout=1,isolation_level=None);db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version==0:
                    if db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():raise ValueError('Nonempty unknown database refused')
                    # SCHEMA is the trusted journal DDL, not external SQL. Avoid
                    # executescript, which may commit before the unit is sealed.
                    for sql in SCHEMA.split(';'):
                        if sql.strip():db.execute(sql)
                    for sql in DDL:db.execute(sql)
                    db.execute('PRAGMA user_version=6')
                elif version!=6:raise ValueError('Agent journal does not migrate existing schemas')
                yield db
                db.commit()
            except BaseException:
                db.rollback();raise
            finally:db.close()
    def complete(self,*args,**kwargs):raise ChatStateError('candidate_unwired','Use the explicit atomic storage API only')
    def recent(self,*args,**kwargs):raise ChatStateError('candidate_unwired','History eligibility not implemented')
    def _completed(self,*args,**kwargs):raise ChatStateError('candidate_unwired','Source-currentness gate required before replay')
    def complete_scoped(self,request_id,reply,epoch,ref_ids,dependencies):
        manifest=encoded(roots(dependencies));fingerprint=digest({'reply':{k:reply[k] for k in ('text','emotion','action')},'refs':ref_ids})
        with self.connection() as db:
            self._owner(db)
            old=db.execute('SELECT * FROM ag_seals WHERE request_id=?',(request_id,)).fetchone()
            if old:
                turn=db.execute('SELECT * FROM lc_turns WHERE id=?',(request_id,)).fetchone()
                message=db.execute('SELECT content FROM lc_messages WHERE id=?',(turn['assistant_id'],)).fetchone() if turn else None
                if old['manifest']!=manifest or old['reply_hash']!=fingerprint or not turn or turn['status']!='complete' or not message or message[0]!=reply['text']:
                    raise ChatStateError('request_conflict','Sealed storage descriptor changed')
                stored={'text':message[0],'emotion':turn['emotion'],'action':turn['action']}
                if digest({'reply':stored,'refs':json.loads(turn['ref_ids'])})!=fingerprint:
                    raise ChatStateError('request_conflict','Stored reply metadata differs from seal')
                actual=[{'scope':r['scope'],'key':r['source_key'],'revision':r['revision'],'hash':r['source_hash']} for r in db.execute('SELECT * FROM ag_roots WHERE request_id=? ORDER BY scope,source_key',(request_id,))]
                if encoded(actual)!=manifest:raise ChatStateError('request_conflict','Dependency rows differ from seal')
                return turn['assistant_id']
            message_id=self._complete(db,request_id,reply,epoch,ref_ids)
            for r in json.loads(manifest):db.execute('INSERT INTO ag_roots VALUES (?,?,?,?,?)',(request_id,r['scope'],r['key'],r['revision'],r['hash']))
            db.execute('INSERT INTO ag_seals VALUES (?,?,?)',(request_id,fingerprint,manifest))
            return message_id
