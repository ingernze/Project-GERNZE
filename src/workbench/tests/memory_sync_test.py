from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from companion_memory import CompanionMemory
from companion_chat import CompanionChat
from context_manager import ContextManager
from persistent_memory import PersistentMemory
from chat_sync import ChatMemorySync
import memory_merge as mm


def uid():return str(uuid.uuid4())
def note(**kw):return {'title':'合成记忆','body':'合成计划日期2026-11-05','kind':'event','event_date':'2026-11-05','chat_enabled':True,'important':False,**kw}


class Keys:
    def get(self,target):return 'synthetic-only'
    def set(self,target,key):pass


class HTTP:
    def __init__(self):self.calls=[];self.enter=None;self.release=None
    def open(self,request,timeout):
        self.calls.append(json.loads(request.data))
        if self.enter:
            self.enter.set()
            if not self.release.wait(2):raise TimeoutError()
        return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"text":"合成回复。"}'}}]}).encode())


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.scope=uid();self.a_id=uid();self.b_id=uid()
        self.a=self.memory('a',self.a_id);self.b=self.memory('b',self.b_id)
    def memory(self,name,device):return PersistentMemory(self.root/(name+'.sqlite3'),expected_scope=self.scope,device_id=device)
    def state(self,memory=None):return (memory or self.a).export_exchange(expected_scope=self.scope)
    def transfer(self,target,remote):
        plan=target.preview(remote,expected_scope=self.scope)
        return target.apply(remote,plan,expected_scope=self.scope)
    def fork(self):
        first=self.a.save(note());self.transfer(self.b,self.state());return first
    def chat(self,memory=None,context=None,configure=True):
        http=HTTP();chat=CompanionChat(self.root/'chat.json',keys=Keys(),opener=http,memories=memory or self.a,context=context)
        if configure:chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'fixture','key':'synthetic-only'})
        return chat,http,ChatMemorySync(chat)

    def test_legacy_bootstrap_all_rows_and_no_fabricated_ancestors(self):
        legacy=CompanionMemory(self.a.path);first=legacy.save(note(body='合成旧正文'))
        second=legacy.save(note(body='合成现正文'),record_id=first['id'],revision=first['revision'])
        deleted=legacy.save(note(title='将忘记'));legacy.forget(deleted['id'],deleted['revision'])
        with closing(sqlite3.connect(self.a.path)) as db, db:before=db.execute('SELECT * FROM notes ORDER BY id').fetchall()
        state=self.state();self.assertEqual(len(state['revisions']),2)
        self.assertNotIn('合成旧正文',mm.canonical(state).decode());self.assertTrue(any(r['deleted'] for r in state['records']))
        with closing(sqlite3.connect(self.a.path)) as db, db:
            self.assertEqual(before,db.execute('SELECT * FROM notes ORDER BY id').fetchall());self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
        reopened=self.memory('a',self.a_id);self.assertEqual(state,self.state(reopened));self.assertEqual(reopened.list()['records'],[second])

    def test_two_offline_corrections_delete_restart_and_reimport_old_package(self):
        first=self.a.save(note(body='SYNTHETIC_OLD_BODY'));old=self.state()
        second=self.a.save(note(body='SYNTHETIC_SECOND'),record_id=first['id'],revision=first['revision'])
        self.a=self.memory('a',self.a_id)
        third=self.a.save(note(body='SYNTHETIC_THIRD'),record_id=second['id'],revision=second['revision'])
        self.a.forget(third['id'],third['revision']);self.a=self.memory('a',self.a_id)
        state=self.state();self.assertEqual(len(state['revisions']),4)
        for _ in range(2):self.assertEqual(self.transfer(self.a,old)['status'],'applied')
        self.assertEqual(state,self.state());self.assertEqual(self.a.list()['records'],[])
        wire=self.a.export_json(expected_scope=self.scope)
        for text in ('SYNTHETIC_OLD_BODY','SYNTHETIC_SECOND','SYNTHETIC_THIRD'):
            self.assertNotIn(text.encode(),wire);self.assertNotIn(text.encode(),self.a.path.read_bytes())
        self.assertTrue(all(r['deleted'] for r in state['records']))

    def test_concurrent_edits_persist_quarantine_and_explicit_multi_parent_decision(self):
        root=self.fork()
        left=self.a.save(note(body='并发左'),record_id=root['id'],revision=root['revision'])
        right=self.b.save(note(body='并发右'),record_id=root['id'],revision=root['revision'])
        remote=self.state(self.b);plan=self.a.preview(remote,expected_scope=self.scope)
        before=self.state();self.assertEqual(self.a.apply(remote,plan,expected_scope=self.scope)['status'],'needs_decision');self.assertEqual(before,self.state())
        result=self.a.stage_conflicts(remote,plan,expected_scope=self.scope);self.assertTrue(result['staged']);self.assertFalse(result['applied'])
        self.a=self.memory('a',self.a_id);self.assertEqual(self.a.chat_notes(),[]);self.assertEqual(self.a.list()['records'],[])
        state=self.state();self.assertEqual(len(mm.inspect(state,expected_scope=self.scope)['quarantine_revisions']),2)
        with self.assertRaises(mm.Rejected):self.a.decide(root['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),note=note())
        self.a.decide(root['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),note=note(body='人工确认结果'),confirmed=True)
        final=self.state();self.assertEqual(len(final['records']),1)
        tip=next(n for n in final['revisions'] if n['revision']==final['records'][0]['revision'])
        self.assertEqual(tip['parents'],sorted([left['revision'],right['revision']]))
        self.assertNotIn('并发左',mm.canonical(final).decode());self.assertNotIn('并发右',mm.canonical(final).decode())
        self.transfer(self.b,final);self.assertEqual(self.state(self.b),final)

    def test_delete_edit_discards_body_and_no_same_id_restore(self):
        root=self.fork();self.a.forget(root['id'],root['revision'])
        self.b.save(note(body='SYNTHETIC_CONCURRENT_PRIVATE'),record_id=root['id'],revision=root['revision'])
        remote=self.state(self.b);plan=self.a.preview(remote,expected_scope=self.scope)
        self.assertEqual(plan['report']['conflicts'][0]['status'],'delete_edit')
        self.a.stage_conflicts(remote,plan,expected_scope=self.scope)
        state=self.state();self.assertNotIn('SYNTHETIC_CONCURRENT_PRIVATE',mm.canonical(state).decode())
        with self.assertRaises(mm.Rejected):self.a.decide(root['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),note=note(),confirmed=True)
        self.a.decide(root['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),delete=True,confirmed=True)
        self.a=self.memory('a',self.a_id);self.transfer(self.a,remote)
        self.assertEqual(self.a.chat_notes(),[]);self.assertEqual(self.a.status(expected_scope=self.scope)['report']['conflicts'],[])
        self.assertNotIn('SYNTHETIC_CONCURRENT_PRIVATE'.encode(),self.a.path.read_bytes())

    def test_stale_or_modified_plan_and_repeat_import(self):
        self.a.save(note());remote=self.state(self.b);plan=self.a.preview(remote,expected_scope=self.scope)
        self.a.save(note(title='新条目'));before=self.state()
        self.assertEqual(self.a.apply(remote,plan,expected_scope=self.scope)['status'],'needs_refresh');self.assertEqual(before,self.state())
        plan=self.a.preview(remote,expected_scope=self.scope);plan['status']='tampered'
        with self.assertRaises(mm.Rejected):self.a.apply(remote,plan,expected_scope=self.scope)
        self.assertEqual(before,self.state())
        for _ in range(2):self.transfer(self.a,remote)
        self.assertEqual(before,self.state())

    def test_failure_rolls_back_notes_graph_and_bootstrap_schema(self):
        first=self.a.save(note());before=self.state()
        for step in ('after_notes','after_graph','before_commit'):
            def fault(stage):
                if stage==step:raise OSError('synthetic disk fault')
            self.a.fault_hook=fault
            with self.assertRaises(OSError):self.a.save(note(body='不能部分提交'),record_id=first['id'],revision=first['revision'])
            self.a.fault_hook=None;self.assertEqual(self.state(),before)
        legacy=CompanionMemory(self.root/'bootstrap.sqlite3');legacy.save(note())
        failing=PersistentMemory(legacy.path,expected_scope=self.scope,device_id=self.a_id,fault_hook=lambda stage:(_ for _ in ()).throw(OSError()))
        with self.assertRaises(OSError):self.state(failing)
        with closing(sqlite3.connect(legacy.path)) as db, db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn('memory_sync_meta',tables);self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)

    def test_process_crash_hot_journal_recovers_atomic_prior_state(self):
        row=self.a.save(note());before=self.state()
        script="""import os,sys
from persistent_memory import PersistentMemory
m=PersistentMemory(sys.argv[1],expected_scope=sys.argv[2],device_id=sys.argv[3])
m.export_exchange(expected_scope=sys.argv[2])
def crash(stage):
 if stage=='after_notes':os._exit(9)
m.fault_hook=crash
m.forget(sys.argv[4],sys.argv[5])
"""
        import os
        env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
        p=subprocess.run([sys.executable,'-B','-c',script,str(self.a.path),self.scope,self.a_id,row['id'],row['revision']],env=env,capture_output=True)
        self.assertEqual(p.returncode,9);self.a=self.memory('a',self.a_id);self.assertEqual(before,self.state())

    def test_manual_and_staged_capacity_no_auto_disable_or_delete(self):
        rows=[self.a.save(note(title=str(i))) for i in range(6)]
        with self.assertRaisesRegex(ValueError,'最多参考6条'):self.a.save(note(title='第七条'))
        local=self.a.save(note(title='仅保存',chat_enabled=False));before=self.state()
        with self.assertRaises(ValueError):self.a.save(note(),record_id=local['id'],revision=local['revision'])
        self.assertEqual(before,self.state())
        self.b.save(note(title='远端第七勾选'));remote=self.state(self.b);plan=self.a.preview(remote,expected_scope=self.scope)
        self.assertEqual(plan['report']['limits'][0]['code'],'chat_limit')
        self.a.stage_conflicts(remote,plan,expected_scope=self.scope);state=self.state()
        self.assertEqual(self.a.chat_notes(),[]);self.assertEqual(sum(r['chat_enabled'] for r in state['records']),7)
        target=next(r for r in state['records'] if not r['deleted'] and r['chat_enabled'])
        self.a.decide(target['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),note={k:(False if k=='chat_enabled' else target[k]) for k in mm.NOTE_FIELDS},confirmed=True)
        self.assertEqual(len(self.a.chat_notes()),6)

    def test_100_record_limit_requires_explicit_deletion(self):
        records=[]
        for i in range(101):
            records.append({'id':uid(),'revision':uid(),'parent_revision':None,'device_id':self.b_id,
                **note(title=str(i),chat_enabled=False),'created_at':'2026-10-17T00:00:00Z','updated_at':'2026-10-17T00:00:00Z','deleted':False})
        remote=mm.export_records(records[:100],expected_scope=self.scope);self.transfer(self.a,remote)
        with self.assertRaisesRegex(ValueError,'最多保存100条'):self.a.save(note(chat_enabled=False))
        remote=mm.export_records(records,expected_scope=self.scope);plan=self.a.preview(remote,expected_scope=self.scope)
        self.a.stage_conflicts(remote,plan,expected_scope=self.scope);state=self.state()
        self.assertEqual(sum(not r['deleted'] for r in state['records']),101)
        self.a.decide(records[0]['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(state),delete=True,confirmed=True)
        self.assertEqual(len(self.a.list()['records']),100)

    def test_scope_identity_unknown_versions_and_bypass_fail_closed(self):
        with self.assertRaises(mm.Rejected):self.a.export_exchange(expected_scope=uid())
        self.assertFalse(self.a.path.exists())
        self.state()
        wrong=PersistentMemory(self.a.path,expected_scope=self.scope,device_id=uid())
        with self.assertRaises(mm.Rejected):self.state(wrong)
        with closing(sqlite3.connect(self.a.path)) as db, db:db.execute("UPDATE memory_sync_meta SET value='99' WHERE key='schema_version'")
        before=self.a.path.read_bytes()
        with self.assertRaises(mm.Rejected):self.state()
        self.assertEqual(self.a.path.read_bytes(),before)
        with closing(sqlite3.connect(self.b.path)) as db, db:db.execute('PRAGMA user_version=99')
        before=self.b.path.read_bytes()
        with self.assertRaises(ValueError):self.state(self.b)
        self.assertEqual(before,self.b.path.read_bytes())
        other=self.memory('external',uid());other.save(note());CompanionMemory(other.path).save(note(title='绕过写入'))
        with self.assertRaisesRegex(mm.Rejected,'outside_adapter'):other.chat_notes()

    def test_chat_import_invalidates_inflight_summary_indexes_and_rebinds_correction(self):
        def summarizer(req,**kw):return {'text':'合成旧话题OLD','source_turn_ids':req['source_turn_ids']}
        chat,http,sync=self.chat(context=ContextManager(summarizer=summarizer,budget=__import__('context_manager').Budget(32768)))
        first=chat.change_memory({'note':note(body='OLD_SYNTHETIC')});self.transfer(self.b,self.state())
        for i in range(10):chat.reply('旧话题OLD'+str(i))
        self.assertTrue(chat.store.summary_view(chat.store.session_id)['segments'])
        self.b.save(note(body='NEW_SYNTHETIC'),record_id=first['id'],revision=first['revision'])
        remote=self.state(self.b);plan=sync.preview(remote,expected_scope=self.scope)
        http.enter=threading.Event();http.release=threading.Event();errors=[]
        def send():
            try:chat.reply('在途旧请求')
            except ValueError as error:errors.append(error)
        worker=threading.Thread(target=send);worker.start();self.assertTrue(http.enter.wait(1))
        self.assertTrue(sync.apply(remote,plan,expected_scope=self.scope)['applied'])
        http.release.set();worker.join(2);self.assertFalse(worker.is_alive());self.assertTrue(errors)
        self.assertEqual(chat.store.summary_view(chat.store.session_id)['segments'],[])
        self.assertEqual(chat.store.retrieve(chat.store.session_id,'OLD'),[])
        http.enter=None;chat.reply('现在是什么？');payload=json.dumps(http.calls[-1],ensure_ascii=False)
        self.assertIn('NEW_SYNTHETIC',payload);self.assertNotIn('OLD_SYNTHETIC',payload)
        self.assertEqual(chat.store.pending_changes(),[])

    def test_coordinator_stages_conflict_and_crash_recovery_blocks_context(self):
        chat,http,sync=self.chat();first=chat.change_memory({'note':note(body='OLD_SYNTHETIC')})
        self.transfer(self.b,self.state());remote_old=self.state(self.b)
        self.b.save(note(body='REMOTE_SYNTHETIC'),record_id=first['id'],revision=first['revision'])
        remote=self.state(self.b);plan=sync.preview(remote,expected_scope=self.scope)
        sync.fault_hook=lambda stage:(_ for _ in ()).throw(OSError('synthetic cross-db interruption'))
        with self.assertRaises(OSError):sync.apply(remote,plan,expected_scope=self.scope)
        operation=chat.store.pending_changes()[0]['id']
        chat,http,sync=self.chat(configure=False);chat.reply('恢复前不得引用')
        payload=json.dumps(http.calls[-1],ensure_ascii=False);self.assertNotIn('REMOTE_SYNTHETIC',payload);self.assertNotIn('OLD_SYNTHETIC',payload)
        with self.assertRaises(mm.Rejected):sync.recover(operation)
        sync.recover(operation,confirmed=True);chat.reply('恢复后')
        self.assertIn('REMOTE_SYNTHETIC',json.dumps(http.calls[-1],ensure_ascii=False))
        # A stale sibling now creates an explicit conflict which survives restart.
        c=self.memory('c',uid());self.transfer(c,remote_old)
        c.save(note(body='SIBLING_SYNTHETIC'),record_id=first['id'],revision=first['revision'])
        result=sync.review_exchange(self.state(c),expected_scope=self.scope)
        self.assertTrue(result['staged']);self.assertEqual(self.a.list()['records'],[])
        chat.reply('冲突未裁决');payload=json.dumps(http.calls[-1],ensure_ascii=False)
        self.assertNotIn('REMOTE_SYNTHETIC',payload);self.assertNotIn('SIBLING_SYNTHETIC',payload)

    def test_export_excludes_chat_and_nonportable_scoped_policy(self):
        chat,http,sync=self.chat();row=chat.change_memory({'note':note()});chat.reply('ONLY_RAW_CHAT_SYNTHETIC')
        state=sync.export_exchange(expected_scope=self.scope)
        self.assertEqual(set(state),{'format','version','scope_id','records','revisions'})
        self.assertNotIn('ONLY_RAW_CHAT_SYNTHETIC',mm.canonical(state).decode())
        with chat.store.connection() as db:db.execute("UPDATE lc_note_policy SET scope='casual' WHERE note_id=?",(row['id'],))
        with self.assertRaisesRegex(mm.Rejected,'nonportable_note_policy'):sync.export_exchange(expected_scope=self.scope)


if __name__=='__main__':unittest.main()
