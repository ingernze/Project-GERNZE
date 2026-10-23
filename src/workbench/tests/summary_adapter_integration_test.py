"""Current mainline persona/core plus optional summary wiring; no external API."""
from email.message import Message
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_chat_integration_test as fixtures
from companion_chat import CompanionChat
from companion_memory import CompanionMemory
from summary_wiring import adapter_for_chat


class Response(io.BytesIO):
    def __init__(self, raw, url):
        super().__init__(raw); self.status = 200; self.url = url
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'
        self.headers['Content-Length'] = str(len(raw))
    def geturl(self): return self.url


class SummaryHTTP:
    def __init__(self): self.calls = []; self.fail = False
    def open(self, request, *, timeout, control):
        control.check(); self.calls.append(json.loads(request.data))
        message = {'role': 'assistant', 'content': json.dumps({'text': '讨论合成计划，尚未发生。'})}
        raw = json.dumps({'choices': [{'finish_reason': 'length' if self.fail else 'stop',
                                      'message': message}]}).encode()
        return Response(raw, request.full_url)


class SummaryIntegrationTests(unittest.TestCase):
    def test_current_persona_wiring_and_failed_summary_preserve_current_message(self):
        root = Path(__file__).resolve().parent / ('summary-fixture-' + uuid.uuid4().hex)
        root.mkdir(); self.addCleanup(shutil.rmtree, root)
        blocker = patch.object(socket.socket, 'connect', side_effect=AssertionError('real network forbidden'))
        blocker.start(); self.addCleanup(blocker.stop)
        http = fixtures.HTTP(); summary = SummaryHTTP()
        chat = CompanionChat(root / 'chat.json', keys=fixtures.Keys(), opener=http,
                             memories=CompanionMemory(root / 'notes.sqlite3'))
        chat.configure({'enabled': True, 'endpoint': 'https://fixture.invalid/chat/completions',
                        'model': 'fixture', 'key': 'synthetic-only'})
        adapter = adapter_for_chat(chat, http=summary)
        self.assertIsNone(chat.context.summarizer)  # No automatic extra API calls.
        self.assertEqual(adapter.limits.context_window, chat.context.budget.context_window)
        chat.context.summarizer = adapter  # Explicit activation in this isolated test only.
        # New daily minimum: the synthetic journal has passed its default 7-day interval.
        with chat.store.connection() as db: db.execute("UPDATE lc_sessions SET created_at='2000-01-01T00:00:00Z'")
        for i in range(10): chat.reply('合成学习安排' + str(i))
        session = chat.store.session_id
        before = chat.store.summary_view(session)['segments']
        self.assertEqual(len(before), 1); self.assertEqual(len(summary.calls), 1)
        summary.fail = True
        with chat.store.connection() as db: chat.store._set(db, 'summary_clock:'+session, '2000-01-01T00:00:00Z')
        for i in range(3): chat.reply('故障阶段当前消息' + str(i))
        self.assertEqual(chat.store.summary_view(session)['segments'], before)
        self.assertEqual(len(chat.store.messages(session)), 26)
        self.assertEqual(http.requests[-1]['messages'][-1]['content'], '故障阶段当前消息2')
        self.assertEqual(chat.last_context['summary_status'], 'failed')
        chat.context.summarizer = None


if __name__ == '__main__': unittest.main(verbosity=2)
