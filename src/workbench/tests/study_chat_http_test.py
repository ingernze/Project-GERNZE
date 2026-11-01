"""Real authenticated loopback only; independent temporary host and fake API."""
import json
import unittest
import uuid
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import research_books_test as books
from workbench import server


class StudyHTTPTests(unittest.TestCase):
    def setUp(self):
        original=server.WorkbenchServer
        def host(*args,**kwargs):return original(*args,research_enabled=True,**kwargs)
        self.fixture=books.ResearchBooksHTTPTests()
        with patch.object(server,'WorkbenchServer',side_effect=host):self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s=self.fixture.s;self.post=self.fixture.post
        self.s.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'fixture'})
        course=str(uuid.uuid4())
        self.source=self.s.chat.store.catalog.create_source('course','synthetic original',courses=(course,))
        self.entry=self.s.chat.store.catalog.add_entry('COURSE_HTTP_STUDY_SENTINEL',[self.source])
        self.params={'text':'解释合成资料','request_id':str(uuid.uuid4()),'materials':[{'id':self.entry[0],'revision':self.entry[1]}]}

    def test_authenticated_explicit_reply_then_ordinary_context_has_no_course(self):
        self.assertEqual(self.post('chat.study.status',token='wrong')[0],403)
        code,data=self.post('chat.study.status');self.assertEqual(code,200);self.assertTrue(data['result']['available'])
        code,data=self.post('chat.study.reply',self.params)
        self.assertEqual(code,200,data);self.assertEqual(data['result']['research_use']['used'],1)
        self.assertIn('COURSE_HTTP_STUDY_SENTINEL',json.dumps(self.s.chat.http.requests[-1]))
        code,data=self.post('chat.reply',{'text':'普通问题','request_id':str(uuid.uuid4())})
        self.assertEqual(code,200,data)
        self.assertNotIn('COURSE_HTTP_STUDY_SENTINEL',json.dumps(self.s.chat.http.requests[-1]))
        code,data=self.post('chat.history')
        self.assertEqual(len(data['result']['turns']),1)
        self.assertEqual(data['result']['turns'][0]['input'],'普通问题')

    def test_strict_shape_withdrawal_and_ordinary_cache_replay_rejected(self):
        self.assertEqual(self.post('chat.study.reply',{**self.params,'study':True})[0],400)
        self.assertEqual(self.post('chat.reply',{**self.params})[0],400)
        self.assertEqual(self.post('chat.study.reply',self.params)[0],200)
        self.assertEqual(self.post('chat.reply',{'text':self.params['text'],'request_id':self.params['request_id']})[0],400)
        self.s.chat.store.catalog.change_source(*self.source,state='withdrawn')
        self.params['request_id']=str(uuid.uuid4())
        self.assertEqual(self.post('chat.study.reply',self.params)[0],400)

    def test_wrong_origin_cannot_issue_study_request(self):
        request=Request(self.s.origin+'/api/call',data=json.dumps({'command':'chat.study.reply','params':self.params}).encode(),
                        headers={'Authorization':'Bearer '+self.s.token,'Origin':'https://untrusted.invalid','Content-Type':'application/json'},method='POST')
        with self.assertRaises(HTTPError) as error:urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,403)
        self.assertEqual(self.s.chat.http.requests,[])


if __name__=='__main__':unittest.main()
