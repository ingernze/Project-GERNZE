"""Independent synthetic regressions; no real keys, user stores or external calls."""
import argparse,sys,json,uuid,threading,types,tempfile
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--source',required=True);args,rest=p.parse_known_args()
root=Path(args.source).resolve();sys.path.insert(0,str(root/'src'));sys.path.insert(0,str(root/'src/workbench/tests'))
from desktop_auto_review_test import Tests as Fixture,Adapter
from workbench.desktop_memory_review import DesktopMemoryReview
from workbench import desktop_memory_review as module
from workbench.phone_archive import PhoneArchive,ZERO,FORMAT

class Tests(TestCase):
    setUp=Fixture.setUp
    def test_immediate_requests_claim_before_thread_start(self):
        self.adapter.edit=lambda d,e:d.update(action='defer',text='',evidence=[],reason='合成：暂缓')
        queued=[]
        class DelayedThread:
            def __init__(self,*,target,**kw):self.target=target
            def start(self):queued.append(self.target)
        with patch.object(module.threading,'Thread',DelayedThread):
            first=self.r.request();second=self.r.request()
        for target in queued:target()
        self.assertEqual(first['status'],'queued');self.assertEqual(second['status'],'busy')
        self.assertEqual(self.adapter.calls,1)
    def test_source_retired_between_read_and_basis_cannot_promote(self):
        original=self.r._sources
        def race(entry):
            result=original(entry)
            with self.s.connection() as db:db.execute('UPDATE lc_messages SET allowed=0')
            return result
        self.r._sources=race
        result=self.r.run()
        self.assertNotEqual(result['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        self.assertEqual(self.adapter.calls,0)
    def test_phone_reference_change_rejects_old_response(self):
        archive=PhoneArchive(self.s.path);devices=[str(uuid.uuid4()),str(uuid.uuid4())]
        for index,device in enumerate(devices):
            turns=[{'index':i,'user':'合成手机事实'+str(index),'assistant':'合成助手回应','userAt':'2026-10-01T08:00:00+08:00','assistantAt':'2026-10-01T08:00:01+08:00'} for i in range(3)]
            archive.exchange(device,{'format':FORMAT,'sessionId':'synthetic-phone','start':0,'previous':ZERO,'turns':turns})
        key='phone3:'+self.w['key']+':'+self.w['revision']
        def ref(device):return json.dumps({'device':device,'sessionId':'synthetic-phone','start':0,'end':6})
        with self.s.connection() as db:
            db.execute('INSERT INTO lm_layer_sync_meta VALUES (?,?)',(key,ref(devices[0])))
            db.execute('INSERT INTO lm_remote_sources VALUES (?,?,?)',(self.w['key'],self.w['revision'],'{}'))
        def replace():
            with self.s.connection() as db:db.execute('UPDATE lm_layer_sync_meta SET value=? WHERE key=?',(ref(devices[1]),key))
        self.adapter.callback=replace
        self.assertNotEqual(self.r.run()['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_approval_and_reason_record_rollback_together(self):
        record=self.r._record
        def broken(payload,**kw):
            if payload['status']=='completed':raise OSError('synthetic audit storage failure')
            return record(payload,**kw)
        self.r._record=broken
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        with self.s.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_receipts').fetchone()[0],0)
    def test_partial_quote_cannot_strip_plan_or_fiction_prefix(self):
        def crop(d,e):
            s=next(s for s in e['sources'] if s['role']=='user')
            text='尚未开始' # Exact substring still discards what is planned and when.
            d.update(action='correct',text=text,evidence=[{'messageId':s['id'],'quote':text}])
        self.adapter.edit=crop
        self.assertNotEqual(self.r.run()['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_source_time_and_turn_order_are_available(self):
        self.r.run();entries=json.loads(self.adapter.messages[1]['content'])['entries']
        for source in entries[0]['sources']:
            self.assertIn('time',source);self.assertIn('turnIndex',source);self.assertIn('origin',source)
        self.assertEqual(set(json.loads(self.adapter.messages[1]['content'])),{'entries'})
    def test_new_chat_continues_but_invalidates_old_review(self):
        def add():
            tid=str(uuid.uuid4());self.s.begin_turn(self.s.session_id,'纠正刚才的计划：合成松果计划已经取消。',tid)
            self.s.complete(tid,{'text':'合成助手应答','emotion':'normal','action':'none'},self.s.epoch(),[])
        self.adapter.callback=add
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        self.assertTrue(any(m['content']=='纠正刚才的计划：合成松果计划已经取消。' for pair in self.s.recent(self.s.session_id) for m in pair['messages']))
    def test_failure_attempt_persists_across_reviewer_restart(self):
        def fail(*args,**kw):self.adapter.calls+=1;raise ValueError('synthetic-only')
        self.adapter.complete=fail
        self.assertEqual(self.r.run()['status'],'failed')
        self.r.stop();new=DesktopMemoryReview(self.chat,adapter=self.adapter)
        self.assertEqual(new.run()['status'],'not_due');self.assertEqual(self.adapter.calls,1)
    def test_stop_and_pause_late_responses_and_chat_lock(self):
        for action in ['pause','stop']:
            with self.subTest(action=action):
                if action=='pause':self.adapter.callback=lambda:self.r.configure(False)
                else:
                    self.r.configure(True);self.adapter.callback=self.r.stop
                result=self.r.run(force=True);self.assertNotEqual(result['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_invalid_second_decision_does_not_partly_apply(self):
        view=self.s.summary_view(self.s.session_id,keep_recent=1,batch=3)
        self.s.commit_summary(self.s.session_id,view,view['new_turns'],'第二条合成待审')
        count=[0]
        def edit(d,e):
            count[0]+=1
            if count[0]==2:d['revision']='wrong-revision'
        self.adapter.edit=edit
        self.assertEqual(self.r.run(force=True)['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_http_pause_and_workbench_close_while_review_waits(self):
        from workbench.server import WorkbenchServer
        from urllib.request import Request,urlopen
        for action in ['pause','close']:
            with self.subTest(action=action),tempfile.TemporaryDirectory() as folder:
                server=WorkbenchServer(Path(folder));server.memory_reviewer.stop()
                server.chat=self.chat;server.memory_reviewer=DesktopMemoryReview(self.chat,adapter=self.adapter)
                reviewer=server.memory_reviewer;reviewer.configure(True)
                entered=threading.Event();release=threading.Event();done=threading.Event()
                original=self.adapter.complete
                def complete(*args,**kw):
                    entered.set()
                    if not release.wait(3):raise TimeoutError('synthetic release')
                    return original(*args,**kw)
                self.adapter.complete=complete
                original_run=reviewer._claimed_run if hasattr(reviewer,'_claimed_run') else None
                if original_run:
                    def claimed(force):
                        try:return original_run(force)
                        finally:done.set()
                    reviewer._claimed_run=claimed
                serving=threading.Thread(target=server.serve,daemon=True);serving.start()
                def post(command,params=None):
                    req=Request(server.origin+'/api/call',data=json.dumps({'command':command,'params':params or {}}).encode(),headers={'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
                    with urlopen(req,timeout=1) as response:return json.load(response)
                try:
                    self.assertEqual(post('chat.layers.auto_review.run')['result']['status'],'queued');self.assertTrue(entered.wait(1))
                    self.assertTrue(self.chat.guard.acquire(timeout=.2));self.chat.guard.release()
                    if action=='pause':self.assertFalse(post('chat.layers.auto_review.configure',{'enabled':False})['result']['enabled'])
                    else:server.stop();self.assertTrue(reviewer.cancel.is_set())
                    self.assertFalse(release.is_set());release.set();self.assertTrue(done.wait(2))
                    self.assertEqual(self.chat.layers.snapshot()['approved'],[])
                finally:
                    release.set();server.stop();serving.join(2);server.server_close();self.adapter.complete=original

    def test_stop_after_initial_guard_rolls_back_batch(self):
        decide=self.chat.layers.decide
        def interleave(decisions,**kw):
            guard=kw['review_guard']
            def after_guard(db):guard(db);self.r.stop()
            kw['review_guard']=after_guard
            return decide(decisions,**kw)
        self.chat.layers.decide=interleave
        self.assertNotEqual(self.r.run()['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_successful_audit_not_evicted_by_later_checks(self):
        self.assertEqual(self.r.run()['status'],'completed')
        for n in range(101):self.r._record({'status':'deferred','at':str(n),'code':'synthetic-no-source'})
        with self.s.read_connection() as db:
            rows=[json.loads(row[0]) for row in db.execute('SELECT payload FROM lmar_runs')]
        self.assertTrue(any(row['status']=='completed' and row.get('decisions') for row in rows))

    def test_dependency_error_code_cannot_leak_arbitrary_text(self):
        class Fault(Exception):code='SYNTHETIC-SECRET-NOT-A-REAL-KEY'
        def fail(*args,**kw):raise Fault('sensitive synthetic body')
        self.adapter.complete=fail
        result=self.r.run();self.assertEqual(result['status'],'failed');self.assertNotIn(Fault.code,json.dumps(self.r.status()))

def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(Tests)

if __name__=='__main__':main(argv=[sys.argv[0]]+rest,verbosity=2)
