"""One-generation general phone deltas using the existing bounded summary worker.

Phone raw is read through a fixed, write-denied attachment. Only the journal is
written; no model callback runs while either database transaction is held.
"""
from datetime import datetime,timezone
import json,uuid,sqlite3
from pathlib import Path
from .conversation_store import encoded,stamp,uid
from .research_catalog import ResearchAccess,ResearchError,digest
from .research_summaries import ResearchSummaries,reference,normalized_refs

META='id,revision,device,phone_session,version,root,manifest,raw_refs,parents,phone_refs,body_hash,body_bytes,created_at'

def initialize(db):
    old=db.execute("SELECT value FROM rc_meta WHERE key='phone_summary_schema'").fetchone()
    if old and old[0]!='1':raise ResearchError('unsupported_phone_summary_schema')
    for sql in [
        'CREATE TABLE IF NOT EXISTS rc_phone_summary_meta(id TEXT PRIMARY KEY,revision TEXT NOT NULL,device TEXT NOT NULL,phone_session TEXT NOT NULL,version INTEGER NOT NULL,root TEXT NOT NULL,manifest TEXT NOT NULL,raw_refs TEXT NOT NULL,parents TEXT NOT NULL,phone_refs TEXT NOT NULL,body_hash TEXT NOT NULL,body_bytes INTEGER NOT NULL,created_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS rc_phone_summary_bodies(id TEXT PRIMARY KEY,body TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS rc_phone_summary_coverage(device TEXT NOT NULL,session TEXT NOT NULL,seq INTEGER NOT NULL,summary_id TEXT NOT NULL,PRIMARY KEY(device,session,seq))',
        'CREATE TABLE IF NOT EXISTS rc_phone_summary_attempt(key TEXT PRIMARY KEY,latest INTEGER NOT NULL,status TEXT NOT NULL,clock TEXT,claim TEXT NOT NULL)',
    ]:db.execute(sql)
    db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('phone_summary_schema','1')")

