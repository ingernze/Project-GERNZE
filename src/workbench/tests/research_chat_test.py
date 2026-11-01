"""General research selection uses the existing bounded host/journal path."""
import json,unittest,uuid
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import research_context_test as fixtures
import research_books_test as books
from workbench.study_chat import StudyChat,ResearchChat
from workbench import server

def uid():return str(uuid.uuid4())

class ResearchChatTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ResearchWiringTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.chat=self.h.chat;self.service=ResearchChat(self.chat)
        self.source,self.entry=self.h.seed(course=False,text='GENERAL_SELECTED_BODY')
        self.materials=[{'id':self.entry[0],'revision':self.entry[1]}]
    def send(self,materials=None,text='解释所选资料',rid=None):return self.service.reply(text,rid or uid(),materials or self.materials)
    def test_general_material_enters_actual_payload_and_atomic_dependencies(self):
        rid=uid();result=self.send(rid=rid)
        self.assertEqual(result['research_use'],{'status':'ready','used':1})
        self.assertIn('GENERAL_SELECTED_BODY',json.dumps(self.h.http.requests[-1]))
        self.assertEqual(self.h.exposures(rid)[0]['id'],self.entry[0])
        self.assertIsNone(self.chat.research_provider._host_binding.get())
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)
    def test_general_route_rejects_course_and_mixed_batch_before_body(self):
        _,entry=self.h.seed(course=True,text='COURSE_NOT_AUTHORIZED')
        for values in [[{'id':entry[0],'revision':entry[1]}],self.materials+[{'id':entry[0],'revision':entry[1]}]]:
            self.h.events.clear()
            with self.assertRaises(ValueError):self.send(values)
            self.assertFalse(self.h.body_queries());self.assertEqual(self.h.http.requests,[])
    def test_original_study_route_still_rejects_general_material(self):
        self.h.events.clear()
        with self.assertRaises(ValueError):StudyChat(self.chat).reply('解释',uid(),self.materials)
        self.assertFalse(self.h.body_queries());self.assertEqual(self.h.http.requests,[])
    def test_model_failure_clears_host_selection(self):
        self.h.http.callback=lambda:(_ for _ in ()).throw(RuntimeError('synthetic'))
        with self.assertRaises(ValueError):self.send()
        self.assertIsNone(self.chat.research_provider._host_binding.get());self.assertEqual(self.chat.research_provider._bindings,{})
        self.h.http.callback=None;self.chat.reply_request('普通问题',request_id=uid())
        self.assertNotIn('GENERAL_SELECTED_BODY',json.dumps(self.h.http.requests[-1]))
    def test_version_or_withdrawal_rejected_before_new_body(self):
        self.h.events.clear()
        with self.assertRaises(ValueError):self.send([{'id':self.entry[0],'revision':uid()}])
        self.assertFalse(self.h.body_queries())
        self.chat.store.catalog.change_source(*self.source,state='withdrawn');self.h.events.clear()
        with self.assertRaises(ValueError):self.send()
        self.assertFalse(self.h.body_queries());self.assertEqual(self.h.http.requests,[])
    def test_inflight_source_change_discards_answer(self):
        self.h.http.callback=lambda:self.chat.store.catalog.change_source(*self.source,state='withdrawn');rid=uid()
        with self.assertRaises(ValueError):self.send(rid=rid)
        self.assertIsNone(self.h.exposures(rid));self.assertIsNone(self.chat.research_provider._host_binding.get())
    def test_same_selection_cache_retry_and_ordinary_replay_are_separate(self):
        rid=uid();self.send(rid=rid);n=len(self.h.http.requests)
        self.assertEqual(self.send(rid=rid)['research_use'],{'status':'cached','used':1});self.assertEqual(len(self.h.http.requests),n)
        with self.assertRaises(ValueError):self.chat.reply_request('解释所选资料',request_id=rid)
        self.assertEqual(len(self.h.http.requests),n)
    def test_budget_omission_happens_before_material_body(self):
        _,entry=self.h.seed(course=False,text='LONG_GENERAL_'+('甲'*6500));self.h.events.clear()
        result=self.send([{'id':entry[0],'revision':entry[1]}])
        self.assertEqual(result['research_use'],{'status':'budget_omitted_before_body','used':0})
        self.assertFalse(self.h.body_queries());self.assertNotIn('LONG_GENERAL_',json.dumps(self.h.http.requests))
    def test_no_research_request_skips_selection_and_material_body(self):
        self.h.events.clear();self.send(text='不要读取资料，只回答我这句话')
        self.assertFalse(self.h.body_queries());self.assertNotIn('GENERAL_SELECTED_BODY',json.dumps(self.h.http.requests))
    def test_general_history_inherits_source_without_rereading_material(self):
        self.h.http.text='GENERAL_DERIVED_ANSWER';rid=uid();self.send(rid=rid);self.h.events.clear()
        second=uid();self.chat.reply_request('继续说明',request_id=second)
        self.assertEqual(self.h.exposures(second)[0]['id'],self.entry[0]);self.assertFalse(any(q.startswith('SELECT body FROM rc_bodies') for q in self.h.events))
        self.chat.store.catalog.change_source(*self.source,state='withdrawn');self.chat.reply_request('普通问题',request_id=uid())
        self.assertNotIn('GENERAL_DERIVED_ANSWER',json.dumps(self.h.http.requests[-1]))

class ResearchChatHTTPTests(unittest.TestCase):
    def setUp(self):
        original=server.WorkbenchServer
        self.h=books.ResearchBooksHTTPTests()
        with patch.object(server,'WorkbenchServer',side_effect=lambda *a,**k:original(*a,research_enabled=True,**k)):self.h.setUp()
        self.addCleanup(self.h.doCleanups);self.s=self.h.s;self.post=self.h.post
        self.s.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'synthetic'})
        source=self.s.chat.store.catalog.create_source('web','synthetic')
        self.entry=self.s.chat.store.catalog.add_entry('GENERAL_HTTP_SELECTED',[source])
        self.params={'text':'解释所选资料','request_id':uid(),'materials':[{'id':self.entry[0],'revision':self.entry[1]}]}
    def test_authenticated_general_route_and_real_request(self):
        self.assertEqual(self.post('chat.research.reply',self.params,token='wrong')[0],403)
        self.assertTrue(self.post('chat.research.status')[1]['result']['available'])
        code,value=self.post('chat.research.reply',self.params);self.assertEqual(code,200,value);self.assertEqual(value['result']['research_use']['used'],1)
        self.assertIn('GENERAL_HTTP_SELECTED',json.dumps(self.s.chat.http.requests[-1]))
    def test_strict_http_shape_and_cross_route_denial(self):
        self.assertEqual(self.post('chat.research.reply',{**self.params,'study':True})[0],400)
        self.assertEqual(self.post('chat.research.reply',{**self.params,'materials':[{**self.params['materials'][0],'grant':True}]})[0],400)
        self.assertEqual(self.post('chat.study.reply',self.params)[0],400)
        self.assertEqual(self.post('chat.reply',self.params)[0],400);self.assertEqual(self.s.chat.http.requests,[])
    def test_wrong_origin_cannot_select_general_sources(self):
        request=Request(self.s.origin+'/api/call',data=json.dumps({'command':'chat.research.reply','params':self.params}).encode(),
                        headers={'Authorization':'Bearer '+self.s.token,'Content-Type':'application/json','Origin':'https://untrusted.invalid'},method='POST')
        with self.assertRaises(HTTPError) as error:urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,403);self.assertEqual(self.s.chat.http.requests,[])

if __name__=='__main__':unittest.main(verbosity=2)
