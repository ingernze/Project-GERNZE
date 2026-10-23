import unittest,tempfile,sys,json,uuid,hashlib,socket,ssl
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
P=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(P/'src'),str(P/'mobile/update-publisher'),str(P/'mobile/update-publisher/vendor')]
from workbench.owner_memory import owner_memory
from workbench.companion_memory import CompanionMemory
from workbench.conversation_store import ConversationStore
from workbench.server import WorkbenchServer
from workbench import memory_merge as mm
from memory_service import MemoryService
from publisher import Publisher
from rules import canonical
FIELDS={'title':'合成条目','body':'合成内容','kind':'other','event_date':'','chat_enabled':True,'important':False}

class Checks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'notes.sqlite3';self.server=str(uuid.uuid4());owner_memory(self.path,workbench=True)
    def tearDown(self):self.temp.cleanup()
    def test_legacy_and_stable_namespace(self):
        old=CompanionMemory(self.path).save(FIELDS);a=owner_memory(self.path);b=owner_memory(self.path)
        self.assertEqual(a.scope,b.scope);self.assertEqual(a.device_id,b.device_id);self.assertEqual(a.list()['records'][0],old)
        fixed=a.save({**FIELDS,'body':'纠正'},record_id=old['id'],revision=old['revision']);self.assertEqual(b.list()['records'][0]['body'],'纠正');self.assertNotEqual(fixed['revision'],old['revision'])
    def test_roundtrip_conflict_and_delete(self):
        service=MemoryService(self.path,self.server);pc=service.memory.save(FIELDS)
        peer=owner_memory(self.root/'phone.sqlite3');peer.scope=service.scope
        # Independent phone root record, with its own local writer identity.
        record={**FIELDS,'title':'手机合成条目','id':str(uuid.uuid4()),'revision':str(uuid.uuid4()),'parent_revision':None,'device_id':str(uuid.uuid4()),'created_at':pc['created_at'],'updated_at':pc['updated_at'],'deleted':False}
        mobile=mm.export_records([record],expected_scope=service.scope)
        first=service.exchange({'snapshot':mobile});self.assertEqual(len(first['active_records']),2)
        second=service.exchange({'snapshot':mobile});self.assertEqual(first['snapshot'],second['snapshot'])
        base=first['snapshot'];phone={**pc,'body':'手机改动','revision':str(uuid.uuid4()),'parent_revision':pc['revision']}
        remote=mm.merge(base,mm.export_records([phone],expected_scope=service.scope),expected_scope=service.scope)
        now=service.memory.save({**FIELDS,'body':'电脑改动'},record_id=pc['id'],revision=pc['revision'])
        conflict=service.exchange({'snapshot':remote});self.assertEqual(conflict['status'],'needs_decision');self.assertNotIn(pc['id'],[r['id'] for r in conflict['active_records']])
        chosen=service.decide({'id':pc['id'],'fingerprint':conflict['fingerprint'],'note':{**FIELDS,'body':'明确选择'},'delete':False});self.assertEqual(chosen['status'],'ready')
        restored=next(r for r in chosen['active_records'] if r['id']==pc['id']);service.memory.forget(restored['id'],restored['revision'])
        result=service.exchange({'snapshot':base});self.assertNotIn(pc['id'],[r['id'] for r in result['active_records']])
    def test_wrong_scope_rejected(self):
        service=MemoryService(self.path,self.server)
        wrong=mm.export_records([],expected_scope=str(uuid.uuid4()))
        with self.assertRaises(ValueError):service.exchange({'snapshot':wrong})
        self.assertEqual(service.memory.list()['records'],[])
    def test_old_desktop_writer_is_not_migrated_by_publisher(self):
        old=self.root/'old.sqlite3';record=CompanionMemory(old).save(FIELDS)
        with self.assertRaisesRegex(ValueError,'updated_workbench_required'):MemoryService(old,self.server)
        self.assertEqual(CompanionMemory(old).list()['records'],[record])
    def test_desktop_minimum_and_weekly_clock(self):
        store=ConversationStore(self.root/'chat.sqlite3');sid=store.session_id
        self.assertFalse(store.summary_due(sid,7));self.assertTrue(store.summary_due(sid,1,now=datetime.now(timezone.utc)+timedelta(days=2)))
        with self.assertRaises(ValueError):store.summary_due(sid,0)
    def test_real_workbench_initializes_updated_writer_without_api(self):
        server=WorkbenchServer(self.root/'workbench-state')
        try:
            service=MemoryService(self.root/'workbench-state/workbench/companion-memory.sqlite3',self.server)
            self.assertEqual(service.info()['scope_id'],server.memories.scope)
            self.assertEqual(server.chat.context.summary_interval_days,7)
            self.assertIsNotNone(server.chat.context.summarizer)
        finally:server.server_close()
    def test_authenticated_tls_exchange(self):
        apk=self.root/'synthetic.apk';apk.write_bytes(b'synthetic-not-an-installable-apk');raw=apk.read_bytes()
        manifest={'schemaVersion':1,'artifactId':str(uuid.uuid4()),'packageName':'com.hecate.companion','versionCode':1,'versionName':'synthetic','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'signerCertificateSha256':['a'*64],'minSdkVersion':24}
        with patch('publisher.private_host',lambda v:v):publisher=Publisher(self.root/'publisher',apk,manifest,'127.0.0.1',memory_path=self.path).start()
        try:
            invite=publisher.issue_invitation();cert=ssl.DER_cert_to_PEM_cert(publisher.der);context=ssl.create_default_context(cadata=cert)
            def request(method,path,body=None,credentials=None):
                data=canonical(body) if body is not None else b'';headers=f'{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{publisher.port}\r\nConnection: close\r\n'
                if body is not None:headers+=f'Content-Type: application/json\r\nContent-Length: {len(data)}\r\n'
                if credentials:headers+='Authorization: Bearer '+credentials['token']+'\r\nX-Hebao-Pairing: '+credentials['pairingId']+'\r\n'
                with socket.create_connection(('127.0.0.1',publisher.port),timeout=3) as rawsock:
                    with context.wrap_socket(rawsock,server_hostname='hebao.local') as secured:
                        secured.sendall((headers+'\r\n').encode()+data);output=b''
                        while block:=secured.recv(65536):output+=block
                head,payload=output.split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(payload)
            status,_=request('GET','/v1/memory/info');self.assertEqual(status,401)
            status,auth=request('POST','/v1/pair',{'serverId':invite['serverId'],'deviceId':str(uuid.uuid4()),'pairingSecret':invite['pairingSecret']});self.assertEqual(status,200)
            status,info=request('GET','/v1/memory/info',credentials=auth);self.assertEqual(status,200)
            empty=mm.export_records([],expected_scope=info['scope_id']);status,answer=request('POST','/v1/memory/exchange',{'snapshot':empty},auth);self.assertEqual(status,200);self.assertEqual(answer['status'],'ready')
        finally:publisher.close()

if __name__=='__main__':unittest.main(verbosity=2)
