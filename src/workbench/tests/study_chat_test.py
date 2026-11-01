"""Explicit host course intent with real journal/context and fake transport."""
from copy import deepcopy
import json
import threading
import unittest
import uuid

from workbench.conversation_store import ChatStateError
from workbench.memory_archive import MemoryArchive
from workbench.research_catalog import ResearchAccess, ResearchError
from workbench.study_chat import StudyChat
import research_context_test as fixtures


def uid(): return str(uuid.uuid4())


class StudyChatTests(unittest.TestCase):
    captures=[]
    def setUp(self):
        self.fixture=fixtures.ResearchWiringTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.chat=self.fixture.chat;self.events=self.fixture.events;self.http=self.fixture.http
        self.service=StudyChat(self.chat)

    def tearDown(self):
        self.captures.append({'case':self.id(),'sql':self.events[:],'payloads':self.http.requests[:]})

    def seed(self, **kwargs):
        source,entry=self.fixture.seed(**kwargs)
        return source,entry,[{'id':entry[0],'revision':entry[1]}]

    def send(self, materials, text='请解释这份资料。', request_id=None):
        return self.service.reply(text, request_id or uid(), materials)

    def test_status_is_metadata_free_and_has_no_request(self):
        self.events.clear()
        self.assertEqual(self.service.status(),{'available':True,'maxMaterials':8,'scope':'one_request'})
        self.assertEqual(self.events,[]);self.assertEqual(self.http.requests,[])

    def test_explicit_selection_enters_real_request_and_dependency(self):
        _,entry,materials=self.seed();rid=uid()
        result=self.send(materials,request_id=rid)
        self.assertEqual(result['research_use'],{'status':'ready','used':1})
        self.assertIn('COURSE_SECRET_source',json.dumps(self.http.requests[-1]))
        self.assertEqual(self.fixture.exposures(rid)[0]['id'],entry[0])
        self.assertIsNone(self.chat.research_provider._host_binding.get())
        self.assertEqual(self.chat.research_provider._bindings,{})

    def test_next_ordinary_turn_has_no_course_body_or_old_answer(self):
        _,_,materials=self.seed();self.http.text='COURSE_SECRET_answer'
        self.send(materials)
        self.events.clear();self.http.text='合成普通回答'
        self.chat.reply_request('今天怎么样',request_id=uid())
        self.fixture.assert_no_course()

    def test_course_words_in_ordinary_input_are_not_a_grant(self):
        self.seed();self.events.clear()
        self.chat.reply_request('我今天研究了课程和线性代数',request_id=uid())
        self.fixture.assert_no_course()

    def test_old_study_request_id_cannot_be_reused_via_ordinary_endpoint(self):
        _,_,materials=self.seed();rid=uid();text='解释这份资料'
        self.send(materials,text,request_id=rid)
        self.events.clear();count=len(self.http.requests)
        with self.assertRaises(ChatStateError):self.chat.reply_request(text,request_id=rid)
        self.assertEqual(len(self.http.requests),count)
        self.assertFalse(self.fixture.body_queries())

    def test_same_explicit_retry_can_use_valid_cache(self):
        _,_,materials=self.seed();rid=uid();text='解释这份资料'
        self.send(materials,text,request_id=rid);count=len(self.http.requests)
        result=self.send(materials,text,request_id=rid)
        self.assertEqual(result['research_use'],{'status':'cached','used':1})
        self.assertEqual(len(self.http.requests),count)

    def test_changed_text_with_same_request_is_refused(self):
        _,_,materials=self.seed();rid=uid()
        self.send(materials,request_id=rid)
        with self.assertRaises(ChatStateError):self.send(materials,'另一个问题',request_id=rid)

    def test_non_course_selection_rejected_before_body_and_model(self):
        _,_,materials=self.seed(course=False)
        self.events.clear()
        with self.assertRaises(ValueError):self.send(materials)
        self.assertFalse(self.fixture.body_queries());self.assertFalse(self.http.requests)

    def test_unknown_or_stale_selection_fails_before_body(self):
        _,_,materials=self.seed();materials[0]['revision']=uid()
        self.events.clear()
        with self.assertRaises(ValueError):self.send(materials)
        self.assertFalse(self.fixture.body_queries());self.assertFalse(self.http.requests)

    def test_withdrawn_source_cannot_enter_request(self):
        source,_,materials=self.seed()
        self.chat.store.catalog.change_source(*source,state='withdrawn')
        self.events.clear()
        with self.assertRaises(ValueError):self.send(materials)
        self.assertFalse(self.fixture.body_queries());self.assertFalse(self.http.requests)

    def test_course_ids_and_grants_in_material_object_rejected(self):
        _,_,materials=self.seed()
        for field in ('courses','study','trust','grant','purpose'):
            changed=deepcopy(materials);changed[0][field]=True
            with self.assertRaises(ValueError):self.send(changed)
        self.assertFalse(self.http.requests)

    def test_duplicate_and_oversized_selection_rejected(self):
        _,_,materials=self.seed()
        for selection in ([],materials*2,materials*9):
            with self.assertRaises(ValueError):self.send(selection)
        self.assertFalse(self.http.requests)

    def test_refusal_retains_current_text_and_never_queries_research(self):
        _,_,materials=self.seed();self.events.clear()
        result=self.send(materials,'不要读取课程资料，只根据我这句话回答：一加一')
        self.fixture.assert_no_course()
        self.assertEqual(result['research_use']['used'],0)
        self.assertFalse(any('rc_entries' in q or 'rc_bodies' in q for q in self.events))

    def test_budget_omission_before_body_is_visible(self):
        _,_,materials=self.seed(text='COURSE_SECRET_'+('甲'*6500))
        self.events.clear()
        result=self.send(materials)
        self.fixture.assert_no_course()
        self.assertEqual(result['research_use'],{'status':'budget_omitted_before_body','used':0})

    def test_scope_reset_even_when_model_fails(self):
        _,_,materials=self.seed()
        self.http.callback=lambda:(_ for _ in ()).throw(RuntimeError('synthetic failure'))
        with self.assertRaises(ValueError):self.send(materials)
        self.assertIsNone(self.chat.research_provider._host_binding.get())
        self.http.callback=None;self.events.clear()
        self.chat.reply_request('普通问题',request_id=uid())
        self.fixture.assert_no_course()

    def test_context_local_selection_cannot_leak_to_other_thread(self):
        _,entry,_=self.seed();provider=self.chat.research_provider;rid=uid();sid=self.chat.store.session_id
        states=[]
        def ordinary():
            with provider.request_scope('普通问题',uid(),sid,'user'):
                state=self.chat.store.scope.get();states.append((state.refs,state.access.scene))
        with provider.host_selection('讲解',rid,sid,[entry],ResearchAccess('study',(self.fixture.course,))):
            thread=threading.Thread(target=ordinary);thread.start();thread.join(2)
        self.assertEqual(states,[((),'casual')])

    def test_host_scope_is_bound_to_exact_text_session_and_request(self):
        _,entry,_=self.seed();provider=self.chat.research_provider;rid=uid();sid=self.chat.store.session_id
        with provider.host_selection('讲解',rid,sid,[entry],ResearchAccess('study',(self.fixture.course,))):
            for text,request,session in [('变更',rid,sid),('讲解',uid(),sid),('讲解',rid,uid())]:
                with self.assertRaises(ResearchError):
                    with provider.request_scope(text,request,session,'user'):pass

    def test_source_changed_during_generation_discards_answer(self):
        source,_,materials=self.seed()
        self.http.callback=lambda:self.chat.store.catalog.change_source(*source,source_text='revised')
        rid=uid()
        with self.assertRaises(ChatStateError):self.send(materials,request_id=rid)
        self.assertIsNone(self.fixture.exposures(rid))

    def test_session_switch_during_generation_discards_answer(self):
        _,_,materials=self.seed()
        self.http.callback=lambda:self.chat.select_session()
        rid=uid()
        with self.assertRaises(ChatStateError):self.send(materials,request_id=rid)
        self.assertIsNone(self.fixture.exposures(rid))

    def test_ordinary_history_filters_research_metadata_before_pagination_and_body(self):
        self.chat.reply_request('普通旧对话',request_id=uid())
        _,_,materials=self.seed();self.http.text='COURSE_SECRET_answer';self.send(materials)
        self.events.clear()
        history=MemoryArchive(self.chat).history()
        self.assertEqual(len(history['turns']),1)
        self.assertEqual(history['turns'][0]['input'],'普通旧对话')
        self.assertNotIn('COURSE_SECRET',json.dumps(history))
        self.assertFalse(any('COURSE_SECRET' in q for q in self.events))
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lc_turns WHERE status='complete'").fetchone()[0],2)

    def test_disabled_default_never_initializes_research(self):
        normal=fixtures.create_desktop_chat(self.fixture.root/'normal/chat.json',keys=fixtures.Keys(),opener=self.http)
        service=StudyChat(normal)
        self.assertFalse(service.status()['available'])
        with self.assertRaises(ValueError):service.reply('test',uid(),[{'id':uid(),'revision':uid()}])
        with normal.store.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'rc_%'").fetchone()[0],0)


if __name__=='__main__':unittest.main()
