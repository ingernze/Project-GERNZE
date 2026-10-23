"""Synthetic journal, review, archive and permission tests; no external network."""
from pathlib import Path
import sys,tempfile,unittest,uuid,io,json,threading,sqlite3,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from workbench.conversation_store import ConversationStore,ChatStateError
from workbench.memory_layers import MemoryLayers
from workbench.memory_archive import MemoryArchive,day_of
from workbench.companion_chat import CompanionChat
from workbench.companion_memory import CompanionMemory
from workbench.context_manager import ContextManager
from workbench.bridge import validate_call,CONTRACTS
from workbench.server import CONTROL

class Keys:
 def __init__(self):self.d={}
 def get(self,k):return self.d.get(k,'')
 def set(self,k,v):self.d[k]=v
 def delete(self,k):self.d.pop(k,None)
class HTTP:
 def __init__(self):self.requests=[];self.enter=None;self.release=None
 def open(self,r,timeout):
  self.requests.append(json.loads(r.data))
  if self.enter:self.enter.set();self.release.wait(4)
  return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'text':'合成回复','layer2':{'body':'MODEL-WRITE-FORBIDDEN'}})}}]}).encode())

class AlignmentTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='gernze-alignment-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.s=ConversationStore(self.root/'journal.sqlite3');self.layers=MemoryLayers(self.s)
 def turns(self,n=10):
  ids=[]
  for i in range(n):
   rid=str(uuid.uuid4());self.s.begin_turn(self.s.session_id,'合成用户原文 '+str(i),rid)
   self.s.complete(rid,{'text':'合成回答 '+str(i),'emotion':'normal','action':'none'},self.s.epoch(),[]);ids.append(rid)
  return ids
 def summary(self,text='合成待审摘要'):
  view=self.s.summary_view(self.s.session_id,keep_recent=1,batch=3);ts=view['new_turns'];self.assertEqual(len(ts),3)
  self.assertTrue(self.s.commit_summary(self.s.session_id,view,ts,text));return self.layers.snapshot()['pending'][-1]
 def chat(self):
  self.http=HTTP();c=CompanionChat(self.root/'chat.json',keys=Keys(),opener=self.http,memories=CompanionMemory(self.root/'legacy.sqlite3'))
  c.configure({'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'fixture','key':'synthetic-only'});return c
 def test_summary_and_working_are_atomic_and_raw_retained(self):
  self.turns();before=self.s.messages(self.s.session_id)
  w=self.summary();self.assertEqual(len(w['source_ids']),6);self.assertEqual(before,self.s.messages(self.s.session_id))
  with self.s.read_connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM lc_turns WHERE covered=1').fetchone()[0],3)
  self.assertEqual(self.layers.snapshot()['approved'],[])
 def test_failed_working_write_rolls_back_summary_and_covered(self):
  self.turns();view=self.s.summary_view(self.s.session_id,keep_recent=1,batch=3);ingest=self.layers.ingest
  def broken(*args):raise sqlite3.OperationalError('synthetic write failure')
  self.layers.ingest=broken
  with self.assertRaises(sqlite3.OperationalError):self.s.commit_summary(self.s.session_id,view,view['new_turns'],'合成摘要')
  self.layers.ingest=ingest
  with self.s.read_connection() as db:
   self.assertEqual(db.execute('SELECT count(*) FROM lc_summaries').fetchone()[0],0);self.assertEqual(db.execute('SELECT sum(covered) FROM lc_turns').fetchone()[0],0)
 def test_replay_never_overwrites_correction_or_revives_withdrawal(self):
  self.turns();w=self.summary();d=[{'key':w['key'],'revision':w['revision'],'action':'approve'}];self.layers.decide(d)
  a=self.layers.snapshot()['approved'][0];self.layers.change_approved(a['key'],a['revision'],text='合成较新纠正')
  self.assertEqual(self.layers.decide(d),{'applied':0,'alreadyProcessed':1});a=self.layers.snapshot()['approved'][0];self.assertEqual(a['body'],'合成较新纠正')
  self.layers.change_approved(a['key'],a['revision'],withdraw=True);self.layers.decide(d)
  a=self.layers.snapshot()['approved'][0];self.assertTrue(a['deleted']);self.assertEqual(a['body'],'');self.assertEqual(self.layers.context_notes(),[])
 def test_changed_decision_for_already_reviewed_revision_rejected(self):
  self.turns();w=self.summary();self.layers.decide([{'key':w['key'],'revision':w['revision'],'action':'reject'}])
  with self.assertRaises(ValueError):self.layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'}])
  self.assertFalse(self.layers.snapshot()['pending']);self.assertFalse(self.layers.snapshot()['approved'])
 def test_batch_rejects_all_if_any_version_stale(self):
  self.turns(15);a=self.summary();b=self.summary('另一组合成摘要')
  with self.assertRaises(ValueError):self.layers.decide([{'key':a['key'],'revision':a['revision'],'action':'approve'},{'key':b['key'],'revision':'stale','action':'approve'}])
  self.assertEqual(self.layers.snapshot()['approved'],[])
  with self.s.read_connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM lm_receipts').fetchone()[0],0)
 def test_baseline_compare_and_swap_rejects_old_review(self):
  self.turns();w=self.summary()
  with self.s.connection() as db:db.execute('INSERT INTO lm_approved VALUES (?,?,?,?,?,0,?)',(w['key'],str(uuid.uuid4()),'较新已审纠正','newer','2026-10-19T00:00:00Z','owner'))
  with self.assertRaisesRegex(ValueError,'基线'):self.layers.decide([{'key':w['key'],'revision':w['revision'],'action':'approve'}])
  self.assertEqual(self.layers.snapshot()['approved'][0]['body'],'较新已审纠正')
 def test_restart_restores_layers_receipts_and_raw(self):
  self.turns();w=self.summary();d=[{'key':w['key'],'revision':w['revision'],'action':'approve'}];self.layers.decide(d)
  reopened=ConversationStore(self.s.path);layers=MemoryLayers(reopened)
  self.assertEqual(len(reopened.messages(reopened.session_id)),20);self.assertEqual(len(layers.snapshot()['approved']),1);self.assertEqual(layers.decide(d)['alreadyProcessed'],1)
 def test_raw_archive_includes_compressed_turns_but_chat_does_not(self):
  self.turns();w=self.summary();c=type('Chat',(),{'store':self.s,'layers':self.layers})();a=MemoryArchive(c)
  latest=a.history();self.assertEqual(len(latest['turns']),1);self.assertEqual(latest['compressedTurns'],3)
  all_visible=a.history(limit=20)['turns'];self.assertEqual(len(all_visible),7);self.assertEqual(len(self.s.messages(self.s.session_id)),20)
  self.assertTrue(any(e['kind']=='summary' for e in a._entries()));self.assertEqual(sum(e['kind']=='conversation' for e in a._entries()),10)
 def test_archive_timezone_unknown_date_and_empty_month(self):
  self.assertEqual(day_of('2026-10-01T16:00:01Z'),'2026-10-02');self.assertEqual(day_of('2026-10-01T15:59:59Z'),'2026-10-01');self.assertIsNone(day_of('2026-10-01'))
  ids=self.turns(2)
  with self.s.connection() as db:db.execute("UPDATE lc_messages SET time='' WHERE turn_id=?",(ids[0],));db.execute("UPDATE lc_messages SET time='2026-10-01T16:30:00Z' WHERE turn_id=?",(ids[1],))
  a=MemoryArchive(type('Chat',(),{'store':self.s,'layers':self.layers})());self.assertEqual(a.months(),[{'month':'2026-10','dayCount':1,'entryCount':1}]);self.assertEqual(a.days('2026-10')[0]['day'],'2026-10-02');self.assertEqual(len(a.undated()['entries']),1);self.assertEqual(a.day('2026-12-24')['entries'],[])
 def test_read_bridges_cannot_write_and_leave_database_bytes_unchanged(self):
  self.turns();a=MemoryArchive(type('Chat',(),{'store':self.s,'layers':self.layers})());before=self.s.path.read_bytes()
  a.history();a.months();a.days('2026-10');a.day('2026-10-19');a.status();self.layers.snapshot();self.assertEqual(before,self.s.path.read_bytes())
  with self.s.read_connection() as db:
   with self.assertRaises(sqlite3.OperationalError):db.execute("INSERT INTO lm_meta VALUES ('forbidden','true')")
 def test_legacy_notes_not_promoted_or_sent_to_model(self):
  c=self.chat();note={'title':'旧样例','body':'LEGACY-AUTO-PROMOTE-BLOCK','kind':'other','event_date':'','chat_enabled':True,'important':True};c.memories.save(note);before=c.memories.path.read_bytes()
  a=MemoryArchive(c,legacy=c.memories);self.assertEqual(len(a.legacy_notes()['records']),1);self.assertEqual(before,c.memories.path.read_bytes());self.assertFalse(c.layers.snapshot()['approved'])
  c.reply_request('你好');self.assertNotIn('LEGACY-AUTO-PROMOTE-BLOCK',json.dumps(self.http.requests));self.assertFalse(c.layers.snapshot()['approved']);self.assertEqual(before,c.memories.path.read_bytes())
 def test_model_reply_extra_fields_have_no_write_authority(self):
  c=self.chat();result=c.reply_request('合成输入');self.assertEqual(result['text'],'合成回复');self.assertNotIn('layer2',result);self.assertEqual(c.layers.snapshot()['working'],[]);self.assertEqual(c.layers.snapshot()['approved'],[])
 def test_core_keys_cannot_be_approved_or_corrected(self):
  self.layers.core_loader=lambda:{'schemaVersion':1,'entries':[{'key':'core-fixture','body':'只读合成基础'}]}
  with self.assertRaises(ValueError):self.layers.change_approved('core-fixture','revision',text='禁止')
  with self.assertRaises(ValueError):self.layers.decide([{'key':'core-fixture','revision':'x','action':'approve'}])
  self.assertEqual(self.layers.snapshot()['core']['entries'][0]['body'],'只读合成基础')
 def test_forged_chat_summary_cannot_enter_working(self):
  with self.s.connection() as db:
   with self.assertRaises(ValueError):self.layers.ingest(db,{'id':'forged'})
  self.assertEqual(self.layers.snapshot()['working'],[])
 def test_manual_write_bridges_removed_and_core_method_closed(self):
  self.assertNotIn('chat.memory.save',CONTROL);self.assertNotIn('chat.memory.forget',CONTROL);self.assertNotIn('memory.save',CONTRACTS)
  c=self.chat()
  with self.assertRaises(ValueError):c.change_memory({'note':{}})
  with self.assertRaises(ValueError):validate_call({'command':'memory.save','params':{'title':'x','body':'x','decision':'adopted'}})
 def test_interval_minimum_and_defaults(self):
  self.assertEqual(self.layers.settings(),{'reviewDays':7,'summaryDays':7,'summaryEnabled':True})
  for bad in [0,-1,True,1.5]:
   with self.assertRaises(ValueError):self.layers.configure({'reviewDays':7,'summaryDays':bad,'summaryEnabled':True})
  self.layers.configure({'reviewDays':None,'summaryDays':1,'summaryEnabled':False});self.assertEqual(self.layers.settings()['summaryDays'],1)
 def test_cancel_before_request_arrival_blocks_model_and_save(self):
  c=self.chat();rid=str(uuid.uuid4());c.cancel(rid)
  with self.assertRaises(ChatStateError):c.reply_request('迟到合成请求',request_id=rid)
  self.assertEqual(self.http.requests,[]);self.assertEqual(c.store.messages(c.store.session_id),[])
 def test_cancel_during_request_preserves_user_raw_and_blocks_late_reply(self):
  c=self.chat();self.http.enter=threading.Event();self.http.release=threading.Event();rid=str(uuid.uuid4());errors=[]
  def run():
   try:c.reply_request('停止测试原文',request_id=rid)
   except Exception as e:errors.append(e)
  worker=threading.Thread(target=run);worker.start();self.assertTrue(self.http.enter.wait(2));c.cancel(rid);self.http.release.set();worker.join(3)
  self.assertFalse(worker.is_alive());self.assertTrue(errors);messages=c.store.messages(c.store.session_id);self.assertEqual(len(messages),1);self.assertEqual(messages[0]['content'],'停止测试原文');self.assertEqual(messages[0]['status'],'cancelled')
  self.http.enter=None;c.reply_request('新的当前页对话');self.assertEqual(len(c.store.messages(c.store.session_id)),3)
 def test_old_scoped_cancel_does_not_cancel_new_request(self):
  c=self.chat();old=str(uuid.uuid4());c.cancel(old);self.http.enter=threading.Event();self.http.release=threading.Event();new=str(uuid.uuid4());results=[]
  worker=threading.Thread(target=lambda:results.append(c.reply_request('当前页',request_id=new)));worker.start();self.assertTrue(self.http.enter.wait(2));c.cancel(old);self.http.release.set();worker.join(3);self.assertEqual(results[0]['text'],'合成回复')
 def test_cancelled_summary_does_not_commit_working(self):
  self.turns()
  with self.s.connection() as db:db.execute("UPDATE lc_sessions SET created_at='2020-01-01T00:00:00Z'")
  entered=threading.Event();release=threading.Event()
  def summary(req,**kw):entered.set();release.wait(2);return {'text':'不得提交的迟到摘要','source_turn_ids':req['source_turn_ids']}
  ctx=ContextManager(summarizer=summary,keep_recent=1,min_batch=3,summary_timeout=.3);results=[]
  worker=threading.Thread(target=lambda:results.append(ctx.summarize(self.s,self.s.session_id)));worker.start();self.assertTrue(entered.wait(1));ctx.cancel();worker.join(2);release.set();self.assertEqual(results,['cancelled']);self.assertEqual(self.layers.snapshot()['working'],[])
 def test_summary_persistence_failure_keeps_raw_uncovered_and_reports_failure(self):
  self.turns()
  with self.s.connection() as db:db.execute("UPDATE lc_sessions SET created_at='2000-01-01T00:00:00Z'")
  ctx=ContextManager(summarizer=lambda req,**kw:{'text':'合成摘要','source_turn_ids':req['source_turn_ids']},keep_recent=1,min_batch=3)
  def broken(*args):raise sqlite3.OperationalError('synthetic storage failure')
  self.layers.ingest=broken
  self.assertEqual(ctx.summarize(self.s,self.s.session_id),'storage_failed')
  self.assertEqual(len(self.s.messages(self.s.session_id)),20)
  with self.s.read_connection() as db:self.assertEqual(db.execute('SELECT sum(covered) FROM lc_turns').fetchone()[0],0)
 def test_tk_forms_are_read_only_in_both_actual_classes(self):
  import ast
  for name in ['_ui_baseline.py','ui.py']:
   p=Path(__file__).resolve().parents[3]/'libao_modules'/name;tree=ast.parse(p.read_text());methods=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_build_memory'];self.assertEqual(len(methods),1)
   text=ast.get_source_segment(p.read_text(),methods[0]);self.assertNotIn('memory_confirmed',text);self.assertNotIn('保存记录',text);self.assertIn('导出 Markdown',text)
if __name__=='__main__':unittest.main(verbosity=2)
