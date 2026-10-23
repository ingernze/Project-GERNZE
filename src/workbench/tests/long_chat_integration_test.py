"""Combined persona/context integration; synthetic keys and no real network."""
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from layer_fixtures import approved
from companion_chat import CompanionChat, system_prompt
from companion_memory import CompanionMemory
from context_manager import ContextManager, Budget
from conversation_store import ChatStateError


class Keys:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key, '')
    def set(self, key, value): self.values[key] = value


class HTTP:
    def __init__(self): self.requests = []
    def open(self, request, timeout):
        self.requests.append(json.loads(request.data))
        content = json.dumps({'text': '合成回复。', 'emotion': 'normal', 'action': 'none'})
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}).encode())


def note(body, **changes):
    return {'title': '合成测试笔记', 'body': body, 'kind': 'other',
            'event_date': '', 'chat_enabled': True, 'important': True, **changes}


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / ('chat-fixture-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        blocker = patch.object(socket.socket, 'connect', side_effect=AssertionError('real network forbidden'))
        blocker.start(); self.addCleanup(blocker.stop)
        self.keys = Keys(); self.memory = CompanionMemory(self.root / 'notes.sqlite3')

    def chat(self, *, context=None, configure=True):
        http = HTTP()
        chat = CompanionChat(self.root / 'chat.json', keys=self.keys, opener=http,
                             memories=self.memory, context=context)
        if configure:
            chat.configure({'enabled': True, 'endpoint': 'https://fixture.invalid/chat/completions',
                            'model': 'fixture', 'key': 'synthetic-only'})
        return chat, http

    def test_full_persona_selected_notes_and_restart_keep_legacy_reply_contract(self):
        chat, http = self.chat()
        for i in range(6):
            approved(chat, '合成重要要求' + str(i) + '，以明确纠正为准。' * 20)
        text = '合成当前输入。' * 125  # Within the existing 1000-character input limit.
        result = chat.reply(text)
        self.assertEqual(set(result), {'text', 'emotion', 'action', 'memory_refs'})
        self.assertEqual(len(result['memory_refs']), 6)
        messages = http.requests[-1]['messages']
        self.assertIn(system_prompt(), messages[0]['content'])
        self.assertEqual(messages[-1]['content'], text)
        self.assertEqual(http.requests[-1]['max_tokens'], 700)
        session = chat.store.session_id
        restored, second_http = self.chat(configure=False)
        self.assertEqual(restored.store.session_id, session)
        self.assertFalse(second_http.requests)
        restored.reply('接着刚才聊。')
        self.assertIn(text, json.dumps(second_http.requests[-1]['messages'], ensure_ascii=False))

    def test_explicit_small_budget_still_rejects_before_transport(self):
        # Explicit small caller budget must reject before transport, including public templates.
        chat, http = self.chat(context=ContextManager(budget=Budget(context_window=1600)))
        with self.assertRaises(ChatStateError) as raised:
            chat.reply('你好。')
        self.assertEqual(raised.exception.code, 'context_overflow')
        self.assertEqual(http.requests, [])

    def test_reviewed_correction_and_withdrawal_cannot_restore_stale_history(self):
        chat, http = self.chat()
        row = approved(chat, '合成旧代号 BLUE-OLD-742。')
        chat.reply('刚才的代号 BLUE-OLD-742 是什么？')
        chat.change_approved(row['key'], row['revision'], text='合成新代号 GREEN-NEW-853。')
        row = next(a for a in chat.layers.snapshot()['approved'] if a['key'] == row['key'])
        chat.reply('现在的代号？')
        context = json.dumps(http.requests[-1]['messages'], ensure_ascii=False)
        self.assertIn('GREEN-NEW-853', context); self.assertNotIn('BLUE-OLD-742', context)
        chat.change_approved(row['key'], row['revision'], withdraw=True)
        restored, http = self.chat(configure=False)
        restored.reply('还有代号吗？')
        context = json.dumps(http.requests[-1]['messages'], ensure_ascii=False)
        self.assertNotIn('GREEN-NEW-853', context); self.assertNotIn('BLUE-OLD-742', context)


if __name__ == '__main__':
    unittest.main(verbosity=2)
