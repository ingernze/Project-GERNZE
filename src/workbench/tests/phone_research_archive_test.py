"""Synthetic paired research archives; real SQLite and authenticated TLS route."""
import copy,hashlib,json,sqlite3,sys,tempfile,unittest,uuid,socket
from pathlib import Path
from unittest.mock import patch
from workbench.phone_research_archive import PhoneResearchArchive,FORMAT,USE_FORMAT
from workbench.phone_archive import PhoneArchive,FORMAT as PLAIN,ZERO
from workbench.conversation_store import encoded
from workbench.companion_chat import CompanionChat
from workbench.memory_archive import MemoryArchive
from workbench.layer_sync import LayerSync,empty
ORIGINAL_CONNECT=socket.socket.connect

def new():return str(uuid.uuid4())
def sha(v):return hashlib.sha256(v.encode('utf-8')).hexdigest()
def receipt(server,scope,session,text='合成研究问题',source=None):
    return {'format':USE_FORMAT,'cache':{'serverId':server,'scope_id':scope,'sequence':1,'fingerprint':'f'*64},'request':{'id':new(),'sessionId':session,'inputHash':sha(text)},'source':source or {'id':new(),'revision':new(),'body_hash':'a'*64,'restriction':'general','courses':[],'facets':['interest'],'trust':'research_summary','review':{'status':'pending','reason':''},'sources':[{'id':new(),'revision':new(),'body_hash':'b'*64,'source_versions':{new():new()},'restriction':'general','courses':[]}],'parents':[],'raw_refs':{new():'c'*64}}}
def turn(i,r=None,text='合成研究问题'):
    return {'index':i,'user':text,'assistant':'合成研究回答','userAt':'2026-10-27T00:00:00Z','assistantAt':'2026-10-27T00:00:01Z','research':r}

class PhoneResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.chat=CompanionChat(Path(self.tmp.name)/'chat.json');self.server=new();self.scope=str(uuid.uuid5(uuid.UUID(self.server),'gernze-layer-memory-v1'));self.device=new();self.sid='synthetic-phone'
        self.archive=PhoneResearchArchive(self.chat.store.path,self.server,self.scope);self.receipt=receipt(self.server,self.scope,self.sid)
    def body(self,turns=None,base=0,start=None,previous=ZERO):return {'format':FORMAT,'serverId':self.server,'scope_id':self.scope,'sessionId':self.sid,'baseStart':base,'start':base if start is None else start,'previous':previous,'turns':turns or []}
    def test_resume_retry_and_plain_tail_keep_exact_original_indices(self):
        rows=[turn(0,self.receipt),turn(1)];a=self.archive.exchange(self.device,self.body(rows));self.assertEqual(a['next'],2)
        self.assertEqual(self.archive.exchange(self.device,self.body(rows))['accepted'],0)
        self.archive.exchange(self.device,self.body([turn(2)],start=2,previous=a['chain']))
        self.assertEqual([m['seq'] for m in self.archive.metadata()],[0,1,2]);self.assertEqual(self.archive.raw(self.device,self.sid,0)['research'],self.receipt)
    def test_changed_original_receipt_or_replay_is_not_overwritten(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));changed=copy.deepcopy(self.receipt);changed['source']['raw_refs']={new():'b'*64}
        with self.assertRaisesRegex(ValueError,'source_changed'):self.archive.exchange(self.device,self.body([turn(0,changed)]))
        self.assertEqual(self.archive.raw(self.device,self.sid,0)['research'],self.receipt)
    def test_raw_meta_cursor_rollback_together(self):
        self.archive.exchange(self.device,self.body())
        with self.archive.connection(True) as db:db.execute("CREATE TRIGGER fail_meta BEFORE INSERT ON pr_meta WHEN NEW.seq=1 BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.archive.exchange(self.device,self.body([turn(0,self.receipt),turn(1)]))
        self.assertEqual(self.archive.exchange(self.device,self.body())['next'],0);self.assertEqual(self.archive.metadata(),[])
        with self.archive.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM pr_bodies').fetchone()[0],0)
    def test_unconfirmed_plain_prefix_and_gap_rejected(self):
        with self.assertRaisesRegex(ValueError,'prefix_not_confirmed'):self.archive.exchange(self.device,self.body([turn(2,self.receipt)],base=2))
        with self.assertRaisesRegex(ValueError,'cursor_changed'):self.archive.exchange(self.device,self.body([turn(1,self.receipt)],start=1))
    def test_confirmed_plain_prefix_remains_in_legacy_only(self):
        p=PhoneArchive(self.chat.store.path);rows=[{k:v for k,v in turn(i).items() if k!='research'} for i in range(2)]
        p.exchange(self.device,{'format':PLAIN,'sessionId':self.sid,'start':0,'previous':ZERO,'turns':rows})
        self.archive.exchange(self.device,self.body([turn(2,self.receipt)],base=2));self.assertEqual(len(p.entries()),2)
        self.assertFalse(p.source(self.device,self.sid,4,6)['complete']);self.assertEqual(len(self.archive.metadata()),1)
    def test_legacy_writer_cannot_relabel_already_attributed_tail(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));plain=PhoneArchive(self.chat.store.path)
        with self.assertRaisesRegex(ValueError,'requires_attributed_channel'):plain.exchange(self.device,{'format':PLAIN,'sessionId':self.sid,'start':0,'previous':ZERO,'turns':[{k:v for k,v in turn(0).items() if k!='research'}]})
        self.assertEqual(plain.entries(),[])
    def test_first_invalid_batch_does_not_leave_partial_schema(self):
        with self.assertRaisesRegex(ValueError,'prefix_not_confirmed'):self.archive.exchange(self.device,self.body([turn(2,self.receipt)],base=2))
        with self.archive.connection() as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='pr_schema'").fetchone())
    def test_changed_base_and_other_binding_rejected(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));bad=self.body();bad['scope_id']=new()
        with self.assertRaises(ValueError):self.archive.exchange(self.device,bad)
        self.assertEqual(self.archive.exchange(new(),self.body())['next'],0)
    def test_input_hash_and_session_bind_current_question(self):
        with self.assertRaisesRegex(ValueError,'input_changed'):self.archive.exchange(self.device,self.body([turn(0,self.receipt,'别的问题')]))
        bad=copy.deepcopy(self.receipt);bad['request']['sessionId']='other'
        with self.assertRaisesRegex(ValueError,'request'):self.archive.exchange(self.device,self.body([turn(0,bad)]))
    def test_course_and_forged_permission_fields_rejected(self):
        for change in [lambda s:s.update(restriction='study',courses=[new()]),lambda s:s['sources'][0].update(restriction='study',courses=[new()]),lambda s:s.update(facets=['course']),lambda s:s.update(grant='study')]:
            r=copy.deepcopy(self.receipt);change(r['source'])
            with self.assertRaises(ValueError):self.archive.exchange(self.device,self.body([turn(0,r)]))
    def test_extra_credentials_body_fields_and_bad_versions_rejected(self):
        for change in [lambda b:b.update(apiKey='synthetic'),lambda b:b['turns'][0]['research'].update(format='future'),lambda b:b['turns'][0]['research']['cache'].update(sequence=True),lambda b:b['turns'][0]['research']['cache'].update(fingerprint='x'*64),lambda b:b['turns'][0]['research']['source'].update(body='not-a-receipt-field')]:
            b=self.body([turn(0,copy.deepcopy(self.receipt))]);change(b)
            with self.assertRaises(ValueError):self.archive.exchange(self.device,b)
    def test_duplicate_request_cannot_move_between_indices(self):
        with self.assertRaisesRegex(ValueError,'duplicate_research_request'):self.archive.exchange(self.device,self.body([turn(0,self.receipt),turn(1,self.receipt)]))
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));state=self.archive.exchange(self.device,self.body())
        with self.assertRaises(sqlite3.IntegrityError):self.archive.exchange(self.device,self.body([turn(1,self.receipt)],start=1,previous=state['chain']))
        self.assertEqual(len(self.archive.metadata()),1)
    def test_unknown_archive_schema_is_not_downgraded(self):
        self.archive.exchange(self.device,self.body())
        with self.archive.connection(True) as db:db.execute('UPDATE pr_schema SET version=3')
        with self.assertRaisesRegex(ValueError,'updated_research_archive_required'):self.archive.exchange(self.device,self.body())
        with self.archive.connection() as db:self.assertEqual(db.execute('SELECT version FROM pr_schema').fetchone()[0],3)
    def test_new_archive_does_not_change_runtime_or_old_approval_stores(self):
        with self.chat.store.read_connection() as db:before={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['lc_messages','lm_approved','lm_working']};owner=self.chat.store.owner
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]))
        with self.chat.store.read_connection() as db:self.assertEqual(before,{t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before});self.assertEqual(db.execute("SELECT value FROM lc_meta WHERE key='owner'").fetchone()[0],owner)
        self.assertEqual(PhoneArchive(self.chat.store.path).entries(),[])
    def test_directory_status_reads_no_research_body(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));queries=[];original=sqlite3.connect
        def traced(*args,**kwargs):db=original(*args,**kwargs);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',traced):
            archive=MemoryArchive(self.chat);self.assertEqual(archive.months()[0]['entryCount'],1);self.assertEqual(archive.days('2026-10')[0]['entryCount'],1);self.assertEqual(archive.status()['phoneStoredMessages'],2)
        self.assertFalse(any('pr_bodies' in q and q.startswith('SELECT') for q in queries))
    def test_only_explicit_day_hydrates_original_and_uncertain_source_label(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]));a=MemoryArchive(self.chat)
        self.assertEqual(a.day('2026-10-26')['entries'],[])
        entry=a.day('2026-10-27')['entries'][0];self.assertIn('来源当前无法核对',entry['text']);self.assertIn('不作为已审用户事实',entry['text']);self.assertIn('合成研究回答',entry['text'])
    def test_undated_research_requires_explicit_undated_view(self):
        t=turn(0,self.receipt);t['userAt']=t['assistantAt']=None;self.archive.exchange(self.device,self.body([t]));self.assertEqual(MemoryArchive(self.chat).status()['undatedEntries'],1);self.assertIn('合成研究回答',MemoryArchive(self.chat).undated()['entries'][0]['text'])
    def test_archived_body_corruption_not_silently_displayed(self):
        self.archive.exchange(self.device,self.body([turn(0,self.receipt)]))
        with self.archive.connection(True) as db:db.execute("UPDATE pr_bodies SET payload='{}'")
        with self.assertRaisesRegex(ValueError,'archive_integrity'):self.archive.raw(self.device,self.sid,0)

