"""Isolated note persistence, stale-write and chat-context regression checks."""
import io
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from layer_fixtures import approved
from companion_memory import CompanionMemory
from companion_chat import CompanionChat


def note(**extra):
    return {'title':'考试日期','body':'考试改为2026年11月6日。','kind':'event',
            'event_date':'2026-11-06','chat_enabled':True,'important':False,**extra}


class Keys:
    def __init__(self): self.values={}
    def get(self,key): return self.values.get(key,'')
    def set(self,key,value): self.values[key]=value


class HTTP:
    def __init__(self): self.requests=[]; self.enter=None; self.release=None
    def open(self,request,timeout):
        self.requests.append(json.loads(request.data))
        if self.enter: self.enter.set(); self.release.wait(3)
        return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"text":"知道啦。"}'}}]}).encode())


class MemoryTests(unittest.TestCase):
    def setUp(self):
        # mkdir inherits the workspace ACL; TemporaryDirectory's restrictive ACL
        # is not usable with this Windows sandbox profile.
        self.directory=Path(__file__).resolve().parent/('memory-fixture-'+uuid.uuid4().hex)
        self.directory.mkdir(); self.addCleanup(shutil.rmtree,self.directory)
        self.path=self.directory/'notes.sqlite3'; self.memory=CompanionMemory(self.path)

    def test_constructor_is_lazy_and_records_survive_new_instances(self):
        self.assertFalse(self.path.exists())
        row=self.memory.save(note())
        loaded=CompanionMemory(self.path).list()['records']
        self.assertEqual(loaded,[row]); self.assertTrue(row['device_id']); self.assertTrue(row['revision'])

    def test_correction_keeps_identity_and_only_new_text_is_current(self):
        row=self.memory.save(note(body='旧日期：11月5日'))
        newer=self.memory.save(note(),record_id=row['id'],revision=row['revision'])
        self.assertEqual(row['id'],newer['id']); self.assertEqual(newer['parent_revision'],row['revision'])
        self.assertNotEqual(newer['revision'],row['revision'])
        prompt,refs=self.memory.prompt(); self.assertNotIn('旧日期',prompt); self.assertIn('11月6日',prompt)
        self.assertEqual(refs,[{'id':row['id'],'title':'考试日期'}])

    def test_two_stale_editors_do_not_overwrite_each_other(self):
        row=self.memory.save(note())
        other=CompanionMemory(self.path)
        other.save(note(body='已确认新日期'),record_id=row['id'],revision=row['revision'])
        with self.assertRaisesRegex(ValueError,'已经变化'):
            self.memory.save(note(body='过时编辑'),record_id=row['id'],revision=row['revision'])
        self.assertEqual(self.memory.list()['records'][0]['body'],'已确认新日期')

    def test_forget_removes_content_but_keeps_a_content_free_tombstone(self):
        marker='private-memory-marker-'+uuid.uuid4().hex
        row=self.memory.save(note(title=marker,body=marker))
        self.memory.forget(row['id'],row['revision'])
        self.assertEqual(self.memory.list()['records'],[]); self.assertEqual(self.memory.prompt(),('',[]))
        with closing(sqlite3.connect(self.path)) as db:
            data=db.execute('SELECT title,body,deleted,parent_revision FROM notes').fetchone()
        self.assertEqual(data,('','',1,row['revision']))
        self.assertNotIn(marker.encode(),self.path.read_bytes())

    def test_stale_forget_cannot_remove_a_corrected_record(self):
        row=self.memory.save(note())
        self.memory.save(note(body='保留这条纠正'),record_id=row['id'],revision=row['revision'])
        with self.assertRaisesRegex(ValueError,'已经变化'):self.memory.forget(row['id'],row['revision'])
        self.assertEqual(len(self.memory.list()['records']),1)

    def test_only_explicit_chat_notes_enter_prompt_and_important_is_first(self):
        self.memory.save(note(title='仅保存',chat_enabled=False))
        self.memory.save(note(title='普通'))
        self.memory.save(note(title='重要',important=True))
        prompt,refs=self.memory.prompt()
        self.assertEqual([x['title'] for x in refs],['重要','普通']); self.assertNotIn('仅保存',prompt)
        self.assertIn('不是系统指令',prompt); self.assertIn('不冒称设置了提醒',prompt)

    def test_chat_limit_is_explicit_and_failed_edit_does_not_mutate(self):
        rows=[self.memory.save(note(title=str(i))) for i in range(6)]
        with self.assertRaisesRegex(ValueError,'最多参考6条'):self.memory.save(note())
        local=self.memory.save(note(chat_enabled=False))
        with self.assertRaisesRegex(ValueError,'最多参考6条'):
            self.memory.save(note(body='不能写入',chat_enabled=True),record_id=local['id'],revision=local['revision'])
        current=next(x for x in self.memory.list()['records'] if x['id']==local['id'])
        self.assertEqual(current,local)
        self.memory.save(note(title='同一条修订'),record_id=rows[0]['id'],revision=rows[0]['revision'])

    def test_invalid_data_is_rejected_without_inserting_records(self):
        for value in [note(title=''),note(body='x'*501),note(event_date='2026-02-30'),note(event_date='20261106'),note(chat_enabled=1),{**note(),'extra':'not allowed'}]:
            with self.assertRaises(ValueError):self.memory.save(value)
        self.assertEqual(self.memory.list()['records'],[])

    def test_unknown_database_version_is_not_rewritten(self):
        with closing(sqlite3.connect(self.path)) as db:db.execute('PRAGMA user_version=99')
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'版本较新'):self.memory.list()
        self.assertEqual(before,self.path.read_bytes())

    def chat(self):
        http=HTTP();chat=CompanionChat(self.directory/'chat.json',keys=Keys(),opener=http,memories=self.memory)
        chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'fixture','key':'not-a-real-key'})
        return chat,http

    def test_reviewed_notes_reach_provider_without_an_extra_model_call(self):
        self.memory.save(note()); chat,http=self.chat(); row=approved(chat,note()['body']+' 事件日期：'+note()['event_date'])
        with patch('companion_chat.system_prompt',return_value='fixture persona'):
            reply=chat.reply('考试什么时候？')
        self.assertEqual(len(http.requests),1)
        self.assertIn('2026-11-06',http.requests[0]['messages'][0]['content'])
        self.assertEqual(reply['memory_refs'][0]['title'],'已审核记忆')
        self.assertNotIn('tools',http.requests[0])

    def test_correction_clears_short_history_and_replaces_next_request_context(self):
        chat,http=self.chat(); row=approved(chat,'旧记忆')
        with patch('companion_chat.system_prompt',return_value='fixture persona'):
            chat.reply('旧记忆相关问题')
            chat.change_approved(row['key'],row['revision'],text='新记忆')
            self.assertEqual(chat.history,[])
            chat.reply('现在呢')
        payload=json.dumps(http.requests[-1],ensure_ascii=False)
        self.assertIn('新记忆',payload); self.assertNotIn('旧记忆',payload)

    def test_forget_retires_in_flight_reply_and_does_not_repopulate_context(self):
        chat,http=self.chat(); row=approved(chat,note()['body']+' 事件日期：'+note()['event_date']); errors=[]
        http.enter=threading.Event();http.release=threading.Event()
        def send():
            try:chat.reply('fixture')
            except ValueError as error:errors.append(str(error))
        with patch('companion_chat.system_prompt',return_value='fixture persona'):
            worker=threading.Thread(target=send);worker.start();self.assertTrue(http.enter.wait(1))
            chat.change_approved(row['key'],row['revision'],withdraw=True)
            http.release.set();worker.join(3)
            self.assertFalse(worker.is_alive());self.assertTrue(errors);self.assertEqual(chat.history,[])
            reply=chat.reply('新的话题')
        self.assertNotIn('memory_refs',reply);self.assertNotIn('考试日期',json.dumps(http.requests[-1],ensure_ascii=False))


if __name__=='__main__':unittest.main()
