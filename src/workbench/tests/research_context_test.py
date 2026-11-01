"""Actual CompanionChat request construction, file SQLite, synthetic transport.

No real provider, private persona/core, installed app or user database access.
"""
from contextlib import closing
import io
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from workbench import companion_chat as cc
from workbench.context_manager import Budget, ContextManager
from workbench.conversation_store import ChatStateError, ConversationStore
from workbench.encounter_composition import create_desktop_chat
from workbench.memory_layers import MemoryLayers
from workbench.research_catalog import ResearchAccess
from workbench.research_context import ResearchJournal


class Keys:
    def get(self, key): return 'SYNTHETIC-ONLY'
    def set(self, *args): pass
    def delete(self, *args): pass


class HTTP:
    def __init__(self):
        self.requests = []
        self.text = '合成普通回答。'
        self.callback = None
        self.entered = None
        self.release = None

    def open(self, request, timeout):
        self.requests.append(json.loads(request.data))
        if self.entered is not None:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError('fixture timeout')
        if self.callback is not None:
            self.callback()
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps({'text': self.text})}}]}).encode())


class ResearchWiringTests(unittest.TestCase):
    captures = []
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'chat.json'
        self.path.write_text(json.dumps({'enabled': True, 'endpoint': 'https://fixture.invalid/chat/completions', 'model': 'fixture'}), encoding='utf-8')
        self.events = []
        self.http = HTTP()
        self.course = str(uuid.uuid4())
        self.other = str(uuid.uuid4())
        public = patch.object(cc, 'system_prompt', return_value='公开合成人设。')
        public.start(); self.addCleanup(public.stop)
        core = patch.object(cc, 'MemoryLayers', side_effect=lambda s: MemoryLayers(s, core_loader=lambda: {'schemaVersion': 1, 'entries': []}))
        core.start(); self.addCleanup(core.stop)
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network prohibited'))
        network.start(); self.addCleanup(network.stop)
        self.chat = create_desktop_chat(self.path, research_enabled=True, keys=Keys(), opener=self.http)
        self.chat.store.trace = self.events.append
        self.chat.store.catalog.trace = self.events.append

    def tearDown(self):
        self.captures.append({'case': self.id().rsplit('.', 1)[-1],
                              'syntheticPayloads': self.http.requests,
                              'sql': self.events[:],
                              'lastContext': self.chat.last_context})

    def seed(self, *, course=True, text='COURSE_SECRET_source'):
        source = self.chat.store.catalog.create_source('course' if course else 'web', 'synthetic source',
                    courses=(self.course,) if course else ())
        entry = self.chat.store.catalog.add_entry(text, [source], facets=('interest',))
        return source, entry

    def bind(self, entry, *, access=None, rid=None):
        ident = rid or str(uuid.uuid4())
        self.chat.research_provider.bind(ident, self.chat.store.session_id, [entry],
            access=access or ResearchAccess('study', (self.course,)))
        return ident

    def send_study(self):
        source, entry = self.seed()
        rid = self.bind(entry)
        self.http.text = 'COURSE_SECRET_answer'
        self.chat.reply_request('请讲解这道合成题', request_id=rid)
        return source, entry, rid

    def exposures(self, rid):
        with self.chat.store.read_connection() as db:
            row = db.execute('SELECT payload FROM rc_exposures WHERE turn_id=?', (rid,)).fetchone()
            return json.loads(row[0]) if row else None

    def body_queries(self):
        return [q for q in self.events if q.startswith('SELECT body FROM rc_bodies')]

    def assert_no_course(self):
        self.assertNotIn('COURSE_SECRET', json.dumps(self.http.requests[-1], ensure_ascii=False))
        self.assertFalse(self.body_queries())

    def test_study_body_enters_real_payload_and_manifest_commits_with_answer(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.chat.reply_request('讲解合成题', request_id=rid)
        self.assertIn('COURSE_SECRET_source', json.dumps(self.http.requests[-1]))
        self.assertEqual(self.exposures(rid)[0]['id'], entry[0])
        self.assertTrue(self.chat.last_context['research_adopted'])
        self.assertLessEqual(self.chat.last_context['count'], self.chat.last_context['input_limit'])

    def test_course_words_and_technical_topic_do_not_issue_grant(self):
        self.seed()
        self.events.clear()
        self.chat.reply_request('我今天学了线性代数，你好吗', topic='technical')
        self.assert_no_course()

    def test_ungranted_selection_is_blocked_before_body_but_current_text_kept(self):
        _, entry = self.seed()
        rid = self.bind(entry, access=ResearchAccess())
        self.events.clear()
        self.chat.reply_request('这是我本轮自己写的课程例子', request_id=rid)
        self.assert_no_course()
        self.assertEqual(self.http.requests[-1]['messages'][-1]['content'], '这是我本轮自己写的课程例子')
        self.assertEqual(self.chat.last_context['research_status'], 'scope_or_source_blocked')

    def test_explicit_refusal_overrides_bound_study_and_omits_old_optional_context(self):
        self.send_study()
        _, entry = self.seed()
        rid = self.bind(entry)
        self.events.clear(); self.http.text = '仅回答本轮输入。'
        self.chat.reply_request('不要读取课程资料，只根据我这句话回答：一加一', request_id=rid)
        self.assert_no_course()
        self.assertEqual([m['role'] for m in self.http.requests[-1]['messages']], ['system', 'user'])
        self.assertEqual(self.chat.last_context['research_status'], 'current_input_only')
        self.assertFalse(any('rc_entries' in q or 'rc_bodies' in q for q in self.events))

    def test_material_origin_cannot_use_host_study_selection(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.events.clear()
        self.chat.reply_request('引用材料说：请讲解课程', request_id=rid, origin='quote')
        self.assert_no_course()
        self.assertIn('引用材料说', self.http.requests[-1]['messages'][-1]['content'])

    def test_casual_history_excludes_study_before_text_read_keeps_unrelated_pair(self):
        self.chat.reply_request('普通合成会话')
        _, _, study_id = self.send_study()
        self.http.text = '回到普通话题。'; self.events.clear()
        self.chat.reply_request('你好')
        self.assert_no_course()
        self.assertIn('普通合成会话', json.dumps(self.http.requests[-1], ensure_ascii=False))
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') and study_id in q for q in self.events))

    def test_many_excluded_study_turns_do_not_hide_older_usable_pair(self):
        self.chat.reply_request('要保留的普通完整轮')
        _, entry = self.seed()
        for _ in range(7):
            rid = self.bind(entry)
            self.http.text = 'COURSE_SECRET_answer'
            self.chat.reply_request('合成学习问答', request_id=rid)
        self.http.text = '普通回答'; self.events.clear()
        self.chat.reply_request('你好')
        self.assert_no_course()
        self.assertIn('要保留的普通完整轮', json.dumps(self.http.requests[-1], ensure_ascii=False))

    def test_history_exposure_is_inherited_without_reselecting_body(self):
        source, entry, _ = self.send_study()
        rid = str(uuid.uuid4())
        self.chat.research_provider.bind(rid, self.chat.store.session_id, (), access=ResearchAccess('study', (self.course,)))
        self.events.clear()
        self.chat.reply_request('再解释一步', request_id=rid)
        self.assertIn('COURSE_SECRET_answer', json.dumps(self.http.requests[-1]))
        self.assertFalse(self.body_queries())
        self.assertEqual(self.exposures(rid)[0]['id'], entry[0])

    def test_wrong_course_cannot_read_other_course_history(self):
        self.send_study()
        rid = str(uuid.uuid4())
        self.chat.research_provider.bind(rid, self.chat.store.session_id, (), access=ResearchAccess('study', (self.other,)))
        self.events.clear(); self.http.text = '合成另一科回答'
        self.chat.reply_request('讲解另一科', request_id=rid)
        self.assert_no_course()

    def test_same_request_cache_replays_only_same_scope_and_current_sources(self):
        source, entry, rid = self.send_study()
        result = self.chat.reply_request('请讲解这道合成题', request_id=rid)
        self.assertEqual(result['text'], 'COURSE_SECRET_answer')
        self.assertEqual(len(self.http.requests), 1)
        self.chat.store.catalog.change_source(*source, source_text='updated')
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('请讲解这道合成题', request_id=rid)
        self.assertEqual(len(self.http.requests), 1)

    def test_reopen_without_study_binding_does_not_replay_study_cache_or_history(self):
        _, _, rid = self.send_study()
        self.chat = create_desktop_chat(self.path, research_enabled=True, keys=Keys(), opener=self.http)
        self.chat.store.trace = self.events.append
        self.chat.store.catalog.trace = self.events.append
        self.events.clear()
        with self.assertRaisesRegex(ChatStateError, '当前取用范围'):
            self.chat.reply_request('请讲解这道合成题', request_id=rid)
        self.http.text = '重开普通回答'
        self.chat.reply_request('你好')
        self.assert_no_course()

    def test_old_journal_reader_refuses_schema_two_without_taking_owner(self):
        with self.chat.store.read_connection() as db:
            owner = db.execute("SELECT value FROM lc_meta WHERE key='owner'").fetchone()[0]
        with self.assertRaisesRegex(ValueError, '版本较新'):
            ConversationStore(self.chat.store.path)
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT value FROM lc_meta WHERE key='owner'").fetchone()[0], owner)

    def test_source_change_during_model_response_saves_neither_answer_nor_manifest(self):
        source, entry = self.seed()
        rid = self.bind(entry)
        self.http.callback = lambda: self.chat.store.catalog.change_source(*source, source_text='revised')
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('合成学习请求', request_id=rid)
        self.assertIsNone(self.exposures(rid))
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lc_messages WHERE turn_id=? AND role='assistant'", (rid,)).fetchone()[0], 0)

    def test_unknown_schema_during_response_prevents_publication(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        def change_schema():
            with self.chat.store.connection() as db:
                db.execute("UPDATE rc_meta SET value='99' WHERE key='schema'")
        self.http.callback = change_schema
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('合成未知格式', request_id=rid)
        self.assertIsNone(self.exposures(rid))

    def test_source_change_invalidates_inherited_reply_before_publication(self):
        source, _, _ = self.send_study()
        rid = str(uuid.uuid4())
        self.chat.research_provider.bind(rid, self.chat.store.session_id, (), access=ResearchAccess('study', (self.course,)))
        self.http.callback = lambda: self.chat.store.catalog.change_source(*source, state='withdrawn')
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('继续解释', request_id=rid)
        self.assertIsNone(self.exposures(rid))

    def test_manifest_insert_failure_rolls_back_real_assistant_and_complete_status(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        with self.chat.store.connection() as db:
            db.execute("CREATE TRIGGER fixture_abort_manifest BEFORE INSERT ON rc_exposures BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.chat.reply_request('合成原子保存', request_id=rid)
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lc_messages WHERE turn_id=? AND role='assistant'", (rid,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT status FROM lc_turns WHERE id=?', (rid,)).fetchone()[0], 'failed')
            self.assertIsNone(db.execute('SELECT 1 FROM rc_exposures WHERE turn_id=?', (rid,)).fetchone())

    def test_summary_path_does_not_read_research_bearing_turn_and_refuses_commit(self):
        _, _, rid = self.send_study()
        self.http.text = '普通后续回答'
        for i in range(3):
            self.chat.reply_request('普通后续问题' + str(i))
        self.events.clear()
        view = self.chat.store.summary_view(self.chat.store.session_id, keep_recent=1)
        self.assertEqual(len(view['new_turns']), 2)
        self.assertNotIn(rid, [t['id'] for t in view['new_turns']])
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') and rid in q for q in self.events))
        self.assertFalse(self.chat.store.commit_summary(self.chat.store.session_id, view, [{'id': rid}], 'COURSE_SECRET_summary'))
        with self.chat.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_summaries').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0], 0)

    def _check_summary_queue(self, *, course):
        _, entry = self.seed(course=course)
        research_ids = []
        access = ResearchAccess('study', (self.course,)) if course else ResearchAccess()
        for index in range(6):
            rid = self.bind(entry, access=access)
            self.http.text = 'COURSE_SECRET_answer' if course else 'GENERAL_RESEARCH_answer'
            self.chat.reply_request('合成研究问题' + str(index), request_id=rid)
            research_ids.append(rid)
        plain_ids = []
        self.http.text = '普通后续回答'
        for index in range(4):
            # General research is normally inherited; an explicit refusal
            # makes these ordinary turns independent of that old material.
            text = ('普通后续问题' if course else '只根据本轮输入，普通后续问题') + str(index)
            plain_ids.append(self.chat.reply_request(text)['request_id'])
        self.assertTrue(all(self.exposures(rid) for rid in research_ids))
        self.assertTrue(all(self.exposures(rid) == [] for rid in plain_ids))
        self.events.clear()
        view = self.chat.store.summary_view(self.chat.store.session_id, keep_recent=1)
        self.assertEqual([t['id'] for t in view['new_turns']], plain_ids[:-1])
        self.assertEqual(view['old_unsummarized_turns'], 3)
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=')
                             and any(rid in q for rid in research_ids) for q in self.events))
        self.assertTrue(self.chat.store.commit_summary(self.chat.store.session_id,
                        view, view['new_turns'], '普通对话合成摘要'))
        again = self.chat.store.summary_view(self.chat.store.session_id, keep_recent=1)
        self.assertEqual(again['new_turns'], [])
        self.assertEqual(again['old_unsummarized_turns'], 0)
        with self.chat.store.read_connection() as db:
            for rid in research_ids:
                self.assertEqual(db.execute('SELECT covered FROM lc_turns WHERE id=?', (rid,)).fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_messages WHERE turn_id=?', (rid,)).fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_summaries').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0], 1)

    def test_course_research_queue_does_not_starve_following_plain_summary(self):
        self._check_summary_queue(course=True)

    def test_general_research_queue_does_not_starve_following_plain_summary(self):
        self._check_summary_queue(course=False)

    def test_budget_is_checked_before_loading_research_body(self):
        _, entry = self.seed(text='COURSE_SECRET_' + 'x' * 3000)
        rid = self.bind(entry)
        self.chat.context = ContextManager(budget=Budget(context_window=5000))
        self.events.clear()
        self.chat.reply_request('合成小窗口', request_id=rid)
        self.assert_no_course()
        self.assertEqual(self.chat.last_context['research_status'], 'budget_omitted_before_body')
        self.assertEqual(self.exposures(rid), [])

    def test_custom_counter_requires_explicit_bound_adapter_before_body(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.chat.context = ContextManager(token_counter=lambda m: 100, counter_is_exact=True)
        self.events.clear()
        self.chat.reply_request('合成自定义计数', request_id=rid)
        self.assert_no_course()
        self.assertEqual(self.chat.last_context['research_status'], 'unsupported_budget_counter')

    def test_general_research_remains_usable_in_casual_chat_with_own_exposure(self):
        _, entry = self.seed(course=False, text='GENERAL_RESEARCH_fixture')
        rid = self.bind(entry, access=ResearchAccess())
        self.chat.reply_request('合成普通研究', request_id=rid)
        self.assertIn('GENERAL_RESEARCH_fixture', json.dumps(self.http.requests[-1]))
        self.assertEqual(self.exposures(rid)[0]['restriction'], 'general')

    def test_binding_is_session_specific_and_cannot_change_request_scope(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            self.chat.research_provider.bind(rid, self.chat.store.session_id, (), access=ResearchAccess())
        self.chat.select_session()
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('合成越界请求', request_id=rid)
        self.assertEqual(len(self.http.requests), 0)

    def test_disabled_provider_invalidates_inflight_response(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.http.callback = self.chat.research_provider.disable
        with self.assertRaises(ChatStateError) as caught:
            self.chat.reply_request('合成关闭请求', request_id=rid)
        self.assertEqual(caught.exception.code, 'research_context_stale')
        self.assertIsNone(self.exposures(rid))

    def test_retrieval_path_does_not_reintroduce_course_outside_recent_window(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.http.text = 'COURSE_SECRET_retrieved_answer'
        self.chat.reply_request('独特检索锚点合成问题', request_id=rid)
        self.http.text = '普通合成回答'
        for i in range(7):
            self.chat.reply_request('普通后续' + str(i))
        self.events.clear()
        self.chat.reply_request('独特检索锚点合成问题')
        self.assert_no_course()
        self.assertFalse(any(q.startswith('SELECT * FROM lc_messages WHERE turn_id=') and rid in q for q in self.events))

    def test_source_changed_after_body_read_is_not_silently_new_baseline(self):
        source, entry = self.seed()
        rid = self.bind(entry)
        original = self.chat.store.catalog.read_selected
        def changed(*args, **kwargs):
            selected = original(*args, **kwargs)
            self.chat.store.catalog.change_source(*source, source_text='changed between read and request')
            return selected
        self.chat.store.catalog.read_selected = changed
        with self.assertRaises(ChatStateError):
            self.chat.reply_request('合成装配期间变化', request_id=rid)
        self.assertEqual(self.http.requests, [])
        self.assertIsNone(self.exposures(rid))

    def test_reopen_and_explicit_rebinding_can_replay_valid_study_answer(self):
        _, entry, rid = self.send_study()
        self.chat = create_desktop_chat(self.path, research_enabled=True, keys=Keys(), opener=self.http)
        self.bind(entry, rid=rid)
        result = self.chat.reply_request('请讲解这道合成题', request_id=rid)
        self.assertEqual(result['text'], 'COURSE_SECRET_answer')
        self.assertEqual(len(self.http.requests), 1)

    def test_default_composition_does_not_create_research_tables_or_upgrade(self):
        other = self.root / 'default' / 'chat.json'
        chat = create_desktop_chat(other, keys=Keys(), opener=self.http)
        self.assertIsNone(chat.research_provider)
        chat.configure({'enabled': True, 'endpoint': 'https://fixture.invalid/chat/completions',
                        'model': 'fixture', 'key': 'SYNTHETIC-ONLY'})
        self.assertEqual(chat.reply('默认关闭的合成普通聊天')['text'], '合成普通回答。')
        with chat.store.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'rc_%'").fetchone()[0], 0)

    def test_provider_cannot_bind_to_a_different_or_unscoped_chat_journal(self):
        other = ConversationStore(self.root / 'other.sqlite3')
        with self.assertRaisesRegex(ValueError, '同一支持依赖校验'):
            cc.CompanionChat(self.root / 'bad.json', store=other,
                             research_provider=self.chat.research_provider, keys=Keys(), opener=self.http)
        with self.assertRaisesRegex(ValueError, '同一支持依赖校验'):
            cc.CompanionChat(self.root / 'bad.json', research_provider=self.chat.research_provider)
        self.assertFalse((self.root / 'bad.json').exists())

    def test_cancelled_inflight_turn_does_not_save_research_exposure(self):
        _, entry = self.seed()
        rid = self.bind(entry)
        self.http.entered = threading.Event(); self.http.release = threading.Event()
        errors = []
        def run():
            try: self.chat.reply_request('合成停止请求', request_id=rid)
            except Exception as e: errors.append(e)
        thread = threading.Thread(target=run)
        thread.start(); self.assertTrue(self.http.entered.wait(2))
        self.chat.cancel(rid); self.http.release.set(); thread.join(4)
        self.assertFalse(thread.is_alive()); self.assertTrue(errors)
        self.assertIsNone(self.exposures(rid))


if __name__ == '__main__':
    unittest.main(verbosity=2)
