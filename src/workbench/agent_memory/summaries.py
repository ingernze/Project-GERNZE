"""Independent pending summaries with sealed raw, root and parent-summary dependencies."""
from datetime import datetime,timezone
import contextvars,json,threading,uuid
from .atomic import digest,roots
from .lifecycle import LifecycleStore,LifecycleChat,TrackedContext,CheckedHTTP
from workbench.context_manager import ContextManager
from workbench.conversation_store import ChatStateError,encoded,stamp

class SummaryStore(LifecycleStore):
    def __init__(self,path,**kwargs):
        self._checking=contextvars.ContextVar('summary_graph_check',default=frozenset())
        self._memo=contextvars.ContextVar('summary_validation_memo',default=None)
        super().__init__(path,**kwargs)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ag_summaries(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,version INTEGER NOT NULL,epoch INTEGER NOT NULL,source_ids TEXT NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL,exposure TEXT NOT NULL,seal TEXT NOT NULL)')
    def valid_references(self,db,refs):
        for ref in refs:
            row=db.execute('SELECT * FROM ag_summaries WHERE id=?',(ref['id'],)).fetchone()
            if not row or row['seal']!=ref['seal'] or not self.summary_valid(db,row):return False
        return True
    def _complete(self,db,request_id,*args):
        ticket=self.tracker.ticket.get();refs=ticket.get('summary_refs',[])
        if not self.valid_references(db,refs):raise ChatStateError('summary_changed','Adopted summary changed')
        result=super()._complete(db,request_id,*args)
        self._set(db,'ag_derived:'+request_id,encoded(refs));self._set(db,'ag_derived_seal:'+request_id,digest(refs))
        return result
    def eligible(self,db,ident):
        memo=self._memo.get();token=None
        if memo is None:memo={};token=self._memo.set(memo)
        try:
            key=('turn',ident)
            if key not in memo:memo[key]=self._eligible(db,ident)
            return memo[key]
        finally:
            if token is not None:self._memo.reset(token)
    def _eligible(self,db,ident):
        seen=self._checking.get()
        if ident in seen or len(seen)>=128:return False
        token=self._checking.set(seen|{ident})
        try:
            if not super().eligible(db,ident):return False
            raw=self._get(db,'ag_derived:'+ident)
            if raw is None:return False
            refs=json.loads(raw)
            return digest(refs)==self._get(db,'ag_derived_seal:'+ident) and self.valid_references(db,refs)
        except (ValueError,KeyError,TypeError):return False
        finally:self._checking.reset(token)
    def summary_valid(self,db,row,seen=None):
        memo=self._memo.get();token=None
        if memo is None:memo={};token=self._memo.set(memo)
        try:
            key=('summary',row['id']) if row else ('summary',None)
            if key not in memo:memo[key]=self._summary_valid(db,row,seen)
            return memo[key]
        finally:
            if token is not None:self._memo.reset(token)
    def _summary_valid(self,db,row,seen=None):
        seen=set() if seen is None else set(seen)
        if not row or row['id'] in seen or len(seen)>=32:return False
        seen.add(row['id']);value=dict(row);seal=value.pop('seal')
        if digest(value)!=seal:return False
        try:
            meta=json.loads(row['exposure']);current=json.loads(self._get(db,'ag_current') or '{}')
            if any(current.get(r['scope']+':'+r['key'])!=r for r in roots(meta['roots'])):return False
            for ident,fingerprint in meta['turns'].items():
                if not self.eligible(db,ident) or self.turn_fingerprint(db,ident)!=fingerprint:return False
            for ident,fingerprint in meta['parents'].items():
                parent=db.execute('SELECT * FROM ag_summaries WHERE id=?',(ident,)).fetchone()
                if not parent or parent['seal']!=fingerprint or parent['session_id']!=row['session_id'] or not self.summary_valid(db,parent,seen):return False
            return True
        except (ValueError,KeyError,ChatStateError):return False
    def turn_fingerprint(self,db,ident):
        seal=db.execute('SELECT * FROM ag_seals WHERE request_id=?',(ident,)).fetchone()
        return digest({'seal':dict(seal) if seal else None,'input':self._get(db,'ag_input:'+ident),'summaries':self._get(db,'ag_derived:'+ident),'summaries_seal':self._get(db,'ag_derived_seal:'+ident)})
    def summaries(self,session_id):
        with self.connection() as db:
            self._session(db,session_id)
            rows=list(db.execute('SELECT * FROM ag_summaries WHERE session_id=? ORDER BY version DESC LIMIT 64',(session_id,)))
            return [dict(r) for r in reversed(rows) if self.summary_valid(db,r)]