class CurrentSourceTests(unittest.TestCase):
    def setUp(self):
        import research_summaries_test as fixtures
        self.h=fixtures.ResearchSummaryTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.source,self.h.entry=self.h.fixture.seed(course=False,text='SYNTHETIC_GENERAL');self.h.worker.text='SYNTHETIC_GENERAL_SUMMARY';self.h.seed_turns(study=False);self.assertEqual(self.h.summarize(study=False),'committed')
        self.server=new();self.sync=LayerSync(self.h.chat,self.server);self.packet=self.sync.exchange({'snapshot':empty(self.sync.scope),'capabilities':['gernze-research-cache-v1']})['research'];self.src=self.packet['records'][0];self.src={k:v for k,v in self.src.items() if k!='body'}
        self.archive=PhoneResearchArchive(self.h.store.path,self.server,self.sync.scope);self.device=new();self.sid='source-check';self.r=receipt(self.server,self.sync.scope,self.sid,source=self.src);self.r['cache'].update(sequence=self.packet['sequence'],fingerprint=sha(encoded(self.packet)))
        self.b={'format':FORMAT,'serverId':self.server,'scope_id':self.sync.scope,'sessionId':self.sid,'baseStart':0,'start':0,'previous':ZERO,'turns':[turn(0,self.r)]}
    def test_current_source_metadata_verified_without_any_source_body(self):
        queries=[];original=sqlite3.connect
        def traced(*a,**kw):db=original(*a,**kw);db.set_trace_callback(queries.append);return db
        with patch('sqlite3.connect',traced):self.assertEqual(self.archive.source_status(self.r),'current')
        self.assertFalse(any(q.startswith('SELECT') and any(t in q for t in ('rc_summary_bodies','rc_bodies','rc_source_payloads')) for q in queries))
    def test_rejected_source_keeps_raw_but_marks_changed(self):
        self.archive.exchange(self.device,self.b)
        with self.h.store.connection() as db:db.execute('INSERT INTO rc_summary_reviews VALUES (?,?,?,?,?,?)',(self.src['id'],self.src['revision'],self.src['body_hash'],'reject','synthetic','2026-10-27T00:00:00Z'))
        self.assertEqual(self.archive.source_status(self.r),'changed');self.assertEqual(self.archive.raw(self.device,self.sid,0)['research'],self.r)
    def test_retired_original_marks_receipt_changed(self):
        self.h.store.retire_context('synthetic');self.assertEqual(self.archive.source_status(self.r),'changed')
    def test_service_capability_only_on_existing_research_journal(self):
        from layer_service import LayerService
        service=LayerService(self.h.store.path,self.server);self.assertEqual(service.info()['phoneResearchRaw'],FORMAT)
    def test_actual_authenticated_tls_route_and_wrong_peer_binding(self):
        import socket,ssl
        from publisher import Publisher
        root=Path(self.h.fixture.tmp.name) if hasattr(self.h.fixture,'tmp') else self.h.store.path.parent
        apk=root/'stage9-synthetic.apk';apk.write_bytes(b'synthetic-not-installable');raw=apk.read_bytes()
        manifest={'schemaVersion':1,'artifactId':new(),'packageName':'com.hecate.companion','versionCode':1,'versionName':'synthetic','size':len(raw),'sha256':sha(raw.decode()),'signerCertificateSha256':['a'*64],'minSdkVersion':24}
        with patch('publisher.private_host',lambda v:v):p=Publisher(root/'stage9-publisher',apk,manifest,'127.0.0.1',memory_path=self.h.store.path.with_name('companion-memory.sqlite3')).start()
        try:
            invitation=p.issue_invitation();ctx=ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(p.der))
            def request(path,body,auth=None):
                payload=encoded(body).encode('utf-8');headers=f'POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{p.port}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n'
                if auth:headers+='Authorization: Bearer '+auth['token']+'\r\nX-Hebao-Pairing: '+auth['pairingId']+'\r\n'
                def loopback(sock,address):
                    if address[0]!='127.0.0.1':raise AssertionError('external network prohibited')
                    return ORIGINAL_CONNECT(sock,address)
                with patch.object(socket.socket,'connect',loopback):
                    with socket.create_connection(('127.0.0.1',p.port),timeout=3) as sock:
                        with ctx.wrap_socket(sock,server_hostname='hebao.local') as tls:
                            tls.sendall((headers+'\r\n').encode()+payload);data=b''
                            while block:=tls.recv(65536):data+=block
                head,text=data.split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(text)
            self.assertEqual(request('/v1/raw/exchange',self.b)[0],401)
            code,auth=request('/v1/pair',{'serverId':invitation['serverId'],'deviceId':self.device,'pairingSecret':invitation['pairingSecret']});self.assertEqual(code,200)
            # Server identity is derived from the publisher, never trusted from payload.
            self.assertEqual(request('/v1/raw/exchange',self.b,auth)[0],409)
            b=copy.deepcopy(self.b);b['serverId']=p.server_id;b['scope_id']=str(uuid.uuid5(uuid.UUID(p.server_id),'gernze-layer-memory-v1'));b['turns'][0]['research']['cache'].update(serverId=p.server_id,scope_id=b['scope_id'])
            code,result=request('/v1/raw/exchange',b,auth);self.assertEqual(code,200);self.assertEqual(result['next'],1);self.assertEqual(result['serverId'],p.server_id)
            self.assertEqual(request('/v1/raw/exchange',b,auth)[1]['accepted'],0)
        finally:p.close()

if __name__=='__main__':unittest.main(verbosity=2)
