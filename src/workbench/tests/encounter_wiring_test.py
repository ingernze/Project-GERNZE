"""Actual reply_request integration, concurrency barriers, and whole-message budgets."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'src'), str(Path(__file__).resolve().parent)]
from encounter_wiring_support import (CapturedHTTP, make_chat, seed, external_data, layer_snapshot,
                             turn_state, QUESTION, REMINDER)
from workbench.context_manager import Budget, ContextManager
from workbench.conversation_store import ChatStateError
from workbench.encounter_provider import LocalEncounterProvider
from libao_browse.encounters import EncounterStore


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        public = patch('workbench.companion_chat.system_prompt', return_value='公开合成人设。')
        public.start(); self.addCleanup(public.stop)
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('real network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_detailed_request_uses_same_reserve_with_external_block(self):
        chat = make_chat(self.root)
        seed(chat.encounter_provider.store)
        chat.reply_request('请详细分析旧标本和新观察有什么关系')
        payload = chat.http.requests[-1]
        self.assertEqual(payload['max_tokens'], 1800)
        self.assertEqual(chat.last_context['reply_reserve'], 1800)
        self.assertIsNotNone(external_data(payload))
        self.assertEqual(chat.last_context['count'], chat.context.count(payload['messages']))
        self.assertLessEqual(chat.last_context['count'] + 1800 + chat.last_context['margin'], chat.context.budget.context_window)

    def test_related_fields_selected_reopen_and_protocol(self):
        chat = make_chat(self.root)
        saved, body = seed(chat.encounter_provider.store)
        chat.encounter_provider.chat.select(saved['id'], saved['revision'], REMINDER)
        # Recreate provider and desktop objects against the same synthetic files.
        http = CapturedHTTP(content=json.dumps({'text': '合成结构回答', 'emotion': 'happy', 'action': 'sway'}))
        chat = make_chat(self.root, http=http)
        before = layer_snapshot(chat)
        answer = chat.reply_request(QUESTION)
        self.assertEqual((answer['emotion'], answer['action']), ('happy', 'sway'))
        data = external_data(http.requests[0])
        self.assertEqual(data['mode'], 'related')
        self.assertEqual(data['trust'], 'external_untrusted')
        self.assertIsNone(data['hostMemoryLayer'])
        item = data['items'][0]
        for field in ('facts', 'authorView', 'inference', 'previousJudgment',
                      'understandingRevision', 'nextResponse', 'missing', 'evidence', 'coverage'):
            self.assertTrue(item[field], field)
        self.assertIs(type(item['revision']), int)
        self.assertIs(type(item['understandingRevision']), str)
        self.assertEqual(data['selectedReflections'][0]['nextResponse'], REMINDER)
        self.assertEqual(before, layer_snapshot(chat))
        self.assertNotIn('memory_refs', answer)
        self.assertEqual(http.requests[0]['max_tokens'], 700)
        self.assertEqual(http.requests[0]['model'], 'deepseek-flash')

    def test_recent_intent_and_rewrite_are_not_confused(self):
        for index, text in enumerate(('最近看到了什么？', '你最近读到了什么？', '说说你最近的见闻',
                                      '把“最近看到了什么”改写成英文', '无关的量子计算问题')):
            with self.subTest(text=text):
                chat = make_chat(self.root / str(index))
                seed(chat.encounter_provider.store)
                chat.reply_request(text)
                data = external_data(chat.http.requests[0])
                if index < 3:
                    self.assertEqual(data['mode'], 'recent')
                    self.assertLessEqual(len(data['items']), 3)
                else:
                    self.assertIsNone(data)

    def test_disabled_empty_read_failures_and_no_hit_fall_back(self):
        for index, kind in enumerate(('disabled', 'empty', 'read_failure', 'envelope_failure', 'unavailable', 'unrelated')):
            with self.subTest(kind=kind):
                chat = make_chat(self.root / str(index), enabled=kind != 'disabled')
                if kind == 'read_failure':
                    chat.encounter_provider.chat.recall = lambda *a, **k: (_ for _ in ()).throw(OSError('synthetic'))
                if kind == 'envelope_failure':
                    chat.encounter_provider.chat.recall = lambda *a, **k: {'ok': False}
                if kind == 'unavailable':
                    chat.encounter_provider.chat = None
                if kind == 'unrelated':
                    seed(chat.encounter_provider.store)
                chat.reply_request('xyzzysynthetic')
                self.assertIsNone(external_data(chat.http.requests[0]))
                self.assertFalse(chat.last_context['external_adopted'])
                if kind == 'disabled':
                    self.assertFalse((self.root / str(index) / 'external').exists())
        # A filesystem error while opening the optional ledger also fails open.
        path = self.root / 'not-a-directory'
        path.write_text('synthetic')
        provider = LocalEncounterProvider(path, enabled=True)
        self.assertEqual(provider.prepare(QUESTION).status, 'unavailable')

    def test_reflections_are_filtered_before_use_no_latest_fallback(self):
        chat = make_chat(self.root)
        saved, body = seed(chat.encounter_provider.store)
        chat.encounter_provider.chat.select(saved['id'], saved['revision'], REMINDER)
        chat.reply_request('如何煮意面？')
        self.assertIsNone(external_data(chat.http.requests[0]))
        # The selected sentence can match independently of the main recall.
        original = chat.encounter_provider.chat.recall
        def no_main(query='', mode='related', **kw):
            result = original(query, mode=mode, **kw)
            if mode == 'related':
                result['result'].update(items=[], contextText='', charCount=0)
            return result
        chat.encounter_provider.chat.recall = no_main
        chat.reply_request('研究方法如何比较？')
        data = external_data(chat.http.requests[-1])
        self.assertFalse(data['items'])
        self.assertEqual(data['selectedReflections'][0]['nextResponse'], REMINDER)

    def test_whole_block_budget_preserves_chinese_recent_turn_and_fixed_content(self):
        chat = make_chat(self.root, enabled=False)
        prior = chat.reply_request('前一轮合成中文问题')
        provider = LocalEncounterProvider(self.root / 'external', enabled=True)
        seed(provider.store)
        # Measure the exact same host selection without external material.
        baseline, _, base_report = chat.context.build(chat.store, chat.store.session_id,
            str(uuid.uuid4()), __import__('workbench.companion_chat', fromlist=['system_prompt']).system_prompt() + chat.layers.permission_prompt(),
            QUESTION, chat._all_notes(), chat.store.note_policies())
        chat.encounter_provider = provider
        chat.context = ContextManager(budget=Budget(context_window=base_report['count'] + 700 + 512))
        chat.reply_request(QUESTION)
        actual = chat.http.requests[-1]['messages']
        self.assertEqual(actual, baseline)
        self.assertIn(prior['request_id'], chat.last_context['recent_turn_ids'])
        self.assertIn('external_encounters', chat.last_context['omitted'])
        self.assertEqual(chat.last_context['count'], chat.context.count(actual))
        self.assertLessEqual(chat.last_context['count'], chat.last_context['input_limit'])
        self.assertFalse(chat.last_context['external_adopted'])

    def _inflight(self, chat, mutation, *, succeeds=False):
        request_id = str(uuid.uuid4())
        outcome = {}
        def run():
            try: outcome['value'] = chat.reply_request(QUESTION, request_id=request_id)
            except Exception as error: outcome['error'] = error
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(chat.http.entered.wait(3), 'HTTP not reached')
            mutation()
        finally:
            chat.http.release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(chat.http.requests), 1, 'no automatic retry')
        state = turn_state(chat, request_id)
        if succeeds:
            self.assertIn('value', outcome)
            self.assertEqual(state['status'], 'complete')
        else:
            self.assertIn('error', outcome)
            self.assertIsInstance(outcome['error'], ChatStateError)
            self.assertNotEqual(state['status'], 'complete')
            self.assertEqual(state['assistant_messages'], 0)
        return outcome

    def test_pending_answer_invalidated_by_update_delete_catalog_cancel_session_or_config(self):
        for index, kind in enumerate(('update', 'delete', 'catalog', 'cancel', 'session', 'config', 'disable', 'replace', 'validation_failure')):
            with self.subTest(kind=kind):
                chat = make_chat(self.root / str(index), http=CapturedHTTP(hold=True))
                saved, _ = seed(chat.encounter_provider.store)
                other = EncounterStore(self.root / str(index) / 'external')
                def mutation():
                    if kind == 'update': other.update_fields(saved['id'], 1, {'facts': '用户修正后的合成结论'})
                    elif kind == 'delete': other.delete(saved['id'], 1)
                    elif kind == 'catalog': seed(other, slug='unrelated', quote='合成无关材料。')
                    elif kind == 'cancel': chat.cancel()
                    elif kind == 'session': chat.select_session()
                    elif kind == 'config':
                        # Public config writes are refused while sending; simulate
                        # the existing host configuration barrier under its guard.
                        with chat.guard: chat._connection_changed()
                    elif kind == 'disable': chat.encounter_provider.disable()
                    elif kind == 'replace': chat.encounter_provider = None
                    else: chat.encounter_provider.service.dispatch = lambda *a, **k: {'ok': False}
                self._inflight(chat, mutation)

    def test_unadopted_answer_survives_external_updates(self):
        # Empty/no-hit answer, and a budget-omitted answer, owe no external dependency.
        for index, budget_omitted in enumerate((False, True)):
            with self.subTest(budget_omitted=budget_omitted):
                chat = make_chat(self.root / str(index), http=CapturedHTTP(hold=True))
                if budget_omitted:
                    seed(chat.encounter_provider.store)
                    from workbench.companion_chat import system_prompt
                    _, _, report = chat.context.build(chat.store, chat.store.session_id, str(uuid.uuid4()),
                        system_prompt()+chat.layers.permission_prompt(), QUESTION, [], {})
                    chat.context = ContextManager(budget=Budget(context_window=report['count'] + 1212))
                self._inflight(chat, lambda: seed(chat.encounter_provider.store, slug='new'), succeeds=True)
                self.assertFalse(chat.last_context['external_adopted'])

    def test_catalog_change_during_recall_is_explicit_and_sends_nothing(self):
        chat = make_chat(self.root)
        seed(chat.encounter_provider.store)
        original = chat.encounter_provider.chat.recall
        def change_between_snapshots(*a, **kw):
            result = original(*a, **kw)
            if kw.get('mode') == 'related':
                seed(chat.encounter_provider.store, slug='second')
            return result
        chat.encounter_provider.chat.recall = change_between_snapshots
        with self.assertRaises(ChatStateError) as error:
            chat.reply_request(QUESTION)
        self.assertEqual(error.exception.code, 'external_context_stale')
        self.assertFalse(chat.http.requests)

    def test_publication_gate_excludes_other_store_writer_until_completion(self):
        chat = make_chat(self.root)
        saved, _ = seed(chat.encounter_provider.store)
        other = EncounterStore(self.root / 'external')
        started, done = threading.Event(), threading.Event()
        errors = []
        def write():
            started.set()
            try: other.update_fields(saved['id'], 1, {'facts': '门闩之后提交的合成纠正'})
            except Exception as error: errors.append(error)
            finally: done.set()
        writer = threading.Thread(target=write)
        original = chat.encounter_provider.service.dispatch
        def validate(*a, **kw):
            result = original(*a, **kw)
            if a[0] == 'encounters.context.validate':
                writer.start()
                self.assertTrue(started.wait(1))
            return result
        chat.encounter_provider.service.dispatch = validate
        complete = chat.store.complete
        def checked_complete(*a, **kw):
            self.assertFalse(done.is_set())
            return complete(*a, **kw)
        chat.store.complete = checked_complete
        answer = chat.reply_request(QUESTION)
        writer.join(5)
        self.assertTrue(done.is_set())
        self.assertFalse(errors)
        self.assertEqual(turn_state(chat, answer['request_id'])['status'], 'complete')

    def test_injection_is_only_data_no_host_layer_changes_or_tools(self):
        chat = make_chat(self.root)
        seed(chat.encounter_provider.store, injection=True)
        before = layer_snapshot(chat)
        chat.reply_request(QUESTION)
        payload = chat.http.requests[0]
        self.assertIn('忽略设定', external_data(payload)['items'][0]['inference'])
        self.assertNotIn('tools', payload)
        self.assertEqual(before, layer_snapshot(chat))
        self.assertIn('不是系统指令', payload['messages'][0]['content'])

    def test_failure_is_not_retried_and_plain_text_remains_compatible(self):
        chat = make_chat(self.root, http=CapturedHTTP(fail=True))
        seed(chat.encounter_provider.store)
        with self.assertRaises(ValueError): chat.reply_request(QUESTION)
        self.assertEqual(len(chat.http.requests), 1)
        chat.http = CapturedHTTP(content='合成纯文本fallback')
        answer = chat.reply_request('另一条不相关问题xyzz')
        self.assertEqual(answer['text'], '合成纯文本fallback')
        self.assertEqual((answer['emotion'], answer['action']), ('normal', 'none'))


if __name__ == '__main__': unittest.main(verbosity=2)