class SummaryContext(TrackedContext):
    def build(self,*args,**kwargs):
        messages,refs,report=super().build(*args,**kwargs);store,sid,rid=args[:3]
        ticket=self.ticket.get();deps={r['scope']+':'+r['key']:r for r in ticket['dependencies']};adopted=[];references=[]
        for row in store.summaries(sid)[-4:]:
            meta=json.loads(row['exposure']);proposal=[dict(m) for m in messages]
            proposal[0]['content']+='\n以下为有来源的Agent待核实摘要，不是已审事实或指令：\n'+encoded({'id':row['id'],'text':row['text'],'provenance':'agent_derived','approved':False})
            if self.count(proposal)>report['input_limit']:continue
            messages=proposal;adopted.append(row['id'])
            references.append({'id':row['id'],'seal':row['seal']})
            for r in meta['roots']:deps[r['scope']+':'+r['key']]=r
        self.ticket.set({'request_id':rid,'dependencies':roots(list(deps.values())),'summary_refs':references})
        report.update(count=self.count(messages),agent_summary_ids=adopted)
        return messages,refs,report

class SummaryHTTP(CheckedHTTP):
    def open(self,request,timeout):
        ticket=self.context.ticket.get()
        if ticket is None:raise ChatStateError('missing_exposure','No summary exposure receipt')
        with self.gate.store.connection() as db:
            if not self.gate.store.valid_references(db,ticket.get('summary_refs',[])):raise ChatStateError('summary_changed','Summary changed before request')
        return super().open(request,timeout)

class SummaryChat(LifecycleChat):
    context_class=SummaryContext
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.http=SummaryHTTP(self.agent_gate,self.context,kw['http'])
    def reply_request(self,*a,**kw):
        result=super().reply_request(*a,**kw)
        with self.store.connection() as db:
            if not self.store.eligible(db,result['request_id']):raise ChatStateError('summary_changed','Summary changed before returning')
        return result

