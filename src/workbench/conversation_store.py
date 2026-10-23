"""Local session journal and derived-data policy. No network or model calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

ORIGINS={'user','quote','fiction','external_ai','assistant','inference'}
SCOPES={'global','casual','technical','session','turn'}

class ChatStateError(ValueError):
    def __init__(self,code,message):self.code=code;super().__init__(message)

def uid(value):
    if type(value) is not str:raise ValueError('编号无效。')
    try:
        if str(uuid.UUID(value))!=value:raise ValueError()
    except ValueError:raise ValueError('编号无效。') from None
    return value

def stamp():return datetime.now(timezone.utc).isoformat(timespec='microseconds')
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def terms(text):
    text=text.casefold();result=set(re.findall(r'[a-z0-9_]{2,40}',text))
    for run in re.findall(r'[\u3400-\u9fff]+',text):result.update(run[i:i+2] for i in range(len(run)-1))
    for y,m,d in re.findall(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?',text):
        result.update([f'date:{y}-{int(m):02}-{int(d):02}',f'md:{int(m):02}-{int(d):02}'])
    for m,d in re.findall(r'(\d{1,2})月(\d{1,2})日',text):result.add(f'md:{int(m):02}-{int(d):02}')
    return sorted(result)[:256]

def query_terms(text):
    result=set(terms(text))
    if any(word in text for word in ['怎么称呼','叫什么','叫我什么']):result.update(['称呼','名字','昵称'])
    if any(word in text for word in ['哪天','什么时候','几号']):result.update(['日期','约定','计划'])
    return sorted(result)[:128]

SCHEMA='''
CREATE TABLE lc_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE lc_sessions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE lc_turns(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,session_id TEXT NOT NULL,
 status TEXT NOT NULL,origin TEXT NOT NULL,topic TEXT NOT NULL,created_at TEXT NOT NULL,
 user_id TEXT NOT NULL,assistant_id TEXT NOT NULL,attempt INTEGER NOT NULL,owner TEXT NOT NULL,
 epoch INTEGER NOT NULL,error_code TEXT NOT NULL DEFAULT '',emotion TEXT,action TEXT,ref_ids TEXT NOT NULL DEFAULT '[]',covered INTEGER NOT NULL DEFAULT 0);
CREATE TABLE lc_messages(id TEXT PRIMARY KEY,turn_id TEXT NOT NULL,session_id TEXT NOT NULL,
 role TEXT NOT NULL,time TEXT NOT NULL,origin TEXT NOT NULL,content TEXT NOT NULL,
 allowed INTEGER NOT NULL DEFAULT 1,reason TEXT NOT NULL DEFAULT '');
CREATE INDEX lc_messages_session ON lc_messages(session_id,turn_id);
CREATE TABLE lc_terms(message_id TEXT NOT NULL,term TEXT NOT NULL,PRIMARY KEY(message_id,term));
CREATE INDEX lc_terms_term ON lc_terms(term);
CREATE TABLE lc_summaries(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,version INTEGER NOT NULL,
 epoch INTEGER NOT NULL,source_ids TEXT NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE lc_summary_attempt(session_id TEXT PRIMARY KEY,last_seq INTEGER NOT NULL,status TEXT NOT NULL);
CREATE TABLE lc_note_policy(note_id TEXT PRIMARY KEY,revision TEXT,scope TEXT NOT NULL,event_state TEXT NOT NULL,
 source_ids TEXT NOT NULL,correction INTEGER NOT NULL DEFAULT 0);
CREATE TABLE lc_changes(id TEXT PRIMARY KEY,note_id TEXT,status TEXT NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE lc_candidates(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE lc_directives(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,request_id TEXT,source_ids TEXT NOT NULL,body TEXT NOT NULL,scope TEXT NOT NULL);
'''

class ConversationStore:
    """One active chat runtime per journal; a new owner explicitly retires old work."""
    def __init__(self,path):
        self.path=Path(path);self.guard=threading.RLock();self.owner=str(uuid.uuid4())
        with self.connection() as db:
            self._set(db,'owner',self.owner)
            db.execute("UPDATE lc_turns SET status='interrupted',error_code='runtime_restarted' WHERE status='pending'")
            if not self._get(db,'epoch'):self._set(db,'epoch','0')
            current=self._get(db,'selected')
            if not current:
                current=str(uuid.uuid4());db.execute('INSERT INTO lc_sessions VALUES (?,?,0)',(current,stamp()));self._set(db,'selected',current)
            self.session_id=current

    @contextmanager
    def connection(self):
        with self.guard:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA secure_delete=ON')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0,1):raise ValueError('候选会话库版本较新，未改写。')
                if version==0:db.executescript(SCHEMA+'PRAGMA user_version=1;')
                db.execute('BEGIN IMMEDIATE');yield db;db.commit()
            except Exception:db.rollback();raise
            finally:db.close()

    @staticmethod
    def _get(db,key):
        row=db.execute('SELECT value FROM lc_meta WHERE key=?',(key,)).fetchone();return row[0] if row else None

    @contextmanager
    def read_connection(self):
        """Archive/read bridges cannot create a DB, initialize schema or write."""
        with self.guard:
            db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
            db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db
            finally:db.close()
    @staticmethod
    def _set(db,key,value):db.execute('INSERT OR REPLACE INTO lc_meta VALUES (?,?)',(key,str(value)))
    def _owner(self,db):
        if self._get(db,'owner')!=self.owner:raise ChatStateError('runtime_changed','会话已由新的运行实例接管。')
    def _session(self,db,session_id):
        uid(session_id);row=db.execute('SELECT deleted FROM lc_sessions WHERE id=?',(session_id,)).fetchone()
        if not row or row[0]:raise ChatStateError('session_deleted','会话不存在或已删除。')
    def epoch(self):
        with self.connection() as db:return int(self._get(db,'epoch'))
    def retire_context(self,reason):
        with self.connection() as db:self._owner(db);self._barrier(db,reason)
    def sessions(self):
        with self.connection() as db:return [dict(r) for r in db.execute('SELECT * FROM lc_sessions WHERE deleted=0 ORDER BY created_at')]
    def _bump(self,db):
        n=int(self._get(db,'epoch'))+1;self._set(db,'epoch',n);return n
    def _barrier(self,db,reason):
        self._bump(db)
        db.execute("UPDATE lc_messages SET allowed=0,reason=? WHERE allowed=1",(reason,))
        db.execute("UPDATE lc_turns SET status='stale',error_code=? WHERE status='pending'",(reason,))
        for table in ['lc_terms','lc_summaries','lc_candidates','lc_directives','lc_summary_attempt']:db.execute('DELETE FROM '+table)

    def observe_notes(self,fingerprint):
        with self.connection() as db:
            self._owner(db);old=self._get(db,'notes_fingerprint')
            if old is not None and old!=fingerprint:self._barrier(db,'notes_changed')
            self._set(db,'notes_fingerprint',fingerprint)
            return old is not None and old!=fingerprint

    def begin_change(self,note_id,metadata):
        if note_id is not None:uid(note_id)
        with self.connection() as db:
            self._owner(db);self._barrier(db,'memory_change')
            change=str(uuid.uuid4());db.execute('INSERT INTO lc_changes VALUES (?,?,?,?,?)',(change,note_id,'prepared',encoded(metadata),stamp()));return change
    def finish_change(self,change_id,note_id,revision,fingerprint,metadata,*,failed=False):
        with self.connection() as db:
            self._owner(db)
            db.execute('UPDATE lc_changes SET status=? WHERE id=?',('failed' if failed else 'committed',change_id))
            self._set(db,'notes_fingerprint',fingerprint)
            if note_id and not failed:
                db.execute('INSERT OR REPLACE INTO lc_note_policy VALUES (?,?,?,?,?,?)',
                    (note_id,revision,metadata['scope'],metadata['event_state'],encoded(metadata['source_ids']),int(metadata.get('correction',False))))
    def pending_changes(self):
        with self.connection() as db:return [dict(r) for r in db.execute("SELECT id,note_id,created_at FROM lc_changes WHERE status='prepared'")]
    def acknowledge_change(self,change_id,*,note=None,applied=True):
        uid(change_id)
        with self.connection() as db:
            self._owner(db)
            row=db.execute("SELECT * FROM lc_changes WHERE id=? AND status='prepared'",(change_id,)).fetchone()
            if not row:raise ValueError('没有这个待核对操作。')
            if applied and note is not None:
                meta=json.loads(row['metadata'])
                db.execute('INSERT OR REPLACE INTO lc_note_policy VALUES (?,?,?,?,?,?)',
                    (note['id'],note['revision'],meta['scope'],meta['event_state'],encoded(meta['source_ids']),int(meta.get('correction',False))))
            db.execute("UPDATE lc_changes SET status='reviewed' WHERE id=?",(change_id,))
    def note_policies(self):
        with self.connection() as db:
            return {r['note_id']:{**dict(r),'source_ids':json.loads(r['source_ids'])} for r in db.execute('SELECT * FROM lc_note_policy')}

    def select_session(self,session_id=None):
        with self.connection() as db:
            self._owner(db)
            if session_id is None:
                session_id=str(uuid.uuid4());db.execute('INSERT INTO lc_sessions VALUES (?,?,0)',(session_id,stamp()))
            self._session(db,session_id);self._set(db,'selected',session_id);self.session_id=session_id
            self._bump(db);db.execute("UPDATE lc_turns SET status='cancelled',error_code='session_changed' WHERE status='pending' AND owner=?",(self.owner,))
            return session_id

    def begin_turn(self,session_id,text,request_id,origin='user',topic='unspecified'):
        uid(request_id)
        if type(origin) is not str or type(topic) is not str or origin not in ORIGINS-{'assistant'} or topic not in {'unspecified','casual','technical','other'}:raise ValueError('消息来源或话题范围无效。')
        with self.connection() as db:
            self._owner(db);self._session(db,session_id)
            old=db.execute('SELECT * FROM lc_turns WHERE id=?',(request_id,)).fetchone()
            if old:
                user=db.execute('SELECT * FROM lc_messages WHERE id=?',(old['user_id'],)).fetchone()
                if old['session_id']!=session_id or not user or user['content']!=text or old['origin']!=origin or old['topic']!=topic:raise ChatStateError('request_conflict','请求编号已用于其他内容。')
                if not user['allowed']:raise ChatStateError('request_retired','旧来源已失效，不能重放。')
                if old['status']=='complete':return {'cached':self._completed(db,old)}
                if old['status']=='pending':raise ChatStateError('busy','请求仍在处理中。')
                db.execute("UPDATE lc_turns SET status='pending',attempt=attempt+1,owner=?,epoch=?,error_code='' WHERE id=?",(self.owner,int(self._get(db,'epoch')),request_id))
                return {'request_id':request_id,'message_id':old['user_id']}
            user_id,assistant_id=str(uuid.uuid4()),str(uuid.uuid4());now=stamp()
            db.execute('INSERT INTO lc_turns(id,session_id,status,origin,topic,created_at,user_id,assistant_id,attempt,owner,epoch) VALUES (?,?,?,?,?,?,?,?,1,?,?)',
                (request_id,session_id,'pending',origin,topic,now,user_id,assistant_id,self.owner,int(self._get(db,'epoch'))))
            db.execute('INSERT INTO lc_messages(id,turn_id,session_id,role,time,origin,content) VALUES (?,?,?,?,?,?,?)',
                (user_id,request_id,session_id,'user',now,origin,text))
            return {'request_id':request_id,'message_id':user_id}
    def _completed(self,db,turn):
        assistant=db.execute('SELECT * FROM lc_messages WHERE id=?',(turn['assistant_id'],)).fetchone()
        if not assistant or not assistant['allowed']:raise ChatStateError('request_retired','旧回复已失效，不能重放。')
        return {'text':assistant['content'],'emotion':turn['emotion'],'action':turn['action'],
                'ref_ids':json.loads(turn['ref_ids']),'request_id':turn['id'],'message_id':turn['assistant_id'],'session_id':turn['session_id']}
    def complete(self,request_id,reply,epoch,ref_ids):
        with self.connection() as db:
            self._owner(db);turn=db.execute('SELECT * FROM lc_turns WHERE id=?',(request_id,)).fetchone()
            if not turn or turn['status']!='pending' or turn['owner']!=self.owner or turn['epoch']!=epoch or int(self._get(db,'epoch'))!=epoch:raise ChatStateError('stale_reply','已停止等待这条回复。')
            db.execute('INSERT INTO lc_messages(id,turn_id,session_id,role,time,origin,content) VALUES (?,?,?,?,?,?,?)',
                (turn['assistant_id'],request_id,turn['session_id'],'assistant',stamp(),'assistant',reply['text']))
            db.execute("UPDATE lc_turns SET status='complete',emotion=?,action=?,ref_ids=? WHERE id=?",(reply['emotion'],reply['action'],encoded(ref_ids),request_id))
            user=db.execute('SELECT content,allowed FROM lc_messages WHERE id=?',(turn['user_id'],)).fetchone()
            if user['allowed'] and turn['origin']=='user':
                db.executemany('INSERT OR IGNORE INTO lc_terms VALUES (?,?)',[(turn['user_id'],t) for t in terms(user['content'])])
            return turn['assistant_id']
    def fail(self,request_id,code='failed'):
        with self.connection() as db:db.execute("UPDATE lc_turns SET status='failed',error_code=? WHERE id=? AND status='pending' AND owner=?",(code,request_id,self.owner))
    def cancel_pending(self):
        with self.connection() as db:
            self._owner(db);self._bump(db)
            db.execute("UPDATE lc_turns SET status='cancelled',error_code='cancelled' WHERE status='pending' AND owner=?",(self.owner,))
    def reusable_request(self,session_id,text):
        with self.connection() as db:
            row=db.execute('SELECT t.id,t.status,t.origin,t.topic,m.content,m.allowed FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? ORDER BY t.seq DESC LIMIT 1',(session_id,)).fetchone()
            return row['id'] if row and row['allowed'] and row['origin']=='user' and row['topic']=='unspecified' and row['status'] in ('failed','interrupted') and row['content']==text else None

    def messages(self,session_id,*,limit=200,offset=0):
        if type(limit) is not int or not 1<=limit<=1000 or type(offset) is not int or offset<0:raise ValueError('分页参数无效。')
        with self.connection() as db:
            self._session(db,session_id)
            return [dict(r) for r in db.execute('SELECT m.*,t.status,t.seq,t.attempt FROM lc_messages m JOIN lc_turns t ON t.id=m.turn_id WHERE m.session_id=? ORDER BY t.seq,m.role DESC LIMIT ? OFFSET ?',(session_id,limit,offset))]
    @staticmethod
    def _pairs_from_rows(db,rows):
        result=[]
        for t in rows:
            msgs=[dict(r) for r in db.execute('SELECT * FROM lc_messages WHERE turn_id=? ORDER BY role DESC',(t['id'],))]
            if len(msgs)==2 and all(m['allowed'] for m in msgs):result.append({'id':t['id'],'seq':t['seq'],'origin':t['origin'],'messages':msgs})
        return result
    def recent(self,session_id,limit=6):
        with self.connection() as db:
            self._session(db,session_id)
            rows=list(db.execute("SELECT t.* FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? AND t.status='complete' AND m.allowed=1 ORDER BY t.seq DESC LIMIT ?",(session_id,limit)))
            return self._pairs_from_rows(db,reversed(rows))
    def retrieve(self,session_id,query,limit=3):
        wanted=query_terms(query)
        if not wanted:return []
        with self.connection() as db:
            self._session(db,session_id)
            rows=list(db.execute("SELECT t.*,COUNT(*) AS matches FROM lc_terms x JOIN lc_messages m ON m.id=x.message_id JOIN lc_turns t ON t.id=m.turn_id WHERE m.session_id=? AND m.allowed=1 AND t.status='complete' AND t.origin='user' AND x.term IN ("+','.join('?' for _ in wanted)+") GROUP BY t.id ORDER BY matches DESC,t.seq DESC LIMIT ?",(session_id,*wanted,limit)))
            pairs=self._pairs_from_rows(db,rows)
            for pair in pairs:
                pair['matched_terms']=sorted(set(terms(pair['messages'][0]['content']))&set(wanted))
            return pairs

    def summary_view(self,session_id,*,keep_recent=6,batch=6):
        with self.connection() as db:
            self._owner(db);self._session(db,session_id);epoch=int(self._get(db,'epoch'))
            latest=db.execute("SELECT MAX(seq) FROM lc_turns WHERE session_id=? AND status='complete'",(session_id,)).fetchone()[0] or 0
            recent=list(db.execute("SELECT t.seq FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? AND t.status='complete' AND m.allowed=1 ORDER BY t.seq DESC LIMIT ?",(session_id,keep_recent)))
            cutoff=min([r[0] for r in recent],default=0)
            rows=list(db.execute("SELECT t.* FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? AND t.status='complete' AND t.origin='user' AND t.covered=0 AND m.allowed=1 AND t.seq<? ORDER BY t.seq LIMIT ?",(session_id,cutoff,batch)))
            segments=[dict(r) for r in db.execute('SELECT * FROM lc_summaries WHERE session_id=? ORDER BY version DESC LIMIT 16',(session_id,))]
            attempt=db.execute('SELECT * FROM lc_summary_attempt WHERE session_id=?',(session_id,)).fetchone()
            remaining=db.execute("SELECT COUNT(*) FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? AND t.status='complete' AND t.origin='user' AND t.covered=0 AND m.allowed=1 AND t.seq<?",(session_id,cutoff)).fetchone()[0]
            return {'epoch':epoch,'latest_seq':latest,'new_turns':self._pairs_from_rows(db,rows),'segments':list(reversed(segments)),
                    'last_attempt_seq':attempt['last_seq'] if attempt else 0,'last_attempt_status':attempt['status'] if attempt else 'never',
                    'old_unsummarized_turns':remaining,'owner':self.owner}
    def summary_due(self,session_id,days,*,now=None):
        if type(days) is not int or days<1:raise ValueError('摘要间隔至少一天。')
        moment=now or datetime.now(timezone.utc)
        with self.connection() as db:
            self._owner(db);self._session(db,session_id)
            created=db.execute('SELECT created_at FROM lc_sessions WHERE id=?',(session_id,)).fetchone()[0]
            last=self._get(db,'summary_clock:'+session_id) or created
            return (moment-datetime.fromisoformat(last.replace('Z','+00:00'))).total_seconds()>=days*86400

    def summary_attempt(self,session_id,seq,status,*,epoch=None):
        with self.connection() as db:
            self._owner(db)
            if epoch is not None and int(self._get(db,'epoch'))!=epoch:return False
            db.execute('INSERT OR REPLACE INTO lc_summary_attempt VALUES (?,?,?)',(session_id,seq,status));return True
    def commit_summary(self,session_id,view,turns,text):
        with self.connection() as db:
            self._owner(db)
            if int(self._get(db,'epoch'))!=view['epoch']:return False
            for turn in turns:
                r=db.execute('SELECT t.covered,t.status,m.allowed FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.id=? AND t.session_id=?',(turn['id'],session_id)).fetchone()
                if not r or r['covered'] or r['status']!='complete' or not r['allowed']:return False
            self._set(db,'summary_clock:'+session_id,stamp())
            version=int(self._get(db,'summary_version') or '0')+1;self._set(db,'summary_version',version)
            summary={'id':str(uuid.uuid4()),'session_id':session_id,'version':version,'epoch':view['epoch'],'source_ids':encoded([t['id'] for t in turns]),'text':text,'created_at':stamp()}
            db.execute('INSERT INTO lc_summaries VALUES (:id,:session_id,:version,:epoch,:source_ids,:text,:created_at)',summary)
            if getattr(self,'layers',None) is not None:self.layers.ingest(db,summary)
            db.executemany('UPDATE lc_turns SET covered=1 WHERE id=?',[(t['id'],) for t in turns])
            db.execute('DELETE FROM lc_summaries WHERE session_id=? AND id NOT IN (SELECT id FROM lc_summaries WHERE session_id=? ORDER BY version DESC LIMIT 16)',(session_id,session_id))
            return True
    def source_messages(self,ids,*,session_id=None):
        if type(ids) is not list or not 1<=len(ids)<=8 or any(type(i) is not str for i in ids) or len(set(ids))!=len(ids):raise ValueError('请提供1～8个来源消息编号。')
        for i in ids:uid(i)
        with self.connection() as db:
            result=[]
            for i in ids:
                r=db.execute('SELECT m.*,t.status FROM lc_messages m JOIN lc_turns t ON t.id=m.turn_id WHERE m.id=?',(i,)).fetchone()
                if not r or not r['allowed'] or r['role']!='user' or r['origin']!='user' or r['status']!='complete' or session_id and r['session_id']!=session_id:raise ValueError('来源尚未确认、已失效或不是用户本人陈述。')
                result.append(dict(r))
            return result
    def add_candidate(self,session_id,proposal):
        with self.connection() as db:
            self._owner(db);self._session(db,session_id)
            if db.execute('SELECT count(*) FROM lc_candidates').fetchone()[0]>=100:raise ValueError('待确认候选过多，请先整理。')
            i=str(uuid.uuid4());db.execute('INSERT INTO lc_candidates VALUES (?,?,?,?)',(i,session_id,encoded(proposal),stamp()));return i
    def candidate(self,i):
        uid(i)
        with self.connection() as db:
            r=db.execute('SELECT * FROM lc_candidates WHERE id=?',(i,)).fetchone()
            if not r:raise ValueError('候选已失效，请重新确认。')
            return dict(r)|{'payload':json.loads(r['payload'])}
    def add_directive(self,session_id,proposal):
        with self.connection() as db:
            self._owner(db);self._barrier(db,'local_correction')
            i=str(uuid.uuid4());db.execute('INSERT INTO lc_directives VALUES (?,?,?,?,?,?)',(i,session_id,proposal['request_id'],encoded(proposal['source_ids']),proposal['note']['body'],proposal['scope']));return i
    def directives(self,session_id,request_id):
        with self.connection() as db:return [dict(r) for r in db.execute('SELECT id,scope,body,source_ids FROM lc_directives WHERE session_id=? AND (request_id IS NULL OR request_id=?)',(session_id,request_id))]
    def remove_candidate(self,i):
        with self.connection() as db:db.execute('DELETE FROM lc_candidates WHERE id=?',(i,))
    def remove_source(self,message_id):
        uid(message_id)
        with self.connection() as db:
            self._owner(db);r=db.execute('SELECT turn_id FROM lc_messages WHERE id=?',(message_id,)).fetchone()
            if not r:raise ValueError('来源不存在。')
            self._barrier(db,'source_removed')
            db.execute("UPDATE lc_messages SET content='',allowed=0,reason='source_removed' WHERE turn_id=?",(r['turn_id'],))
            if getattr(self,'layers',None) is not None:self.layers.invalidate_sources(db);self.layers.backfill(db)
    def delete_session(self,session_id):
        with self.connection() as db:
            self._owner(db);self._session(db,session_id);self._barrier(db,'session_deleted')
            db.execute('DELETE FROM lc_messages WHERE session_id=?',(session_id,))
            # Retain only content-free request ids so purged requests cannot be reused.
            db.execute("UPDATE lc_turns SET status='deleted',emotion=NULL,action=NULL,ref_ids='[]' WHERE session_id=?",(session_id,))
            db.execute('UPDATE lc_sessions SET deleted=1 WHERE id=?',(session_id,))
            if getattr(self,'layers',None) is not None:self.layers.invalidate_sources(db);self.layers.backfill(db)
        if self.session_id==session_id:return self.select_session()
        return self.session_id
