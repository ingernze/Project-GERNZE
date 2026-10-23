"""Synthetic L3 -> source review -> L2. No credentials/private data/network."""
from pathlib import Path
import sys,tempfile,unittest,uuid,json,types,threading
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

if __name__=='__main__':unittest.main(verbosity=2)
