"""Synthetic long-body summary integration; no real keys, persona or network."""
import io,json,pathlib,socket,sys,tempfile,threading,time,unittest,uuid
from email.message import Message
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from conversation_store import ConversationStore
from context_manager import ContextManager
from memory_layers import MemoryLayers
from summary_adapter import SummaryAdapter,SummaryAdapterError,validate_request,Limits

def request(body):
    ids=[str(uuid.uuid4()) for _ in range(3)]
    return {'existing_summaries':[],'new_block':[{'turn_id':ids[0],'source_ids':ids[1:],'origin':'user','messages':[{'role':'user','content':'合成问题'},{'role':'assistant','content':body}]}],
            'source_turn_ids':ids[:1],'max_output_units':512,'instruction':'只总结原文'}

class Response(io.BytesIO):
    def __init__(self):
        raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"text":"合成摘要"}'}}]}).encode()
        super().__init__(raw);self.status=200;self.headers=Message();self.headers['Content-Type']='application/json';self.headers['Content-Length']=str(len(raw))
    def geturl(self):return 'https://synthetic.invalid/chat/completions'

class HTTP:
    def __init__(self):self.calls=[]
    def open(self,req,**kwargs):self.calls.append(json.loads(req.data));return Response()

class LongSummaryTests(unittest.TestCase):
    def setUp(self):
        blocker=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'));blocker.start();self.addCleanup(blocker.stop)
    def adapter(self):
        http=HTTP();keys=[]
        adapter=SummaryAdapter(settings_getter=lambda:{'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'},
            key_getter=lambda config:(keys.append(True) or 'synthetic-only'),http=http)
        return adapter,http,keys
    def test_full4300_body_reaches_real_adapter_HTTP_without_cut(self):
        adapter,http,keys=self.adapter();data=request('x'*4300)
        result=adapter(data,cancel_event=threading.Event(),deadline=time.monotonic()+2)
        actual=json.loads(http.calls[0]['messages'][1]['content'])
        self.assertEqual(actual['new_block'][0]['messages'][1]['content'],'x'*4300)
        self.assertEqual(result['source_turn_ids'],data['source_turn_ids']);self.assertEqual(len(keys),1);self.assertEqual(http.calls[0]['max_tokens'],512)
    def test_body_cap_matches_chat_but_budget_still_rejects_before_key_and_HTTP(self):
        validate_request(request('x'*64000))
        with self.assertRaises(SummaryAdapterError):validate_request(request('x'*64001))
        adapter,http,keys=self.adapter()
        with self.assertRaises(SummaryAdapterError) as caught:adapter(request('x'*20000),cancel_event=threading.Event(),deadline=time.monotonic()+2)
        self.assertEqual(caught.exception.code,'context_overflow');self.assertEqual(keys,[]);self.assertEqual(http.calls,[])
    def seed(self,root,first='x'*4500):
        store=ConversationStore(pathlib.Path(root)/'synthetic.sqlite3')
        for index in range(12):
            rid=str(uuid.uuid4());store.begin_turn(store.session_id,'合成问题'+str(index),rid)
            store.complete(rid,{'text':first if index==0 else 'y'*1400,'emotion':'normal','action':'none'},store.epoch(),[])
        return store
    def test_due_batch_shrinks_to_one_whole_turn_then_seals_only_that_turn(self):
        with tempfile.TemporaryDirectory(prefix='gernze-long-summary-') as root:
            store=self.seed(root);adapter,http,_=self.adapter();before=store.messages(store.session_id)
            layers=MemoryLayers(store,core_loader=lambda:{'schemaVersion':1,'entries':[]})
            with store.connection() as db:db.execute("UPDATE lc_sessions SET created_at='2000-01-01T00:00:00Z'")
            ctx=ContextManager(summarizer=adapter)
            self.assertEqual(ctx.summarize(store,store.session_id),'committed')
            data=json.loads(http.calls[0]['messages'][1]['content']);self.assertEqual(len(data['new_block']),1)
            self.assertEqual(data['new_block'][0]['messages'][1]['content'],'x'*4500)
            self.assertEqual(store.messages(store.session_id),before)
            self.assertEqual(len(layers.snapshot()['pending']),1)
            with store.read_connection() as db:self.assertEqual(db.execute('SELECT SUM(covered) FROM lc_turns').fetchone()[0],1)
    def test_single_oversized_head_blocks_without_skipping_or_callback(self):
        with tempfile.TemporaryDirectory(prefix='gernze-long-summary-') as root:
            store=self.seed(root,first='中'*6000);calls=[];before=store.messages(store.session_id)
            ctx=ContextManager(summarizer=lambda *args,**kw:calls.append(True))
            self.assertEqual(ctx.summarize(store,store.session_id),'input_too_large');self.assertEqual(calls,[])
            self.assertEqual(store.messages(store.session_id),before)
            with store.read_connection() as db:self.assertIsNone(store._get(db,'summary_clock:'+store.session_id));self.assertEqual(db.execute('SELECT SUM(covered) FROM lc_turns').fetchone()[0],0)
    def test_original_three_new_turn_start_gate_still_applies(self):
        with tempfile.TemporaryDirectory(prefix='gernze-long-summary-') as root:
            store=self.seed(root);view=store.summary_view(store.session_id)
            store.summary_attempt(store.session_id,view['latest_seq']-1,'failed',epoch=view['epoch'])
            calls=[];ctx=ContextManager(summarizer=lambda *args,**kw:calls.append(True))
            self.assertEqual(ctx.summarize(store,store.session_id),'not_due');self.assertEqual(calls,[])

    def test_adapter_full_prompt_preflight_blocks_before_configuration_key_and_HTTP(self):
        adapter=SummaryAdapter(settings_getter=lambda:(_ for _ in ()).throw(AssertionError('config read')),
            key_getter=lambda value:(_ for _ in ()).throw(AssertionError('key read')),limits=Limits(context_window=4096))
        self.assertFalse(adapter.input_fits(request('x'*3500)))
        with tempfile.TemporaryDirectory(prefix='gernze-long-summary-') as root:
            store=self.seed(root,first='x'*3500);ctx=ContextManager(summarizer=adapter)
            self.assertEqual(ctx.summarize(store,store.session_id),'input_too_large')