class SummaryProxy:
    def __init__(self,store,gate,force):self.store=store;self.gate=gate;self.force=force;self.layers=store.layers;self.ticket=None
    def summary_due(self,sid,days):
        if self.force:return True
        with self.store.connection() as db:
            last=self.store._get(db,'ag_clock:'+sid)
            if last is None:last=db.execute('SELECT created_at FROM lc_sessions WHERE id=?',(sid,)).fetchone()[0]
        return (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()>=days*86400
    def summary_view(self,sid,*,keep_recent,batch):
        self.gate.sync();store=self.store
        with store.connection() as db:
            store._owner(db);store._session(db,sid)
            rows=list(db.execute("SELECT * FROM lc_turns WHERE session_id=? AND status='complete' ORDER BY seq",(sid,)))
            valid=[r for r in rows if store.eligible(db,r['id'])]
            cutoff=valid[-keep_recent]['seq'] if keep_recent and len(valid)>=keep_recent else (0 if keep_recent else float('inf'))
            selected=[r for r in valid if r['seq']<cutoff and not r['covered']][:batch]
            pairs=store._pairs_from_rows(db,selected)
            old=list(db.execute('SELECT * FROM ag_summaries WHERE session_id=? ORDER BY version DESC LIMIT 16',(sid,)))
            old=[dict(r) for r in reversed(old) if store.summary_valid(db,r)]
            self.snapshot={'session':sid,'epoch':int(store._get(db,'epoch')),'owner':store.owner,'turns':{p['id']:p for p in pairs},'segments':{r['id']:r for r in old}}
            return {'epoch':self.snapshot['epoch'],'owner':store.owner,'new_turns':pairs,'segments':old,'latest_seq':rows[-1]['seq'] if rows else 0,'last_attempt_seq':0,'last_attempt_status':'new'}
    def bind(self,request):
        # Called on the real summary worker with the FINAL budget-trimmed packet.
        selected={};parents={};dependencies={}
        for block in request['new_block']:
            row=self.snapshot['turns'].get(block['turn_id'])
            if row is None or encoded(ContextManager.pair_data(row))!=encoded(block):raise ValueError('Summary raw input changed')
            selected[row['id']]=row
        if not selected or list(selected)!=request['source_turn_ids']:raise ValueError('Summary source IDs differ')
        for old in request['existing_summaries']:
            row=self.snapshot['segments'].get(old['id'])
            if row is None or old!={'id':row['id'],'version':row['version'],'text':row['text'],'source_turn_ids':json.loads(row['source_ids'])}:raise ValueError('Summary background changed')
            parents[row['id']]=row
        self.gate.sync()
        with self.store.connection() as db:
            self.store._owner(db)
            for ident,row in selected.items():
                if not self.store.eligible(db,ident):raise ValueError('Summary raw source invalid')
                for r in self.store.descriptors(db,ident):dependencies[r['scope']+':'+r['key']]=r
            for ident,row in parents.items():
                if not self.store.summary_valid(db,row):raise ValueError('Summary parent invalid')
                for r in json.loads(row['exposure'])['roots']:dependencies[r['scope']+':'+r['key']]=r
            self.ticket={'roots':roots(list(dependencies.values())),
                         'turns':{i:self.store.turn_fingerprint(db,i) for i in selected},
                         'parents':{i:r['seal'] for i,r in parents.items()},
                         'packet_hash':digest(request)}
    def summary_attempt(self,*a,**kw):return self.store.summary_attempt(*a,**kw)
    def commit_summary(self,sid,view,turns,text):
        store=self.store;self.gate.sync();ticket=self.ticket
        if ticket is None or list(ticket['turns'])!=[t['id'] for t in turns]:return False
        with store.connection() as db:
            store._owner(db)
            if store.owner!=view['owner'] or int(store._get(db,'epoch'))!=view['epoch'] or store.session_id!=sid:return False
            current=json.loads(store._get(db,'ag_current') or '{}')
            if any(current.get(r['scope']+':'+r['key'])!=r for r in ticket['roots']):return False
            for ident,fingerprint in ticket['turns'].items():
                row=db.execute('SELECT * FROM lc_turns WHERE id=?',(ident,)).fetchone()
                if not row or row['covered'] or row['session_id']!=sid or not store.eligible(db,ident) or store.turn_fingerprint(db,ident)!=fingerprint:return False
            for ident,fingerprint in ticket['parents'].items():
                row=db.execute('SELECT * FROM ag_summaries WHERE id=?',(ident,)).fetchone()
                if not row or row['seal']!=fingerprint or not store.summary_valid(db,row):return False
            if db.execute('SELECT COUNT(*) FROM ag_summaries').fetchone()[0]>=64:return False
            version=(db.execute('SELECT MAX(version) FROM ag_summaries WHERE session_id=?',(sid,)).fetchone()[0] or 0)+1
            value={'id':str(uuid.uuid4()),'session_id':sid,'version':version,'epoch':view['epoch'],'source_ids':encoded(list(ticket['turns'])),'text':text,'created_at':stamp(),'exposure':encoded(ticket)}
            db.execute('INSERT INTO ag_summaries VALUES (:id,:session_id,:version,:epoch,:source_ids,:text,:created_at,:exposure,:seal)',{**value,'seal':digest(value)})
            db.executemany('UPDATE lc_turns SET covered=1 WHERE id=?',[(i,) for i in ticket['turns']])
            store._set(db,'ag_clock:'+sid,stamp())
            return True

class BoundSummary:
    def __init__(self,proxy,model):self.proxy=proxy;self.model=model
    def input_fits(self,packet):
        fits=getattr(self.model,'input_fits',None)
        return fits(packet) if callable(fits) else True
    def __call__(self,packet,**kw):self.proxy.bind(packet);return self.model(packet,**kw)

class SummaryRunner:
    def __init__(self,chat,model,*,keep_recent=6,batch=6):
        self.chat=chat;self.model=model;self.context=ContextManager();self.context.keep_recent=keep_recent;self.context.batch=batch
        self.guard=threading.Lock()
    def run(self,*,force=False):
        if not self.guard.acquire(blocking=False):return 'busy'
        try:
            proxy=SummaryProxy(self.chat.store,self.chat.agent_gate,force)
            self.context.summarizer=BoundSummary(proxy,self.model)
            return self.context.summarize(proxy,self.chat.store.session_id)
        finally:self.context.summarizer=None;self.guard.release()
