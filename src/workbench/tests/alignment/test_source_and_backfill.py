"""Regression coverage for revoked sources and overflow from a real legacy schema."""
from pathlib import Path
import sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from workbench.conversation_store import ConversationStore,stamp,encoded
from workbench.memory_layers import MemoryLayers
from workbench.memory_archive import MemoryArchive

def uid():return str(uuid.uuid4())

def legacy_journal(path,count):
    store=ConversationStore(path);when=stamp()
    with store.connection() as db:
        sessions=[uid() for _ in range((count+15)//16)]
        db.executemany('INSERT INTO lc_sessions VALUES (?,?,0)',[(sid,when) for sid in sessions])
        for number in range(count):
            sid=sessions[number//16];turns=[]
            for _ in range(3):
                tid,u,a=uid(),uid(),uid();turns.append(tid)
                db.execute("INSERT INTO lc_turns(id,session_id,status,origin,topic,created_at,user_id,assistant_id,attempt,owner,epoch,emotion,action,covered) VALUES (?,?,'complete','user','unspecified',?,?,?,1,?,0,'normal','none',1)",(tid,sid,when,u,a,store.owner))
                db.executemany('INSERT INTO lc_messages(id,turn_id,session_id,role,time,origin,content) VALUES (?,?,?,?,?,?,?)',[(u,tid,sid,'user',when,'user','synthetic legacy original'),(a,tid,sid,'assistant',when,'assistant','synthetic legacy answer')])
            db.execute('INSERT INTO lc_summaries VALUES (?,?,?,?,?,?,?)',(uid(),sid,number+1,0,encoded(turns),'synthetic old summary '+str(number),when))
    return store

class SourceAndBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='gernze-source-backfill-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def summary(self,count=4):
        store=ConversationStore(self.root/'source.sqlite3');layers=MemoryLayers(store)
        for i in range(count):
            rid=uid();store.begin_turn(store.session_id,'SYNTHETIC source '+str(i),rid)
            store.complete(rid,{'text':'SYNTHETIC answer','emotion':'normal','action':'none'},store.epoch(),[])
        view=store.summary_view(store.session_id,keep_recent=1,batch=3)
        self.assertTrue(store.commit_summary(store.session_id,view,view['new_turns'],'SYNTHETIC removable summary'))
        return store,layers,layers.snapshot()['pending'][0]
    def check_retired(self,store,layers,working):
        self.assertFalse(layers.snapshot()['pending'])
        archive=MemoryArchive(type('Chat',(),{'store':store,'layers':layers})())
        self.assertFalse(any(e['kind']=='summary' for e in archive._entries()))
        with self.assertRaises(ValueError):layers.decide([{'key':working['key'],'revision':working['revision'],'action':'approve'}])
        self.assertFalse(layers.context_notes())
        with store.read_connection() as db:self.assertEqual(db.execute('SELECT body FROM lm_working WHERE key=?',(working['key'],)).fetchone()[0],'')
    def test_removed_source_retires_pending_in_same_operation(self):
        store,layers,w=self.summary();store.remove_source(w['source_ids'][0]);self.check_retired(store,layers,w)
    def test_deleted_session_cannot_be_revived_by_old_approval(self):
        store,layers,w=self.summary();store.delete_session(w['session_id']);self.check_retired(store,layers,w)
    def test_approval_revalidates_source_even_if_changed_outside_hook(self):
        store,layers,w=self.summary()
        with store.connection() as db:db.execute("UPDATE lc_messages SET content='' WHERE id=?",(w['source_ids'][0],))
        with self.assertRaisesRegex(ValueError,'来源已撤销'):layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'}])
        self.assertFalse(layers.context_notes());self.assertFalse(layers.snapshot()['pending'])
    def test_global_barrier_does_not_retire_other_unchanged_sources(self):
        store,layers,a=self.summary(8);view=store.summary_view(store.session_id,keep_recent=1,batch=3)
        store.commit_summary(store.session_id,view,view['new_turns'],'SYNTHETIC unrelated summary')
        b=next(w for w in layers.snapshot()['pending'] if w['key']!=a['key'])
        store.remove_source(a['source_ids'][0]);self.assertEqual([w['key'] for w in layers.snapshot()['pending']],[b['key']])
        self.assertEqual(layers.decide([{'key':b['key'],'revision':b['revision'],'action':'approve'}])['applied'],1)
    def test_source_removal_does_not_implicitly_delete_approved_memory(self):
        store,layers,w=self.summary();decision=[{'key':w['key'],'revision':w['revision'],'action':'approve'}];layers.decide(decision)
        store.remove_source(w['source_ids'][0]);self.assertEqual(len(layers.context_notes()),1)
        self.assertEqual(layers.decide(decision),{'applied':0,'alreadyProcessed':1})
    def test_201_old_summaries_start_and_resume_without_losing_raw(self):
        store=legacy_journal(self.root/'legacy.sqlite3',201);layers=MemoryLayers(store);view=layers.snapshot()
        self.assertEqual((len(view['pending']),view['deferredCount']),(200,1))
        w=view['pending'][0];layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'}]);view=layers.snapshot()
        self.assertEqual((len(view['pending']),view['deferredCount'],len(view['working']),len(view['approved'])),(200,0,201,1))
        with store.read_connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM lc_messages').fetchone()[0],1206)
        reopened=MemoryLayers(ConversationStore(store.path));self.assertEqual(len(reopened.snapshot()['pending']),200)
    def test_backlog_survives_context_barrier_and_restart_then_drains(self):
        store=legacy_journal(self.root/'legacy.sqlite3',205);layers=MemoryLayers(store);view=layers.snapshot();self.assertEqual(view['deferredCount'],5)
        store.retire_context('notes_changed')
        with store.read_connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM lc_summaries').fetchone()[0],0)
        store=ConversationStore(store.path);layers=MemoryLayers(store);view=layers.snapshot();self.assertEqual(view['deferredCount'],5)
        layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'} for w in view['pending'][:5]])
        view=layers.snapshot();self.assertEqual((view['deferredCount'],len(view['working']),len(view['pending'])),(0,205,200))
    def test_backfill_failure_rolls_back_approval_and_entire_drain(self):
        store=legacy_journal(self.root/'legacy.sqlite3',203);layers=MemoryLayers(store);view=layers.snapshot();real=layers.ingest;calls=0
        def fail_second(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('synthetic backfill failure')
            return real(*args,**kwargs)
        layers.ingest=fail_second
        with self.assertRaises(OSError):layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'} for w in view['pending'][:3]])
        layers.ingest=real;view=layers.snapshot();self.assertEqual((len(view['approved']),len(view['pending']),view['deferredCount']),(0,200,3))

if __name__=='__main__':unittest.main(verbosity=2)
