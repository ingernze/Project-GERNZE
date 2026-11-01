"""Scoped summary provenance with real SQLite/context and synthetic workers."""
from contextlib import contextmanager
import json
import sqlite3
import unittest
import uuid

from workbench.context_manager import ContextManager
from workbench.conversation_store import ChatStateError, ConversationStore
from workbench.research_catalog import ResearchAccess, ResearchError
from workbench.research_context import ResearchJournal
from workbench.research_summaries import reference
import research_context_test as fixtures


class Worker:
    def __init__(self):self.calls=[];self.callback=None;self.text='COURSE_SECRET_summary'
    def __call__(self, request, **kwargs):
        self.calls.append(request)
        if self.callback:self.callback()
        return {'text':self.text,'source_turn_ids':list(request['source_turn_ids'])}


class ResearchSummaryTests(unittest.TestCase):
    captures=[]
    def setUp(self):
        self.fixture=fixtures.ResearchWiringTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.chat=self.fixture.chat;self.store=self.chat.store;self.events=self.fixture.events;self.http=self.fixture.http
        self.worker=Worker();self.manager=ContextManager(summarizer=self.worker,keep_recent=1,batch_size=3,min_batch=3,summary_timeout=1)
        self.chat.layers.configure({'summaryEnabled':True,'summaryDays':1,'reviewDays':None})
        with self.store.connection() as db:
            db.execute("UPDATE lc_sessions SET created_at='2000-01-01T00:00:00+00:00'")
        self.source,self.entry=self.fixture.seed()
        self.turns=[]

    def tearDown(self):
        self.captures.append({'case':self.id(),'sql':self.events[:],'summaryRequests':self.worker.calls,'chatPayloads':self.http.requests})

    @contextmanager
    def scope(self, *, study=True, course=None, refs=None):
        access=ResearchAccess('study',(course or self.fixture.course,)) if study else ResearchAccess()
        rid=str(uuid.uuid4())
        self.chat.research_provider.bind(rid,self.store.session_id,refs if refs is not None else [self.entry] if study else [],access=access)
        with self.chat.research_provider.request_scope('合成摘要触发',rid,self.store.session_id,'user'):
            yield rid

    def seed_turns(self,n=7,*,study=True):
        for i in range(n):
            rid=self.fixture.bind(self.entry,access=ResearchAccess('study',(self.fixture.course,)) if study else ResearchAccess())
            self.http.text='COURSE_SECRET_answer' if study else 'GENERAL_RESEARCH_answer'
            self.turns.append(self.chat.reply_request('合成研究轮'+str(len(self.turns)),request_id=rid)['request_id'])

    def summarize(self,**kwargs):
        with self.scope(**kwargs):return self.manager.summarize(self.store,self.store.session_id)

    def summary_rows(self):
        with self.store.read_connection() as db:return [dict(r) for r in db.execute('SELECT * FROM rc_summary_meta ORDER BY version')]

    def test_course_delta_commits_body_manifest_and_coverage_atomically(self):
        self.seed_turns();self.events.clear()
        self.assertEqual(self.summarize(),'committed')
        row=self.summary_rows()[0]
        self.assertEqual(len(json.loads(row['raw_refs'])),3)
        self.assertEqual(json.loads(row['manifest'])[0]['id'],self.entry[0])
        self.assertEqual(self.worker.calls[0]['existing_summaries'],[])
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_summary_coverage').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_summaries').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT SUM(covered) FROM lc_turns').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_messages').fetchone()[0],14)

    def test_ordinary_summary_does_not_read_course_pairs_or_summary_body(self):
        self.seed_turns();self.assertEqual(self.summarize(),'committed');self.events.clear();count=len(self.worker.calls)
        self.assertEqual(self.summarize(study=False),'not_due')
        with self.scope(study=False):self.assertEqual(self.store.research_summaries.metadata(self.store.session_id),[])
        self.assertEqual(len(self.worker.calls),count)
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') for q in self.events))
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_wrong_course_metadata_blocks_before_summary_body(self):
        self.seed_turns();self.summarize();self.events.clear()
        with self.scope(course=str(uuid.uuid4()),refs=[]):
            self.assertEqual(self.store.research_summaries.metadata(self.store.session_id),[])
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_summary_enters_actual_study_payload_and_answer_links_same_commit(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager
        rid=self.fixture.bind(self.entry)
        self.chat.reply_request('请继续说明资料',request_id=rid)
        self.assertIn('COURSE_SECRET_summary',json.dumps(self.http.requests[-1]))
        with self.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_turn_summary_links WHERE turn_id=?',(rid,)).fetchone()[0],1)
        self.assertTrue(self.fixture.exposures(rid))

    def test_ordinary_request_after_summary_omits_course_body_and_history(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager;self.events.clear();self.http.text='普通回答'
        self.chat.reply_request('今天好吗',request_id=str(uuid.uuid4()))
        self.fixture.assert_no_course()
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_source_revision_change_blocks_existing_summary_before_body(self):
        self.seed_turns();self.summarize();self.store.catalog.change_source(*self.source,source_text='changed');self.events.clear()
        with self.scope():self.assertEqual(self.store.research_summaries.metadata(self.store.session_id),[])
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_source_changes_while_worker_runs_discards_whole_delta(self):
        self.seed_turns();self.worker.callback=lambda:self.store.catalog.change_source(*self.source,source_text='changed')
        self.assertEqual(self.summarize(),'stale');self.assertEqual(self.summary_rows(),[])
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_summary_coverage').fetchone()[0],0)

    def test_raw_removal_while_worker_runs_discards_delta(self):
        self.seed_turns()
        with self.store.read_connection() as db:message=db.execute('SELECT user_id FROM lc_turns WHERE id=?',(self.turns[0],)).fetchone()[0]
        self.worker.callback=lambda:self.store.remove_source(message)
        self.assertEqual(self.summarize(),'stale');self.assertEqual(self.summary_rows(),[])

    def test_failed_body_insert_rolls_back_metadata_and_coverage(self):
        self.seed_turns()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_summary BEFORE INSERT ON rc_summary_bodies BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        self.assertEqual(self.summarize(),'storage_failed');self.assertEqual(self.summary_rows(),[])
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_summary_coverage').fetchone()[0],0)

    def test_invalid_model_sources_cannot_write_summary(self):
        self.seed_turns()
        self.manager.summarizer=lambda request,**kwargs:{'text':'bad','source_turn_ids':[str(uuid.uuid4())]}
        self.assertEqual(self.summarize(),'invalid_output');self.assertEqual(self.summary_rows(),[])

    def test_course_summary_never_enters_legacy_summary_commit(self):
        self.seed_turns();self.summarize()
        view=self.store.summary_view(self.store.session_id,keep_recent=1)
        self.assertFalse(self.store.commit_summary(self.store.session_id,view,[{'id':self.turns[0]}],'course leakage'))
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)

    def test_plain_summaries_keep_priority_and_one_worker_per_request(self):
        self.seed_turns()
        for i in range(5):self.chat.reply_request('普通对话'+str(i),request_id=str(uuid.uuid4()))
        with self.scope(study=False):result=self.manager.summarize(self.store,self.store.session_id)
        self.assertEqual(result,'committed');self.assertEqual(len(self.worker.calls),1)
        self.assertEqual(self.summary_rows(),[])
        with self.store.read_connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],1)

    def test_cancellation_cannot_commit_delta(self):
        self.seed_turns();self.worker.callback=lambda:self.manager.cancel()
        self.assertEqual(self.summarize(),'cancelled');self.assertEqual(self.summary_rows(),[])

    def test_source_current_content_change_during_capture_is_rejected(self):
        self.seed_turns()
        def mutate():
            with self.store.connection() as db:db.execute("UPDATE lc_messages SET content='changed raw' WHERE turn_id=? AND role='assistant'",(self.turns[0],))
        self.worker.callback=mutate
        self.assertEqual(self.summarize(),'stale');self.assertEqual(self.summary_rows(),[])

    def test_same_batch_cannot_be_committed_twice(self):
        self.seed_turns()
        with self.scope():
            proxy=self.store.scoped_summary_store(1,3);view=proxy.summary_view(self.store.session_id)
            self.assertTrue(proxy.commit_summary(self.store.session_id,view,view['new_turns'],'delta'))
            self.assertFalse(proxy.commit_summary(self.store.session_id,view,view['new_turns'],'duplicate'))
        self.assertEqual(len(self.summary_rows()),1)

    def test_reopen_preserves_scoped_summary_and_old_reader_refuses_version3(self):
        self.seed_turns();self.summarize();path=self.store.path
        with self.assertRaises(ValueError):ConversationStore(path)
        reopened=ResearchJournal(path)
        self.addCleanup(lambda:None)
        with reopened.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_summary_meta').fetchone()[0],1)
        self.assertEqual(reopened.research_summaries.metadata(reopened.session_id),[])

    def test_summary_body_corruption_is_not_returned(self):
        self.seed_turns();self.summarize();row=self.summary_rows()[0]
        with self.store.connection() as db:db.execute("UPDATE rc_summary_bodies SET body='corrupt' WHERE id=?",(row['id'],))
        with self.scope():
            with self.assertRaises(ResearchError):self.store.research_summaries.read(reference(row))

    def test_budget_omits_scoped_summary_before_body_query(self):
        self.seed_turns();self.worker.text='字'*450;self.manager.summary_output_limit=1500
        self.assertEqual(self.summarize(),'committed');self.chat.context=self.manager
        # A current material may fit while the summary's safe escaped bound does not.
        self.events.clear();rid=self.fixture.bind(self.entry)
        self.chat.reply_request('请简要讲解',request_id=rid)
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))
        self.assertTrue(any(x.startswith('research_summary:') for x in self.chat.last_context['omitted']))

    def test_general_research_summary_usable_in_casual_scope(self):
        self.source,self.entry=self.fixture.seed(course=False,text='GENERAL_RESEARCH_source')
        self.worker.text='GENERAL_RESEARCH_summary';self.seed_turns(study=False)
        self.assertEqual(self.summarize(study=False),'committed')
        with self.scope(study=False):
            rows=self.store.research_summaries.metadata(self.store.session_id)
            self.assertEqual(len(rows),1)
            self.assertEqual(self.store.research_summaries.read(reference(rows[0]))['text'],'GENERAL_RESEARCH_summary')

    def test_two_generations_preserve_ancestral_sources_and_parent_version(self):
        self.seed_turns(n=4);self.assertEqual(self.summarize(),'committed');self.chat.context=self.manager
        first=self.summary_rows()[0]
        for i in range(4):
            rid=self.fixture.bind(self.entry)
            self.chat.reply_request('延续研究'+str(i),request_id=rid)
        with self.store.connection() as db:db.execute("UPDATE rc_summary_attempt SET clock='2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.summarize(),'committed')
        second=self.summary_rows()[1]
        self.assertIn(first['id'],[r['id'] for r in json.loads(second['parents'])])
        self.assertTrue(set(json.loads(first['raw_refs']))<set(json.loads(second['raw_refs'])))
        with self.store.connection() as db:db.execute('UPDATE rc_summary_meta SET revision=? WHERE id=?',(str(uuid.uuid4()),first['id']))
        self.events.clear()
        with self.scope():
            with self.assertRaises(ResearchError):self.store.research_summaries.read(reference(second))
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_answer_and_summary_links_roll_back_together(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_links BEFORE INSERT ON rc_turn_summary_links BEGIN SELECT RAISE(ABORT,'synthetic link failure'); END")
        rid=self.fixture.bind(self.entry)
        with self.assertRaises(sqlite3.IntegrityError):self.chat.reply_request('使用摘要',request_id=rid)
        with self.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lc_messages WHERE turn_id=? AND role='assistant'",(rid,)).fetchone()[0],0)
            self.assertIsNone(db.execute('SELECT 1 FROM rc_exposures WHERE turn_id=?',(rid,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM rc_turn_summary_links WHERE turn_id=?',(rid,)).fetchone())

    def test_turn_cannot_replay_cached_answer_after_summary_version_change(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager
        rid=self.fixture.bind(self.entry);self.chat.reply_request('合成缓存问题',request_id=rid)
        row=self.summary_rows()[0]
        with self.store.connection() as db:db.execute('UPDATE rc_summary_meta SET revision=? WHERE id=?',(str(uuid.uuid4()),row['id']))
        count=len(self.http.requests)
        with self.assertRaises(ChatStateError):self.chat.reply_request('合成缓存问题',request_id=rid)
        self.assertEqual(len(self.http.requests),count)

    def test_summary_preference_off_prevents_worker_and_body_reads(self):
        self.seed_turns();self.chat.layers.configure({'summaryEnabled':False,'summaryDays':1,'reviewDays':None});self.events.clear()
        self.assertEqual(self.summarize(),'disabled')
        self.assertEqual(self.worker.calls,[])
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') for q in self.events))

    def test_explicit_refusal_skips_both_raw_and_scoped_summary(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager;self.events.clear()
        rid=self.fixture.bind(self.entry)
        self.chat.reply_request('不要读取课程资料，只根据我这句话回答：你好',request_id=rid)
        self.fixture.assert_no_course()
        self.assertFalse(any(q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))

    def test_legacy_commit_rejects_scope_bearing_turn_after_scoped_summary_created(self):
        self.seed_turns();self.summarize();self.chat.context=self.manager
        rid=self.fixture.bind(self.entry);self.chat.reply_request('继续合成问题',request_id=rid)
        view=self.store.summary_view(self.store.session_id,keep_recent=1)
        self.assertFalse(self.store.commit_summary(self.store.session_id,view,[{'id':rid}],'unscoped'))

    def test_not_due_general_group_cannot_starve_due_course_group(self):
        self.source,self.entry=self.fixture.seed(course=False,text='GENERAL_RESEARCH_source')
        self.worker.text='GENERAL_RESEARCH_summary';self.seed_turns(n=4,study=False)
        self.assertEqual(self.summarize(study=False),'committed')
        self.seed_turns(n=3,study=False)
        self.source,self.entry=self.fixture.seed();self.seed_turns(n=4)
        self.worker.text='COURSE_SECRET_summary'
        self.assertEqual(self.summarize(),'committed')
        rows=self.summary_rows();self.assertEqual(len(rows),2)
        self.assertEqual(json.loads(rows[-1]['group_key'])['scene'],'study')

    def test_small_due_general_group_cannot_starve_full_course_batch(self):
        self.source,self.entry=self.fixture.seed(course=False,text='GENERAL_RESEARCH_source')
        self.worker.text='GENERAL_RESEARCH_summary';self.seed_turns(n=4,study=False)
        self.assertEqual(self.summarize(study=False),'committed')
        with self.store.connection() as db:db.execute("UPDATE rc_summary_attempt SET clock='2000-01-01T00:00:00+00:00'")
        self.source,self.entry=self.fixture.seed();self.seed_turns(n=4)
        self.assertEqual(self.summarize(),'committed')
        self.assertEqual(json.loads(self.summary_rows()[-1]['group_key'])['scene'],'study')

    def test_disabling_runtime_blocks_summary_before_raw_or_summary_body(self):
        self.seed_turns();self.events.clear()
        with self.scope():
            self.chat.research_provider.disable()
            with self.assertRaises(ResearchError):self.manager.summarize(self.store,self.store.session_id)
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') or q.startswith('SELECT body FROM rc_summary_bodies') for q in self.events))
        self.assertEqual(self.worker.calls,[])

    def test_unknown_summary_schema_is_not_silently_accepted(self):
        from workbench.research_summaries import ResearchSummaries
        with self.store.connection() as db:db.execute("UPDATE rc_meta SET value='999' WHERE key='summary_schema'")
        with self.assertRaisesRegex(ResearchError,'unsupported_summary_schema'):
            with self.store.connection() as db:ResearchSummaries.initialize(db)


if __name__=='__main__':unittest.main()
