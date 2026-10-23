from pathlib import Path
import sys,tempfile,unittest,uuid,sqlite3,json,socket,ssl,hashlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]));sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'mobile/update-publisher'))
from workbench.phone_archive import PhoneArchive,chain,ZERO,FORMAT
from workbench.conversation_store import encoded
from workbench.companion_chat import CompanionChat
from workbench.memory_archive import MemoryArchive
from workbench.layer_sync import LayerSync,empty,identity
from workbench import memory_merge as mm
from layer_service import LayerService
from publisher import Publisher

def turn(i,text='合成原文'):return {'index':i,'user':text,'assistant':'合成回答','userAt':'2026-10-20T00:00:00Z','assistantAt':'2026-10-20T00:00:01Z'}
def body(rows,start=0,previous=ZERO):return {'format':FORMAT,'sessionId':'phone-session','start':start,'previous':previous,'turns':rows}
def packet(scope,tier=3):
 p=empty(scope);revision=str(uuid.uuid4());key='summary:phone-test'
 entry={'key':key,'revision':revision,'body':'合成待审记忆','deleted':False,'updatedAt':'2026-10-20T00:00:01Z','createdAt':'2026-10-20T00:00:01Z','approvedBaseRevision':None,'source':{'sessionId':'phone-session','summaryId':'phone-test','epoch':0,'start':0,'end':6,'turnIds':[],'messageIds':[],'at':'2026-10-20T00:00:00Z'}}
 rid=identity(tier,key);payload={'tier':tier,'entry':entry};record={'id':rid,'revision':revision,'parent_revision':None,'device_id':str(uuid.uuid4()),'title':'layer-'+str(tier),'body':mm.digest(payload),'kind':'other','event_date':'','chat_enabled':False,'important':False,'created_at':'1970-01-01T00:00:00Z','updated_at':'2026-10-20T00:00:01Z','deleted':False}
 p['graph']['records']=[record];p['graph']['revisions']=[{'id':rid,'revision':revision,'parents':[],'deleted':False,'digest':mm.digest(record)}];p['identities'][rid]={'tier':tier,'key':key};p['payloads'][revision]=payload;return p
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.chat=CompanionChat(Path(self.tmp.name)/'chat.json');self.raw=PhoneArchive(self.chat.store.path);self.device=str(uuid.uuid4());self.service=LayerService(self.chat.store.path,str(uuid.uuid4()))
 def tearDown(self):self.tmp.cleanup()
 def test_cursor_resume_and_retry_do_not_duplicate(self):
  self.assertEqual(self.raw.exchange(self.device,body([]))['next'],0)
  first=self.raw.exchange(self.device,body([turn(0),turn(1)]));self.assertEqual(first['next'],2)
  self.assertEqual(self.raw.exchange(self.device,body([turn(0),turn(1)]))['accepted'],0)
  self.assertEqual(self.raw.exchange(self.device,body([turn(2)],2,first['chain']))['next'],3)
  self.assertEqual(len(self.raw.entries()),3)
 def test_conflicting_original_is_not_overwritten(self):
  self.raw.exchange(self.device,body([turn(0)]))
  with self.assertRaisesRegex(ValueError,'raw_source_changed'):self.raw.exchange(self.device,body([turn(0,'改写旧原文')]))
  self.assertEqual(self.raw.entries()[0]['user'],'合成原文')
 def test_failed_batch_rolls_back_all_rows(self):
  self.raw.exchange(self.device,body([]))
  with self.raw.connection(True) as db:db.execute("CREATE TRIGGER fail_second BEFORE INSERT ON turns WHEN NEW.seq=1 BEGIN SELECT RAISE(ABORT,'synthetic'); END")
  with self.assertRaises(sqlite3.IntegrityError):self.raw.exchange(self.device,body([turn(0),turn(1)]))
  self.assertEqual(self.raw.exchange(self.device,body([]))['next'],0);self.assertEqual(self.raw.entries(),[])
 def test_archive_counts_and_undated_raw(self):
  row=turn(1);row['userAt']=row['assistantAt']=None;self.raw.exchange(self.device,body([turn(0),row]))
  archive=MemoryArchive(self.chat);self.assertEqual(archive.status()['phoneStoredMessages'],4);self.assertEqual(archive.status()['desktopStoredMessages'],0)
  self.assertTrue(archive.day('2026-10-20')['entries']);self.assertEqual(len(archive.undated()['entries']),1)
 def test_credentials_and_foreign_layers_not_raw_fields(self):
  value=body([turn(0)]);value['apiKey']='SYNTHETIC'
  with self.assertRaises(ValueError):self.raw.exchange(self.device,value)
  other=str(uuid.uuid4());self.raw.exchange(self.device,body([turn(0)]));self.assertEqual(self.raw.exchange(other,body([]))['next'],0)
 def test_phone_cannot_review_or_send_approved_edits(self):
  with self.assertRaisesRegex(ValueError,'review_on_desktop'):self.service.decide({})
  with self.assertRaisesRegex(ValueError,'approved_memory_desktop_only'):self.service.exchange({'snapshot':packet(self.service.scope,2)},peer_device=self.device)
  self.assertEqual(self.chat.layers.snapshot()['approved'],[])
 def test_review_requires_uploaded_source_then_returns_approved(self):
  p=packet(self.service.scope);self.service.exchange({'snapshot':p},peer_device=self.device);pending=self.chat.layers.snapshot()['pending'][0]
  decision={'key':pending['key'],'revision':pending['revision'],'action':'approve'}
  self.assertIn('phoneSource',pending)
  with self.assertRaisesRegex(ValueError,'尚未传齐'):self.chat.review_layers([decision])
  self.raw.exchange(self.device,body([turn(i) for i in range(3)]));self.assertTrue(self.chat.layers.phone_source(pending['key'],pending['revision'])['complete'])
  self.assertEqual(self.chat.review_layers([decision])['applied'],1)
  answer=self.service.exchange({'snapshot':p},peer_device=self.device);self.assertTrue(any(m['tier']==2 for m in answer['packet']['identities'].values()))
 def test_owner_and_raw_database_stay_separate(self):
  owner=self.chat.store.owner;self.raw.exchange(self.device,body([turn(0)]))
  with self.chat.store.read_connection() as db:
   self.assertEqual(db.execute("SELECT value FROM lc_meta WHERE key='owner'").fetchone()[0],owner)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM lc_messages').fetchone()[0],0)
 def test_authenticated_tls_raw_route_and_desktop_review_policy(self):
  root=Path(self.tmp.name);apk=root/'synthetic.apk';apk.write_bytes(b'synthetic-not-installable');raw=apk.read_bytes()
  manifest={'schemaVersion':1,'artifactId':str(uuid.uuid4()),'packageName':'com.hecate.companion','versionCode':1,'versionName':'synthetic','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'signerCertificateSha256':['a'*64],'minSdkVersion':24}
  with patch('publisher.private_host',lambda v:v):publisher=Publisher(root/'publisher',apk,manifest,'127.0.0.1',memory_path=root/'companion-memory.sqlite3').start()
  try:
   invitation=publisher.issue_invitation();context=ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(publisher.der))
   def request(path,data,auth=None):
    payload=encoded(data).encode('utf8');headers=f'POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{publisher.port}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n'
    if auth:headers+='Authorization: Bearer '+auth['token']+'\r\nX-Hebao-Pairing: '+auth['pairingId']+'\r\n'
    with socket.create_connection(('127.0.0.1',publisher.port),timeout=3) as sock:
     with context.wrap_socket(sock,server_hostname='hebao.local') as tls:
      tls.sendall((headers+'\r\n').encode()+payload);response=b''
      while block:=tls.recv(65536):response+=block
    head,value=response.split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(value)
   self.assertEqual(request('/v1/raw/exchange',body([]))[0],401)
   status,auth=request('/v1/pair',{'serverId':invitation['serverId'],'deviceId':self.device,'pairingSecret':invitation['pairingSecret']});self.assertEqual(status,200)
   status,result=request('/v1/raw/exchange',body([turn(0)]),auth);self.assertEqual(status,200);self.assertEqual(result['next'],1)
   self.assertEqual(request('/v1/layers/decide',{},auth)[0],409)
  finally:publisher.close()
if __name__=='__main__':unittest.main(verbosity=2)
