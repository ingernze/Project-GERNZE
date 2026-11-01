"""Synthetic response policy tests, no production API/persona or private data."""
import io,json,socket,sys,tempfile,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from companion_chat import CompanionChat,normalized_reply,reply_reserve_for
from context_manager import ContextManager,Budget
from conversation_store import ChatStateError

class Keys:
    def __init__(self):self.values={}
    def get(self,k):return self.values.get(k,'')
    def set(self,k,v):self.values[k]=v
class HTTP:
    def __init__(self):self.requests=[];self.content='{"text":"合成完整回复"}';self.finish='stop';self.entered=None;self.release=None
    def open(self,request,timeout):
        self.requests.append(json.loads(request.data))
        if self.entered:self.entered.set();self.release.wait(3)
        return io.BytesIO(json.dumps({'choices':[{'finish_reason':self.finish,'message':{'content':self.content}}]}).encode())

class ReplyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        blocker=patch.object(socket.socket,'connect',side_effect=AssertionError('network prohibited'));blocker.start();self.addCleanup(blocker.stop)
        public=patch('companion_chat.system_prompt',return_value='公开合成人设。');public.start();self.addCleanup(public.stop)
        self.http=HTTP();self.chat=CompanionChat(Path(self.tmp.name)/'chat.json',keys=Keys(),opener=self.http)
        self.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'fixture','key':'SYNTHETIC'})
    def test_short_and_detailed_capture_actual_payload_and_budget(self):
        for text,n in [('你好',700),('请详细分析这个合成问题',1800),('帮我深入解释这个合成问题',1800)]:
            self.chat.reply_request(text);report=self.chat.last_context;payload=self.http.requests[-1]
            self.assertEqual(payload['max_tokens'],n);self.assertEqual(report['reply_reserve'],n)
            self.assertLessEqual(self.chat.context.count(payload['messages'])+n+report['margin'],self.chat.context.budget.context_window)
        self.assertEqual(len(self.http.requests),3)
    def test_untrusted_and_quoted_requests_never_raise_reserve(self):
        for text,origin in [('请详细分析这个合成问题','external_ai'),('请详细分析这个合成问题','quote'),('作者说“请详细分析这个问题”','user'),('请解释这句："详细分析"','user'),('> 请详细分析','user'),('请阅读材料：详细分析是书中用语','user'),('请引用材料中详细分析这一段','user')]:
            self.chat.reply_request(text,origin=origin);self.assertEqual(self.http.requests[-1]['max_tokens'],700)
    def test_broken_json_not_success_and_no_hidden_retry(self):
        for content in ['{"text":"partial', '{"text":"a","text":"b"}', '```json\n{"text":"broken\n```']:
            self.http.content=content;before=len(self.http.requests)
            with self.assertRaises(ValueError):self.chat.reply_request('合成问题',request_id=str(uuid.uuid4()))
            self.assertEqual(len(self.http.requests),before+1)
            self.assertEqual(self.chat.store.recent(self.chat.store.session_id),[])
    def test_complete_plaintext_compatibility(self):
        self.http.content='完整纯文本回复。';self.assertEqual(self.chat.reply('合成问题')['text'],self.http.content)
    def test_length_finish_never_commits_even_valid_json(self):
        self.http.finish='length'
        with self.assertRaises(ValueError):self.chat.reply('合成问题')
        self.assertEqual(self.chat.store.recent(self.chat.store.session_id),[]);self.assertEqual(len(self.http.requests),1)
    def test_long_legal_body_survives_transport_store_and_cache(self):
        text='合成正文。'*1000;self.http.content=json.dumps({'text':text})
        rid=str(uuid.uuid4());one=self.chat.reply_request('请详细说明合成内容',request_id=rid);two=self.chat.reply_request('请详细说明合成内容',request_id=rid)
        self.assertEqual(one['text'],text);self.assertEqual(two['text'],text);self.assertEqual(len(self.http.requests),1)
        self.assertEqual(self.chat.store.recent(self.chat.store.session_id)[0]['messages'][1]['content'],text)
    def test_oversize_fails_instead_of_cutting(self):
        with self.assertRaises(ValueError):normalized_reply(json.dumps({'text':'x'*64001}))
    def test_cancel_inflight_rejects_late_result(self):
        self.http.entered=threading.Event();self.http.release=threading.Event();errors=[];rid=str(uuid.uuid4())
        def run():
            try:self.chat.reply_request('合成问题',request_id=rid)
            except Exception as e:errors.append(e)
        t=threading.Thread(target=run);t.start();self.assertTrue(self.http.entered.wait(1));self.chat.cancel(rid);self.http.release.set();t.join(3)
        self.assertFalse(t.is_alive());self.assertTrue(errors);self.assertEqual(self.chat.store.recent(self.chat.store.session_id),[])
    def test_session_change_rejects_old_result(self):
        self.http.entered=threading.Event();self.http.release=threading.Event();errors=[]
        def run():
            try:self.chat.reply_request('合成旧会话问题')
            except Exception as e:errors.append(e)
        old=self.chat.store.session_id;t=threading.Thread(target=run);t.start()
        self.assertTrue(self.http.entered.wait(1));self.chat.select_session();self.http.release.set();t.join(3)
        self.assertFalse(t.is_alive());self.assertTrue(errors)
        self.assertEqual(self.chat.store.recent(old),[])
        self.assertEqual(self.chat.store.recent(self.chat.store.session_id),[])
    def test_plaintext_missing_finish_reason_legacy_compatibility(self):
        self.http.finish=None;self.http.content='合成旧提供方完整正文。'
        self.assertEqual(self.chat.reply('合成问题')['text'],self.http.content)
    def test_small_window_detailed_fails_before_transport(self):
        self.chat.context=ContextManager(budget=Budget(context_window=2200))
        with self.assertRaises(ChatStateError):self.chat.reply('请详细解释合成问题')
        self.assertEqual(self.http.requests,[])
    def test_request_policy_does_not_mutate_shared_budget(self):
        self.chat.reply('请详细解释合成问题');self.assertEqual(self.chat.context.budget.reply_reserve,700)
        self.chat.reply('你好');self.assertEqual(self.http.requests[-1]['max_tokens'],700)

if __name__=='__main__':unittest.main(verbosity=2)
