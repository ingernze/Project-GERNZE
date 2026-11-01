"""Synthetic L3 -> source review -> L2. No credentials/private data/network."""
from pathlib import Path
import sys,tempfile,unittest,uuid,json,types,threading,time,contextlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from workbench.companion_chat import CompanionChat
from workbench.desktop_memory_review import DesktopMemoryReview

class Keys:
    def __init__(self):self.values={}
    def get(self,k):return self.values.get(k,'')
    def set(self,k,v):self.values[k]=v
    def delete(self,k):self.values.pop(k,None)
class Adapter:
    limits=types.SimpleNamespace(context_window=32768,margin=512,io_timeout=1)
    def __init__(self):self.calls=0;self.edit=None;self.callback=None;self.messages=None
    def count(self,messages):return len(json.dumps(messages,ensure_ascii=False).encode())+128
    def complete(self,messages,maximum,control,report,**kw):
        self.calls+=1;self.messages=messages;control.check()
        entries=json.loads(messages[1]['content'])['entries'];out=[]
        for e in entries:
            source=next(s for s in e['sources'] if s['role']=='user');text=source['content']
            d={'key':e['key'],'revision':e['revision'],'action':'approve' if text==e['body'] else 'correct','text':text,'evidence':[{'messageId':source['id'],'quote':text}],'reason':'合成核验：有用户原话。'}
            if self.edit:self.edit(d,e)
            out.append(d)
        if self.callback:self.callback()
        return json.dumps({'decisions':out},ensure_ascii=False)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.chat=CompanionChat(Path(self.temp.name)/'chat.json',keys=Keys())
        self.chat.configure({'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic','key':'synthetic-only'})
        self.s=self.chat.store
        for i in range(8):
            rid=str(uuid.uuid4());self.s.begin_turn(self.s.session_id,'我把合成松果计划排在下周，尚未开始。',rid)
            self.s.complete(rid,{'text':'这是助手观点，不是用户事实。','emotion':'normal','action':'none'},self.s.epoch(),[])
        view=self.s.summary_view(self.s.session_id,keep_recent=1,batch=3)
        self.s.commit_summary(self.s.session_id,view,view['new_turns'],'我把合成松果计划排在下周，尚未开始。')
        with self.s.connection() as db:db.execute("UPDATE lm_working SET updated_at='2000-01-01T00:00:00Z'")
        self.w=self.chat.layers.snapshot()['pending'][0];self.adapter=Adapter();self.r=DesktopMemoryReview(self.chat,adapter=self.adapter)
    def test_auto_approve_source_backed_and_do_not_send_upper_layers(self):
        result=self.r.run();self.assertEqual(result['status'],'completed');self.assertEqual(result['result']['applied'],1)
        self.assertEqual(self.chat.layers.snapshot()['approved'][0]['body'],self.w['body'])
        data=json.loads(self.adapter.messages[1]['content']);self.assertEqual(set(data),{'entries'});self.assertNotIn('core',data);self.assertNotIn('approved',data)
        self.assertEqual(self.r.run()['status'],'not_due');self.assertEqual(self.adapter.calls,1)
    def test_correct_only_exact_user_quote(self):
        with self.s.connection() as db:db.execute("UPDATE lm_working SET body='错误的合成摘要'")
        self.assertEqual(self.r.run()['status'],'completed')
        self.assertEqual(self.chat.layers.snapshot()['approved'][0]['body'],self.w['body'])
    def test_hallucinated_rewrite_and_assistant_quote_are_rejected(self):
        self.adapter.edit=lambda d,e:d.update(text='捏造长期爱好')
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        def assistant(d,e):
            s=next(s for s in e['sources'] if s['role']=='assistant');d.update(action='correct',text=s['content'],evidence=[{'messageId':s['id'],'quote':s['content']}])
        self.adapter.edit=assistant
        self.assertEqual(self.r.run(force=True)['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_extra_tool_fields_and_new_keys_do_not_grant_permissions(self):
        self.adapter.edit=lambda d,e:d.update(tools=['write_core'])
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        self.adapter.edit=lambda d,e:d.update(key='new-model-key')
        self.assertEqual(self.r.run(force=True)['status'],'failed')
    def test_disable_while_model_inflight_drops_result(self):
        self.adapter.callback=lambda:self.r.configure(False)
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        self.assertEqual(self.r.run(force=True)['status'],'disabled')
    def test_source_retired_while_model_inflight_drops_result(self):
        def retire():
            with self.s.connection() as db:db.execute('UPDATE lc_messages SET allowed=0')
        self.adapter.callback=retire
        self.assertEqual(self.r.run()['status'],'failed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_old_approval_cannot_revive_withdrawn_second_layer(self):
        self.r.run();a=self.chat.layers.snapshot()['approved'][0]
        self.chat.change_approved(a['key'],a['revision'],withdraw=True)
        self.assertEqual(self.r.run(force=True)['status'],'no_pending');self.assertTrue(self.chat.layers.snapshot()['approved'][0]['deleted'])
    def test_defer_does_not_promote_or_spin(self):
        self.adapter.edit=lambda d,e:d.update(action='defer',text='',evidence=[],reason='合成：来源有歧义。')
        self.assertEqual(self.r.run()['status'],'completed');self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        self.assertEqual(self.r.run()['status'],'not_due');self.assertEqual(self.adapter.calls,1)
    def test_phone_missing_source_never_calls_model(self):
        with self.s.connection() as db:db.execute('INSERT INTO lm_layer_sync_meta VALUES (?,?)',('phone3:'+self.w['key']+':'+self.w['revision'],json.dumps({'device':str(uuid.uuid4()),'sessionId':'synthetic-phone','start':0,'end':6})))
        self.chat.layers.phone_source=lambda *args:{'complete':False,'turns':[]}
        self.assertEqual(self.r.run()['status'],'deferred');self.assertEqual(self.adapter.calls,0);self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_unconfigured_manual_interval_and_stop_do_not_call_model(self):
        self.chat.configure({'enabled':False,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'})
        self.assertEqual(self.r.run()['status'],'unconfigured');self.assertEqual(self.adapter.calls,0)
        self.chat.configure({'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'})
        self.chat.layers.configure({'reviewDays':None,'summaryDays':7,'summaryEnabled':True})
        self.assertEqual(self.r.run()['status'],'not_due');self.r.stop();self.assertEqual(self.r.run(force=True)['status'],'stopped')
    def test_context_overflow_leaves_pending_without_provider_call(self):
        self.adapter.limits=types.SimpleNamespace(context_window=256,margin=100,io_timeout=1)
        self.assertEqual(self.r.run()['status'],'deferred');self.assertEqual(self.adapter.calls,0);self.assertEqual(len(self.chat.layers.snapshot()['pending']),1)
    def test_empty_source_never_calls_provider(self):
        self.r._sources=lambda entry:[]
        self.assertEqual(self.r.run()['status'],'deferred');self.assertEqual(self.adapter.calls,0)

    def test_progress_reports_real_stage_and_completion_without_content(self):
        phases=[]
        self.adapter.callback=lambda:phases.append(self.r.status()['progress'])
        result=self.r.run(force=True)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(phases[0]['phase'],'model')
        self.assertEqual(set(phases[0]),{'phase','state','message','steps','counts'})
        self.assertEqual(self.r.status()['progress']['state'],'complete')

    @contextlib.contextmanager
    def slow_provider(self,delay):
        received=threading.Event();requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(data);received.set();time.sleep(delay)
                entries=json.loads(data['messages'][1]['content'])['entries']
                decisions=[{'key':e['key'],'revision':e['revision'],'action':'defer','text':'','evidence':[],'reason':'合成：保留待审。'} for e in entries]
                raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'decisions':decisions})}}]}).encode()
                try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                except OSError:pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        # Set the connection BEFORE generating synthetic source turns. A
        # connection change correctly retires already-exposed old context.
        self.chat=CompanionChat(Path(self.temp.name)/'slow/chat.json',keys=Keys())
        self.chat.configure({'enabled':True,'endpoint':'http://127.0.0.1:'+str(server.server_port)+'/chat/completions','model':'synthetic','key':'synthetic-only'})
        self.s=self.chat.store
        for i in range(8):
            rid=str(uuid.uuid4());self.s.begin_turn(self.s.session_id,'我把合成松果计划排在下周，尚未开始。',rid)
            self.s.complete(rid,{'text':'合成助手回应','emotion':'normal','action':'none'},self.s.epoch(),[])
        view=self.s.summary_view(self.s.session_id,keep_recent=1,batch=3)
        self.s.commit_summary(self.s.session_id,view,view['new_turns'],'合成待审计划。')
        with self.s.connection() as db:db.execute("UPDATE lm_working SET updated_at='2000-01-01T00:00:00Z'")
        try:yield received,requests
        finally:server.shutdown();worker.join(2);server.server_close()
    def test_slow_response_after_two_seconds_uses_remaining_review_budget(self):
        from workbench.summary_wiring import adapter_for_chat
        with self.slow_provider(2.3) as (received,requests):
            reviewer=DesktopMemoryReview(self.chat)
            result=reviewer.run()
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['result']['applied'],0)
            self.assertEqual(len(requests),1);self.assertEqual(requests[0]['max_tokens'],8192)
            self.assertEqual(reviewer.adapter.limits.io_timeout,60)
            self.assertEqual(adapter_for_chat(self.chat).limits.io_timeout,2)
            self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_total_deadline_still_stops_without_retry(self):
        from workbench import desktop_memory_review as module
        with self.slow_provider(.8) as (received,requests),patch.object(module,'REVIEW_TIMEOUT_S',.3):
            reviewer=DesktopMemoryReview(self.chat);start=time.monotonic();result=reviewer.run()
            self.assertIn(result['code'],{'deadline_exceeded','io_timeout'});self.assertLess(time.monotonic()-start,1)
            self.assertEqual(len(requests),1);self.assertEqual(reviewer.run()['status'],'not_due')
            self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_stop_returns_promptly_and_late_slow_response_cannot_commit(self):
        with self.slow_provider(.5) as (received,requests):
            reviewer=DesktopMemoryReview(self.chat);result=[];worker=threading.Thread(target=lambda:result.append(reviewer.run()));worker.start()
            self.assertTrue(received.wait(2));start=time.monotonic();reviewer.stop();self.assertLess(time.monotonic()-start,.3)
            worker.join(3);self.assertFalse(worker.is_alive());self.assertEqual(result[0]['code'],'cancelled')
            self.assertEqual(len(requests),1);self.assertEqual(self.chat.layers.snapshot()['approved'],[])

    def test_completion_numbers_and_finish_reason_survive_failure_without_private_text(self):
        from workbench.summary_adapter import SummaryAdapterError
        def fail(messages,maximum,control,report,**kwargs):
            report.update(max_tokens=maximum,completion_tokens=2048,reasoning_tokens=2048,finish_reason='length',body='PRIVATE-SYNTHETIC-REPLY',reasoning_content='PRIVATE-SYNTHETIC-THOUGHT')
            raise SummaryAdapterError('not_complete')
        self.adapter.complete=fail;result=self.r.run()
        self.assertEqual(result['completion'],{'max_tokens':8192,'completion_tokens':2048,'reasoning_tokens':2048,'finish_reason':'length'})
        self.assertNotIn('PRIVATE-SYNTHETIC',json.dumps(self.r.status()))
        self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_untrusted_completion_metadata_is_never_persisted(self):
        from workbench.summary_adapter import SummaryAdapterError
        def fail(messages,maximum,control,report,**kwargs):
            report.update(completion_tokens=True,reasoning_tokens='PRIVATE-SYNTHETIC',finish_reason='PRIVATE-SYNTHETIC')
            raise SummaryAdapterError('not_complete')
        self.adapter.complete=fail;result=self.r.run()
        self.assertNotIn('completion',result);self.assertNotIn('PRIVATE-SYNTHETIC',json.dumps(self.r.status()))

    def test_actual_progress_waits_for_model_and_only_finishes_after_commit(self):
        entered=threading.Event();release=threading.Event();result=[]
        def wait():entered.set();release.wait(5)
        self.adapter.callback=wait
        worker=threading.Thread(target=lambda:result.append(self.r.run(force=True)));worker.start()
        try:
            self.assertTrue(entered.wait(3));before=self.r.status()['progress']
            self.assertEqual(before['steps'],{'completed':2,'total':5})
            self.assertEqual(before['counts']['selected'],1);self.assertEqual(before['counts']['processed'],0)
            time.sleep(.03);self.assertEqual(self.r.status()['progress'],before)
            self.assertEqual(self.chat.layers.snapshot()['approved'],[])
        finally:release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(result[0]['status'],'completed')
        after=self.r.status()['progress'];self.assertEqual(after['steps'],{'completed':5,'total':5})
        self.assertEqual(after['counts']['processed'],1);self.assertIn('1/1',after['message'])
    def test_model_failure_keeps_actual_step_and_never_reports_completion(self):
        from workbench.summary_adapter import SummaryAdapterError
        def fail():raise SummaryAdapterError('io_timeout')
        self.adapter.callback=fail;self.assertEqual(self.r.run(force=True)['status'],'failed')
        progress=self.r.status()['progress'];self.assertEqual(progress['state'],'error')
        self.assertEqual(progress['steps']['completed'],2);self.assertEqual(progress['counts']['processed'],0)
        self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_failed_commit_does_not_finish_progress_and_next_run_resets_steps(self):
        with patch.object(self.chat.layers,'decide',side_effect=ValueError('review_basis_changed')):
            self.assertEqual(self.r.run(force=True)['status'],'failed')
        self.assertEqual(self.r.status()['progress']['steps']['completed'],4)
        self.assertEqual(self.r.status()['progress']['counts']['processed'],0)
        phases=[];original=self.r._phase
        def capture(*a,**kw):original(*a,**kw);phases.append(self.r.status()['progress'])
        self.r._phase=capture;self.assertEqual(self.r.run(force=True)['status'],'completed')
        self.assertEqual(phases[0]['steps']['completed'],0);self.assertEqual(phases[-1]['steps']['completed'],5)

    def test_completed_review_reports_deferred_not_written(self):
        self.adapter.edit=lambda d,e:d.update(action='defer',text='',evidence=[],reason='合成：保留待审')
        self.assertEqual(self.r.run(force=True)['status'],'completed')
        progress=self.r.status()['progress'];self.assertEqual(progress['steps']['completed'],5)
        self.assertEqual(progress['counts']['written'],0);self.assertEqual(progress['counts']['deferred'],1)
        self.assertEqual(progress['counts']['excluded'],0);self.assertIn('写入0条，保留待审1条',progress['message'])
        self.assertEqual(self.chat.layers.snapshot()['approved'],[])
    def test_completed_review_reports_written_and_excluded_separately(self):
        self.assertEqual(self.r.run(force=True)['status'],'completed')
        self.assertEqual(self.r.status()['progress']['counts']['written'],1)
        # A new independent fixture distinguishes rejection from a new memory.
        other=Tests();other.setUp()
        try:
            other.adapter.edit=lambda d,e:d.update(action='reject',text='',evidence=[],reason='合成：排除')
            self.assertEqual(other.r.run(force=True)['status'],'completed')
            counts=other.r.status()['progress']['counts'];self.assertEqual(counts['written'],0)
            self.assertEqual(counts['excluded'],1);self.assertEqual(counts['deferred'],0)
            self.assertEqual(other.chat.layers.snapshot()['approved'],[])
        finally:other.doCleanups()

if __name__=='__main__':unittest.main(verbosity=2)