class TransportFailureTests(unittest.TestCase):
    def check_failure(self,error,expected,*,during_open=False,cancel=False):
        from summary_adapter import CallControl
        event=threading.Event();response=Response()
        def broken_read(size):
            if cancel:event.set()
            raise error('SYNTHETIC-TRANSPORT-PRIVATE-TEXT')
        response.read1=broken_read
        class BrokenHTTP:
            def open(self,req,**kwargs):
                if during_open:raise error('SYNTHETIC-TRANSPORT-PRIVATE-TEXT')
                return response
        adapter=SummaryAdapter(settings_getter=lambda:{'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'},key_getter=lambda c:'synthetic-only',http=BrokenHTTP())
        control=CallControl(event,time.monotonic()+5,1)
        with self.assertRaises(SummaryAdapterError) as caught:adapter.complete([{'role':'user','content':'synthetic'}],128,control,{})
        self.assertEqual(caught.exception.code,expected)
        self.assertNotIn('SYNTHETIC-TRANSPORT-PRIVATE-TEXT',str(caught.exception))
        if not during_open:self.assertTrue(response.closed)
    def test_body_timeout_becomes_safe_code_and_closes_response(self):self.check_failure(TimeoutError,'io_timeout')
    def test_body_disconnect_becomes_safe_code_and_closes_response(self):self.check_failure(ConnectionResetError,'connection_failed')
    def test_open_timeout_becomes_safe_code(self):self.check_failure(TimeoutError,'io_timeout',during_open=True)
    def test_cancellation_wins_over_body_timeout(self):self.check_failure(TimeoutError,'cancelled',cancel=True)

class CompletionMetadataTests(unittest.TestCase):
    def check_response(self,reason,usage):
        from summary_adapter import CallControl
        raw=json.dumps({'choices':[{'finish_reason':reason,'message':{'role':'assistant','content':'','reasoning_content':'PRIVATE-SYNTHETIC-THOUGHT'}}],'usage':usage}).encode()
        response=Response();response.seek(0);response.truncate();response.write(raw);response.seek(0);response.headers.replace_header('Content-Length',str(len(raw)))
        class HTTP:
            def open(self,*args,**kwargs):return response
        adapter=SummaryAdapter(settings_getter=lambda:{'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic'},key_getter=lambda c:'synthetic-only',http=HTTP(),limits=Limits(context_window=32768));report={}
        with self.assertRaises(SummaryAdapterError) as caught:adapter.complete([{'role':'user','content':'synthetic'}],8192,CallControl(threading.Event(),time.monotonic()+2,1),report)
        self.assertEqual(caught.exception.code,'not_complete');self.assertNotIn('PRIVATE-SYNTHETIC',json.dumps(report));self.assertTrue(response.closed);return report
    def test_reasoning_only_length_response_remains_rejected_with_safe_numbers(self):
        report=self.check_response('length',{'completion_tokens':2048,'completion_tokens_details':{'reasoning_tokens':2048}})
        self.assertEqual(report['finish_reason'],'length');self.assertEqual(report['reasoning_tokens'],2048)
    def test_unknown_reason_and_invalid_usage_are_redacted(self):
        report=self.check_response('PRIVATE-SYNTHETIC-REASON',{'completion_tokens':True,'completion_tokens_details':{'reasoning_tokens':'PRIVATE-SYNTHETIC'}})
        self.assertEqual(report['finish_reason'],'other');self.assertNotIn('completion_tokens',report);self.assertNotIn('reasoning_tokens',report)
    def test_missing_finish_reason_is_still_not_a_completed_review(self):
        self.assertEqual(self.check_response(None,{})['finish_reason'],'missing')
    def test_io_boundary_allows_explicit_review60_but_default_stays2(self):
        self.assertEqual(Limits(io_timeout=60).io_timeout,60);self.assertEqual(Limits().io_timeout,2)
        with self.assertRaises(ValueError):Limits(io_timeout=61)

if __name__=='__main__':unittest.main(verbosity=2)
