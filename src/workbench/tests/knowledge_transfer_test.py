"""Synthetic project files and journal; no owner profile, TLS identity or model."""
from contextlib import contextmanager,closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from http.server import HTTPServer
import hashlib,http.client,json,sqlite3,sys,tempfile,threading,unittest,uuid
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'mobile/update-publisher'))
from workbench.knowledge_library import KnowledgeWork,KnowledgeReader,SNAPSHOT_FORMAT,packed
from workbench.knowledge_transfer import KnowledgeTransfer
from workbench.conversation_store import ConversationStore
from workbench.memory_layers import MemoryLayers
import layer_service

class Checks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.profile=self.root/'profile';self.profile.mkdir();self.lib=self.root/'library';self.lib.mkdir()
  (self.lib/'索引.json').write_text(packed({'schema_version':1,'scope':'current_project_work_mode','revision':0,'courses':[],'items':[]}),encoding='utf8')
  self.work=KnowledgeWork(self.lib);self.a=self.work.collection('Synthetic database');self.b=self.work.collection('Synthetic math');self.note=self.put(self.a)
  self.save_link(self.lib);self.server=str(uuid.uuid4());self.scope=str(uuid.uuid4());self.transfer=KnowledgeTransfer(self.profile,self.server,self.scope)
 def save_link(self,path): (self.profile/'knowledge-workspace.json').write_text(packed({'format':'gernze-knowledge-link-v1','workspace':str(path)}),encoding='utf8')
 def put(self,c,**kw):return self.work.put(collection_id=c['id'],title='Index 🌙',body='B+树索引，synthetic source.',origin='user',source_ref='synthetic chapter',**kw)['item']
 def request(self,ids=None):return {'knowledge':{'format':SNAPSHOT_FORMAT,'course_ids':[self.a['course_id']] if ids is None else ids}}
 def test_capability_metadata_only(self):
  with patch.object(KnowledgeReader,'_body',side_effect=AssertionError('body touched')):
   k=self.transfer.capability();self.assertEqual(len(k['courses']),2);self.assertEqual(set(k),{'format','libraryId','courses'})
 def test_snapshot_binding_hash_and_repeat(self):
  p=self.transfer.exchange(self.request());self.assertEqual(p,self.transfer.exchange(self.request()));h=p.pop('hash');self.assertEqual(hashlib.sha256(packed(p).encode()).hexdigest(),h);self.assertEqual(p['serverId'],self.server);self.assertEqual(len(p['entries']),1)
 def test_invalid_request_no_body(self):
  with patch.object(KnowledgeReader,'_body',side_effect=AssertionError('body touched')):
   for r in ({'knowledge':{'format':SNAPSHOT_FORMAT,'course_ids':[],'write':True}}, {'knowledge':{},'snapshot':{}},self.request([{}]),self.request([self.a['course_id']]*2),self.request([str(uuid.uuid4())])):
    with self.assertRaises(ValueError):self.transfer.exchange(r)
 def test_empty_selection_reads_no_body(self):
  with patch.object(KnowledgeReader,'_body',side_effect=AssertionError('body touched')):
   p=self.transfer.exchange(self.request([]));self.assertEqual(p['entries'],[]);self.assertEqual(p['courses'],[])
 def test_course_filter_before_body(self):
  other=self.put(self.b);calls=[];original=KnowledgeReader._body
  def body(reader,item):calls.append(item['id']);return original(reader,item)
  with patch.object(KnowledgeReader,'_body',body):self.transfer.exchange(self.request())
  self.assertEqual(calls,[self.note['id']]);self.assertNotIn(other['id'],calls)
 def test_original_attachment_not_exported(self):
  p=self.root/'original.txt';p.write_text('synthetic original',encoding='utf8');self.put(self.a,original_file=p)
  self.assertTrue(any(e.get('original') for e in self.work.catalog()['entries']));self.assertTrue(all('original' not in e for e in self.transfer.exchange(self.request())['entries']))
 def test_source_withdrawal_drops_derived_before_read(self):
  self.put(self.a,related=self.note['id']);self.work.withdraw(self.note['id'],self.note['revision'])
  with patch.object(KnowledgeReader,'_body',side_effect=AssertionError('invalid body touched')):self.assertEqual(self.transfer.exchange(self.request())['entries'],[])
 def test_mutation_during_export_rejected(self):
  original=KnowledgeReader._body
  def body(reader,item):r=original(reader,item);self.work.withdraw(self.note['id'],self.note['revision']);return r
  with patch.object(KnowledgeReader,'_body',body):
   with self.assertRaisesRegex(ValueError,'changed_during_export'):self.transfer.exchange(self.request())
 def test_bad_optional_link_does_not_break_capability(self):
  (self.profile/'knowledge-workspace.json').write_text('{bad',encoding='utf8');self.assertIsNone(self.transfer.capability())
 def test_layer_service_dispatch_preserves_journal(self):
  store=ConversationStore(self.profile/'workbench/chat-sessions.sqlite3');MemoryLayers(store,core_loader=lambda:{'entries':[]})
  with closing(sqlite3.connect(store.path)) as db:before=list(db.iterdump())
  with patch.object(layer_service,'load_core',lambda:{'entries':[]}):service=layer_service.LayerService(store.path,self.server)
  self.assertEqual(service.info()['knowledgeLibrary']['libraryId'],self.transfer.capability()['libraryId']);self.assertEqual(len(service.exchange(self.request())['entries']),1)
  restarted=KnowledgeTransfer(self.profile,self.server,service.scope);self.assertEqual(service.exchange(self.request()),restarted.exchange(self.request()))
  with closing(sqlite3.connect(store.path)) as db:self.assertEqual(before,list(db.iterdump()))
 def test_real_http_route_rechecks_auth_after_export(self):
  from publisher import Handler
  case=self
  class Fake:
   host='127.0.0.1';port=0;allowed=True;revoke=False
   def authorized(self,*args):return self.allowed
   @contextmanager
   def database(self):yield SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:[str(uuid.uuid4())]))
   def layers(self):return self
   def exchange(self,body,**kw):
    result=case.transfer.exchange(body)
    if self.revoke:self.allowed=False
    return result
  p=Fake();httpd=HTTPServer(('127.0.0.1',0),Handler);httpd.publisher=p;p.port=httpd.server_port;t=threading.Thread(target=httpd.serve_forever,daemon=True);t.start()
  def send():
   c=http.client.HTTPConnection(p.host,p.port,timeout=5);c.request('POST','/v1/layers/exchange',packed(self.request()),{'Content-Type':'application/json','Authorization':'Bearer synthetic','X-Hebao-Pairing':'synthetic'});r=c.getresponse();status=r.status;value=json.loads(r.read());c.close();return status,value
  try:
   status,value=send();self.assertEqual(status,200);self.assertEqual(value['format'],SNAPSHOT_FORMAT)
   p.revoke=True;status,value=send();self.assertEqual(status,401);self.assertNotIn('entries',value)
  finally:httpd.shutdown();httpd.server_close();t.join(5)

if __name__=='__main__':unittest.main()
