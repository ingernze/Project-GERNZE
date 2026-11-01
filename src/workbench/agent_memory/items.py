"""Filter replay/history by sealed actual-input dependencies; retain raw archive rows."""
import json,uuid
from .atomic import AtomicJournal,digest,roots
from workbench.conversation_store import ConversationStore,ChatStateError,encoded,query_terms,terms

class ItemStore(AtomicJournal):
    def _complete(self,db,request_id,*args):
        result=super()._complete(db,request_id,*args)
        user=db.execute("SELECT m.* FROM lc_messages m JOIN lc_turns t ON t.user_id=m.id WHERE t.id=?",(request_id,)).fetchone()
        self._set(db,'ag_input:'+request_id,digest(dict(user)))
        return result
    def descriptors(self,db,request_id):
        seal=db.execute('SELECT * FROM ag_seals WHERE request_id=?',(request_id,)).fetchone()
        if not seal:raise ChatStateError('unknown_dependencies','No sealed exposure metadata')
        value=json.loads(seal['manifest']);roots(value)
        actual=[{'scope':r['scope'],'key':r['source_key'],'revision':r['revision'],'hash':r['source_hash']} for r in db.execute('SELECT * FROM ag_roots WHERE request_id=? ORDER BY scope,source_key',(request_id,))]
        if encoded(actual)!=encoded(value):raise ChatStateError('changed_dependencies','Dependency rows changed')
        return value
    def eligible(self,db,request_id):
        try:
            turn=db.execute('SELECT * FROM lc_turns WHERE id=?',(request_id,)).fetchone()
            if not turn or turn['status']!='complete':return False
            msgs=list(db.execute('SELECT * FROM lc_messages WHERE turn_id=?',(request_id,)))
            if len(msgs)!=2 or not all(m['allowed'] for m in msgs):return False
            user=next(m for m in msgs if m['role']=='user');assistant=next(m for m in msgs if m['role']=='assistant')
            if digest(dict(user))!=self._get(db,'ag_input:'+request_id):return False
            expected=digest({'reply':{'text':assistant['content'],'emotion':turn['emotion'],'action':turn['action']},'refs':json.loads(turn['ref_ids'])})
            seal=db.execute('SELECT reply_hash FROM ag_seals WHERE request_id=?',(request_id,)).fetchone()
            if not seal or seal[0]!=expected:return False
            current=json.loads(self._get(db,'ag_current') or '{}')
            return all(current.get(r['scope']+':'+r['key'])==r for r in self.descriptors(db,request_id))
        except (ValueError,KeyError,StopIteration,ChatStateError):return False
    def _pairs_from_rows(self,db,rows):return super()._pairs_from_rows(db,[r for r in rows if self.eligible(db,r['id'])])
    def recent(self,session_id,limit=6):
        with self.connection() as db:
            self._session(db,session_id)
            rows=db.execute("SELECT * FROM lc_turns WHERE session_id=? AND status='complete' ORDER BY seq DESC LIMIT 2048",(session_id,))
            selected=[]
            for r in rows:
                if len(selected)>=limit:break
                if self.eligible(db,r['id']):selected.append(r)
            return self._pairs_from_rows(db,reversed(selected))
    def retrieve(self,session_id,query,limit=3):
        wanted=query_terms(query)
        if not wanted:return []
        with self.connection() as db:
            self._session(db,session_id)
            rows=db.execute("SELECT t.*,COUNT(*) AS matches FROM lc_terms x JOIN lc_messages m ON m.id=x.message_id JOIN lc_turns t ON t.id=m.turn_id WHERE m.session_id=? AND m.allowed=1 AND t.status='complete' AND t.origin='user' AND x.term IN ("+','.join('?' for _ in wanted)+") GROUP BY t.id ORDER BY matches DESC,t.seq DESC LIMIT 512",(session_id,*wanted))
            pairs=self._pairs_from_rows(db,rows)[:limit]
            for pair in pairs:pair['matched_terms']=sorted(set(terms(pair['messages'][0]['content']))&set(wanted))
            return pairs
    def _completed(self,db,turn):
        if not self.eligible(db,turn['id']):raise ChatStateError('source_retired','Source or stored exposure no longer valid')
        return ConversationStore._completed(self,db,turn)
    def summary_view(self,*a,**kw):
        with self.connection() as db:
            if db.execute('SELECT 1 FROM lc_summaries LIMIT 1').fetchone():raise ChatStateError('candidate_unwired','Summary dependencies not implemented')
        return {'segments':[],'new_turns':[],'old_unsummarized_turns':0,'last_attempt_status':'disabled'}
    def commit_summary(self,*a,**kw):raise ChatStateError('candidate_unwired','Summary dependencies not implemented')

class SourceGate:
    def __init__(self,store,reader):self.store=store;self.reader=reader;self.entries=[]
    def sync(self):
        snapshot=self.reader.snapshot() if self.reader is not None else None
        with self.store.connection() as db:return self.apply(db,snapshot)
    def apply(self,db,snapshot):
        current={};entries=[]
        self.store._owner(db)
        seen=json.loads(self.store._get(db,'ag_observed') or '{}')
        if snapshot is not None:
            scope=str(uuid.uuid5(uuid.NAMESPACE_URL,snapshot['scope']))
            for key,state in snapshot['states'].items():
                if state=='withdrawn':seen.setdefault(scope+':'+key,{})['withdrawn']=True
            for entry in snapshot['entries']:
                key=scope+':'+entry['key'];known=seen.setdefault(key,{});rev=entry['revision']
                descriptor={'scope':scope,'key':entry['key'],'revision':rev,'hash':digest({k:entry[k] for k in ('key','revision','body','sourceRefs','sourceHash')})}
                retired=known.setdefault('retired',[])
                if rev==known.get('revision') and descriptor['hash']!=known.get('hash'):
                    if rev not in retired:retired.append(rev)
                    continue
                if known.get('withdrawn') or rev in retired or (rev==known.get('revision') and descriptor['hash']!=known.get('hash')):continue
                if known.get('revision') and rev!=known['revision']:retired.append(known['revision'])
                known.update(revision=rev,hash=descriptor['hash']);current[key]=descriptor;entries.append((entry,descriptor))
        self.store._set(db,'ag_observed',encoded(seen));self.store._set(db,'ag_current',encoded(current))
        self.entries=entries
        return current
    def check(self,dependencies):
        current=self.sync()
        if any(current.get(r['scope']+':'+r['key'])!=r for r in dependencies):raise ChatStateError('source_changed','Source changed around request')