def available(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rc_phone_summary_meta'").fetchone():return False
    row=db.execute("SELECT value FROM rc_meta WHERE key='phone_summary_schema'").fetchone()
    if not row or row[0]!='1':raise ResearchError('unsupported_phone_summary_schema')
    return True

def phone_refs(values):
    if type(values) is not list or not 1<=len(values)<=8:raise ResearchError('invalid_phone_summary_refs')
    seen=set()
    for r in values:
        if type(r) is not dict or set(r)!={'device','session','index','content_hash'}:raise ResearchError('invalid_phone_summary_refs')
        uid(r['device'])
        if type(r['session']) is not str or not 1<=len(r['session'])<=100 or any(ord(c)<32 for c in r['session']) or type(r['index']) is not int or not 0<=r['index']<100000:raise ResearchError('invalid_phone_summary_refs')
        from .phone_research_archive import sha
        sha(r['content_hash']);key=(r['device'],r['session'],r['index'])
        if key in seen:raise ResearchError('duplicate_phone_summary_ref')
        seen.add(key)
    return values

def attach(db,journal_path):
    path=Path(journal_path).with_name('paired-phone-raw.sqlite3').resolve()
    if not path.is_file():raise ResearchError('phone_archive_unavailable')
    attached={r[1]:r[2] for r in db.execute('PRAGMA database_list')}
    if 'phone_raw' in attached:
        if Path(attached['phone_raw']).resolve()!=path:raise ResearchError('phone_archive_attachment_changed')
    else:
        # Existing host writers use native filenames, readers use URI mode.
        # A checked absolute path works with both. The authorizer denies all
        # archive writes; final commit keeps only a short consistency lock.
        db.execute('ATTACH DATABASE ? AS phone_raw',(str(path),))
        def read_only_archive(action,arg1,arg2,database,trigger):
            if database=='phone_raw' and action not in (sqlite3.SQLITE_READ,sqlite3.SQLITE_SELECT,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE):return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(read_only_archive)
    row=db.execute("SELECT 1 FROM phone_raw.sqlite_master WHERE type='table' AND name='pr_receipts'").fetchone()
    if not row:raise ResearchError('phone_summary_metadata_unavailable')
    if [r[0] for r in db.execute('SELECT version FROM phone_raw.pr_schema')]!=[2]:raise ResearchError('phone_summary_metadata_unavailable')

def root_meta(journal,db,ref,access):
    # Deliberately only desktop-root summaries in this phase. Summarizing a
    # phone-derived summary again is deferred instead of creating a hidden loop.
    return ResearchSummaries(journal).verify(db,ref,access)

def verify(journal,db,ref,access=ResearchAccess()):
    ref=normalized_refs([ref])[0]
    if not available(db):raise ResearchError('phone_summary_unavailable')
    row=db.execute('SELECT '+META+' FROM rc_phone_summary_meta WHERE id=?',(ref['id'],)).fetchone()
    if not row or reference(row)!=ref:raise ResearchError('phone_summary_revision_changed')
    ResearchSummaries.review_allowed(db,ref)
    meta=dict(row);root=root_meta(journal,db,json.loads(meta['root']),access)
    if not 1<=meta['body_bytes']<=6000:raise ResearchError('invalid_phone_summary_size')
    if (json.loads(meta['manifest'])!=root['manifest'] or json.loads(meta['raw_refs'])!=root['raw_refs']
        or json.loads(meta['parents'])!=normalized_refs([reference(root),*json.loads(root['parents'])])):raise ResearchError('phone_summary_ancestry_changed')
    attach(db,journal.catalog.path)
    refs=phone_refs(json.loads(meta['phone_refs']))
    for r in refs:
        if r['device']!=meta['device'] or r['session']!=meta['phone_session']:raise ResearchError('phone_summary_scope_changed')
        current=db.execute('SELECT m.content_hash,r.receipt FROM phone_raw.pr_meta m JOIN phone_raw.pr_receipts r USING(device,session,seq) WHERE device=? AND session=? AND seq=?',(r['device'],r['session'],r['index'])).fetchone()
        if not current or current['content_hash']!=r['content_hash']:raise ResearchError('phone_summary_raw_changed')
        source=json.loads(current['receipt'])['source']
        if source.get('phone_refs') or reference(source)!=reference(root) or source['sources']!=root['manifest'] or source['raw_refs']!=root['raw_refs']:raise ResearchError('phone_summary_source_changed')
    meta.update(manifest=root['manifest'],raw_refs=root['raw_refs'],phone_refs=refs)
    return meta

def verify_any(journal,db,ref,access=ResearchAccess()):
    if db.execute('SELECT 1 FROM rc_summary_meta WHERE id=?',(ref['id'],)).fetchone():return root_meta(journal,db,ref,access)
    return verify(journal,db,ref,access)

def proxy(journal,keep,batch,minimum,input_limit):
    current=journal.scope.get()
    if not current or current.input_only or current.access.scene!='casual':return None
    if not journal.path.with_name('paired-phone-raw.sqlite3').is_file():return None
    return PhoneSummaryWriter(journal,keep,batch,minimum,input_limit)

class PhoneSummaryWriter:
    def __init__(self,journal,keep,batch,minimum,input_limit):
        self.journal=journal;self.layers=journal.layers;self.keep=keep;self.batch=batch;self.minimum=minimum;self.input_limit=input_limit
        self.group=None;self.rows=[];self.claim=str(uuid.uuid4());self.snapshot={};self.root=None

    def candidates(self,db,days=None):
        attach(db,self.journal.path)
        groups={};now=datetime.now(timezone.utc)
        rows=db.execute("SELECT m.*,r.receipt,r.message_bytes,r.user_chars,r.received_at,s.next FROM phone_raw.pr_meta m JOIN phone_raw.pr_receipts r USING(device,session,seq) JOIN phone_raw.pr_sessions s USING(device,session) WHERE m.kind='research' AND m.seq<s.next-? AND NOT EXISTS (SELECT 1 FROM rc_phone_summary_coverage c WHERE c.device=m.device AND c.session=m.session AND c.seq=m.seq) ORDER BY m.device,m.session,m.seq LIMIT 512",(self.keep,))
        for row in rows:
            data=dict(row)
            try:
                source=json.loads(data['receipt'])['source']
                if source.get('phone_refs'):continue
                root=root_meta(self.journal,db,reference(source),ResearchAccess())
                if source['sources']!=root['manifest'] or source['raw_refs']!=root['raw_refs'] or source['parents']!=normalized_refs(json.loads(root['parents'])):continue
                key=encoded([data['device'],data['session'],reference(root)])
                attempt=db.execute('SELECT * FROM rc_phone_summary_attempt WHERE key=?',(key,)).fetchone()
                if days is not None:
                    first=attempt['clock'] if attempt and attempt['clock'] else data['received_at']
                    if (now-datetime.fromisoformat(first.replace('Z','+00:00'))).total_seconds()<days*86400:continue
                data.update(root=root,key=key,attempt=dict(attempt) if attempt else None);groups.setdefault(key,[]).append(data)
            except (ValueError,TypeError,KeyError):continue
        if self.group is None:self.group=next((k for k,v in groups.items() if len(v)>=self.minimum),None)
        return groups.get(self.group,[])

    def summary_due(self,session,days):
        try:
            with self.journal.read_connection() as db:return bool(self.candidates(db,days))
        except (ValueError,sqlite3.Error,OSError):return False

    def summary_view(self,session,**unused):
        try:return self._summary_view(session)
        except (ValueError,sqlite3.Error,OSError):return {'epoch':0,'owner':self.journal.owner,'latest_seq':0,'new_turns':[],'segments':[],'old_unsummarized_turns':0,'last_attempt_seq':0,'last_attempt_status':'unavailable'}

    def _summary_view(self,session):
        with self.journal.read_connection() as db:
            rows=self.candidates(db);selected=rows[:self.batch];self.rows=selected
            attempt=selected[0]['attempt'] if selected else None
            view={'epoch':int(self.journal._get(db,'epoch')),'owner':self.journal.owner,'latest_seq':selected[0]['next'] if selected else 0,'new_turns':[],'segments':[],'old_unsummarized_turns':len(rows),'last_attempt_seq':attempt['latest'] if attempt and attempt['status']!='committed' else 0,'last_attempt_status':attempt['status'] if attempt else 'never'}
            # Conservative metadata gate, then the existing exact request/adapter
            # preflight still runs before the provider. Never slice a raw pair.
            if any(r['user_chars']>1000 for r in selected) or sum(r['message_bytes'] for r in selected)+512+320*len(selected)>self.input_limit:
                view['metadata_budget_blocked']=True;return view
            self.snapshot={};self.root=selected[0]['root'] if selected else None
            for row in selected:
                value=db.execute('SELECT payload FROM phone_raw.pr_bodies WHERE device=? AND session=? AND seq=?',(row['device'],row['session'],row['seq'])).fetchone()
                if not value or digest(value[0])!=row['content_hash']:raise ResearchError('phone_summary_raw_changed')
                raw=json.loads(value[0])
                if raw['research']!=json.loads(row['receipt']):raise ResearchError('phone_summary_receipt_changed')
                rid=str(uuid.uuid5(uuid.UUID(row['device']),encoded([row['session'],row['seq']])))
                messages=[{'id':str(uuid.uuid5(uuid.UUID(rid),role)),'role':role,'content':raw[key]} for role,key in [('user','user'),('assistant','assistant')]]
                turn={'id':rid,'origin':'external_ai','messages':messages};view['new_turns'].append(turn);self.snapshot[rid]=(row,digest(encoded(messages)))
            return view

    def summary_attempt(self,session,seq,status,*,epoch=None):
        if not self.group:return False
        with self.journal.connection() as db:
            self.journal._owner(db)
            if int(self.journal._get(db,'epoch'))!=epoch:return False
            old=db.execute('SELECT * FROM rc_phone_summary_attempt WHERE key=?',(self.group,)).fetchone()
            if status=='attempted':
                if old and old['latest']==seq and old['status']!='committed':return False
                db.execute('INSERT INTO rc_phone_summary_attempt VALUES (?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET latest=excluded.latest,status=excluded.status,claim=excluded.claim',(self.group,seq,status,None,self.claim))
            else:
                if not old or old['claim']!=self.claim:return False
                db.execute('UPDATE rc_phone_summary_attempt SET status=? WHERE key=?',(status,self.group))
        return True

    def commit_summary(self,session,view,turns,text):
        current=self.journal.scope.get()
        if not current or current.session_id!=session or current.input_only or current.access.scene!='casual' or not turns or len(turns)>self.batch or len({t['id'] for t in turns})!=len(turns):return False
        if type(text) is not str or not text.strip() or len(text)>1500 or '\0' in text:return False
        with current.publication_guard(),self.journal.connection() as db:
            self.journal._owner(db);current.validate_host()
            if view['owner']!=self.journal.owner or int(self.journal._get(db,'epoch'))!=view['epoch']:return False
            claim=db.execute('SELECT * FROM rc_phone_summary_attempt WHERE key=?',(self.group,)).fetchone()
            if not claim or claim['claim']!=self.claim or claim['status']!='attempted':return False
            root=root_meta(self.journal,db,reference(self.root),ResearchAccess());attach(db,self.journal.path);refs=[]
            for turn in turns:
                if turn['id'] not in self.snapshot:return False
                row,expected=self.snapshot[turn['id']]
                if digest(encoded(turn['messages']))!=expected:return False
                actual=db.execute('SELECT m.content_hash,b.payload,r.receipt FROM phone_raw.pr_meta m JOIN phone_raw.pr_bodies b USING(device,session,seq) JOIN phone_raw.pr_receipts r USING(device,session,seq) WHERE device=? AND session=? AND seq=?',(row['device'],row['session'],row['seq'])).fetchone()
                if not actual or actual['content_hash']!=row['content_hash'] or digest(actual['payload'])!=row['content_hash'] or actual['receipt']!=row['receipt']:return False
                if db.execute('SELECT 1 FROM rc_phone_summary_coverage WHERE device=? AND session=? AND seq=?',(row['device'],row['session'],row['seq'])).fetchone():return False
                refs.append({'device':row['device'],'session':row['session'],'index':row['seq'],'content_hash':row['content_hash']})
            ident,revision=str(uuid.uuid4()),str(uuid.uuid4());version=(db.execute('SELECT MAX(version) FROM rc_phone_summary_meta').fetchone()[0] or 0)+1
            first=self.snapshot[turns[0]['id']][0]
            db.execute('INSERT INTO rc_phone_summary_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,revision,first['device'],first['session'],version,encoded(reference(root)),encoded(root['manifest']),encoded(root['raw_refs']),encoded(normalized_refs([reference(root),*json.loads(root['parents'])])),encoded(phone_refs(refs)),digest(text),len(text.encode('utf-8')),stamp()))
            db.execute('INSERT INTO rc_phone_summary_bodies VALUES (?,?)',(ident,text))
            db.executemany('INSERT INTO rc_phone_summary_coverage VALUES (?,?,?,?)',[(r['device'],r['session'],r['index'],ident) for r in refs])
            db.execute('UPDATE rc_phone_summary_attempt SET clock=? WHERE key=?',(stamp(),self.group))
        return True
