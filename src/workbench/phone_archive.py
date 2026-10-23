"""Append-only plain-text phone archive. Not a chat runtime or model tool store."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import hashlib,json,sqlite3
from .conversation_store import encoded,uid

FORMAT='gernze-phone-raw-v1'
ZERO='0'*64
def chain(previous,turn):return hashlib.sha256(encoded({'previous':previous,'turn':turn}).encode('utf8')).hexdigest()
def valid_turn(t,index):
    if type(t) is not dict or set(t)!={'index','user','assistant','userAt','assistantAt'} or type(t['index']) is not int or t['index']!=index:raise ValueError('invalid_raw_turn')
    for k in ['user','assistant']:
        if type(t[k]) is not str or not t[k] or len(t[k])>12000:raise ValueError('invalid_raw_turn')
    for k in ['userAt','assistantAt']:
        if t[k] is None:continue
        if type(t[k]) is not str or len(t[k])>40:raise ValueError('invalid_raw_time')
        try:
            if datetime.fromisoformat(t[k].replace('Z','+00:00')).tzinfo is None:raise ValueError()
        except ValueError:raise ValueError('invalid_raw_time') from None
    return t

class PhoneArchive:
    def __init__(self,journal):self.path=Path(journal).with_name('paired-phone-raw.sqlite3')
    @contextmanager
    def connection(self,write=False):
        if not write and not self.path.is_file():yield None;return
        if write:self.path.parent.mkdir(parents=True,exist_ok=True)
        uri=self.path.resolve().as_uri()+('?mode=rwc' if write else '?mode=ro')
        db=sqlite3.connect(uri,uri=True,timeout=5);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA secure_delete=ON' if write else 'PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                db.execute('CREATE TABLE IF NOT EXISTS sessions(device TEXT NOT NULL,session TEXT NOT NULL,count INTEGER NOT NULL,chain TEXT NOT NULL,PRIMARY KEY(device,session))')
                db.execute('CREATE TABLE IF NOT EXISTS turns(device TEXT NOT NULL,session TEXT NOT NULL,seq INTEGER NOT NULL,payload TEXT NOT NULL,chain TEXT NOT NULL,PRIMARY KEY(device,session,seq))')
            yield db
            if write:db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
    def exchange(self,device,body):
        uid(device)
        if type(body) is not dict or set(body)!={'format','sessionId','start','previous','turns'} or body['format']!=FORMAT or len(encoded(body).encode('utf8'))>524288:raise ValueError('invalid_raw_exchange')
        sid=body['sessionId'];start=body['start'];previous=body['previous'];turns=body['turns']
        if type(sid) is not str or not 1<=len(sid)<=100 or any(ord(c)<32 for c in sid) or type(start) is not int or not 0<=start<=100000 or type(turns) is not list or len(turns)>64 or type(previous) is not str or len(previous)!=64:raise ValueError('invalid_raw_exchange')
        for i,t in enumerate(turns):valid_turn(t,start+i)
        with self.connection(True) as db:
            old=db.execute('SELECT count,chain FROM sessions WHERE device=? AND session=?',(device,sid)).fetchone()
            count,current=(old['count'],old['chain']) if old else (0,ZERO)
            if not turns:return {'format':FORMAT,'sessionId':sid,'next':count,'chain':current,'accepted':0}
            if start+len(turns)>100000:raise ValueError('phone_archive_session_limit')
            if start>count:raise ValueError('raw_cursor_changed')
            expected=ZERO if start==0 else db.execute('SELECT chain FROM turns WHERE device=? AND session=? AND seq=?',(device,sid,start-1)).fetchone()[0]
            if previous!=expected:raise ValueError('raw_source_changed')
            digest=previous;accepted=0
            for t in turns:
                digest=chain(digest,t);seq=t['index']
                if seq<count:
                    same=db.execute('SELECT payload,chain FROM turns WHERE device=? AND session=? AND seq=?',(device,sid,seq)).fetchone()
                    if not same or same['payload']!=encoded(t) or same['chain']!=digest:raise ValueError('raw_source_changed')
                else:
                    db.execute('INSERT INTO turns VALUES (?,?,?,?,?)',(device,sid,seq,encoded(t),digest));accepted+=1
            if start+len(turns)>count:count=start+len(turns);current=digest
            db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)',(device,sid,count,current))
            return {'format':FORMAT,'sessionId':sid,'next':count,'chain':current,'accepted':accepted}
    def entries(self):
        with self.connection() as db:
            if db is None:return []
            return [{'device':r['device'],'session':r['session'],**json.loads(r['payload'])} for r in db.execute('SELECT * FROM turns ORDER BY device,session,seq')]
    def source(self,device,session,start,end):
        uid(device)
        if type(start) is not int or type(end) is not int or start<0 or start%2 or end%2 or not start<end<=start+16:raise ValueError('invalid_phone_source_range')
        with self.connection() as db:
            rows=[] if db is None else [json.loads(r[0]) for r in db.execute('SELECT payload FROM turns WHERE device=? AND session=? AND seq>=? AND seq<? ORDER BY seq',(device,session,start//2,end//2))]
        return {'source':'paired-phone','sessionId':session,'start':start,'end':end,'complete':len(rows)==(end-start)//2,'turns':rows}
