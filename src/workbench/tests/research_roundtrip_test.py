"""One isolated round trip across the real desktop host, TLS and phone storage.

Set GERNZE_TEST_NODE and GERNZE_TEST_NODE_MODULES to a Node runtime and a
node_modules directory containing Playwright. No personal profile is opened.
Only the model/key interfaces, persona/core and automatic scheduler are fake.
The tiny control HTTP server below is a fixture, never a product endpoint.
"""
import hashlib,json,os,re,secrets,socket,ssl,subprocess,tempfile,threading,unittest,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen
from unittest.mock import patch

from workbench import companion_chat as cc,server
from workbench.context_manager import ContextManager
from workbench.encounter_composition import create_desktop_chat
from workbench.memory_layers import MemoryLayers
from workbench.layer_sync import empty
from workbench.phone_research_archive import PhoneResearchArchive
from research_context_test import Keys,HTTP
from research_summaries_test import Worker
from phone_research_review_test import Adapter
from publisher import Publisher


@unittest.skipUnless(os.environ.get('GERNZE_RESEARCH_ROUNDTRIP')=='1','explicit isolated browser/TLS acceptance only')
class ResearchRoundtripTests(unittest.TestCase):
    evidence=[]
    def setUp(self):
        self.live=Path(os.environ.get('GERNZE_TEST_SOURCE',Path(__file__).resolve().parents[3]))
        self.overlay=Path(os.environ.get('GERNZE_TEST_OVERLAY',self.live))
        self.node=os.environ.get('GERNZE_TEST_NODE','node')
        self.temp=tempfile.TemporaryDirectory(prefix='gernze-roundtrip-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.http=HTTP();self.worker=Worker();self.worker.text='SYNTHETIC_DESKTOP_ROOT'
        original_connect=socket.socket.connect
        def local_connect(sock,address):
            if address[0]!='127.0.0.1':raise AssertionError('non-loopback network prohibited')
            return original_connect(sock,address)
        def make_chat(path,**kwargs):return create_desktop_chat(path,keys=Keys(),opener=self.http,**kwargs)
        core=lambda:{'schemaVersion':1,'entries':[]}
        for item in [patch.object(socket.socket,'connect',local_connect),patch.object(cc,'system_prompt',return_value='合成人设，不是真实私人设定。'),
                     patch.object(cc,'MemoryLayers',side_effect=lambda store:MemoryLayers(store,core_loader=core)),
                     patch.object(server,'create_desktop_chat',side_effect=make_chat),patch.object(server.DesktopMemoryReview,'start',return_value=None),
                     patch('layer_service.load_core',side_effect=core),patch('publisher.private_host',lambda v:v)]:
            item.start();self.addCleanup(item.stop)
        self.host=None;self.publisher=None;self.control=None;self.addCleanup(self.close)
        self.host=self.open_host(self.root/'default',False)
        with self.host.chat.store.read_connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_phone_summary_meta'").fetchone())
        self.assertFalse(self.host.study_chat.status()['available']);self.close_host()
        self.host=self.open_host(self.root/'enabled',True)
        self.host.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'synthetic'})
        self.host.chat.layers.configure({'summaryEnabled':False,'summaryDays':1,'reviewDays':None})
        self.source=self.host.chat.store.catalog.create_source('web','SYNTHETIC_EXTERNAL_ORIGINAL')
        self.entry=self.host.chat.store.catalog.add_entry('SYNTHETIC_GENERAL_RESEARCH',[self.source],facets=('encounter',))
        course=self.host.chat.store.catalog.create_source('course','SYNTHETIC_COURSE_ORIGINAL',courses=(str(uuid.uuid4()),))
        self.host.chat.store.catalog.add_entry('SYNTHETIC_COURSE_DO_NOT_SEND',[course])
        for i in range(9):
            rid=str(uuid.uuid4())
            result=self.desktop('chat.research.reply',{'text':'合成研究 '+str(i),'request_id':rid,
                                'materials':[{'id':self.entry[0],'revision':self.entry[1]}]})
            self.assertTrue(result['text'])
        self.assertEqual(len(self.http.requests),9)
        self.assertTrue(all('SYNTHETIC_GENERAL_RESEARCH' in json.dumps(r) for r in self.http.requests))
        self.assertNotIn('SYNTHETIC_COURSE_DO_NOT_SEND',json.dumps(self.http.requests))
        self.host.chat.layers.configure({'summaryEnabled':True,'summaryDays':1,'reviewDays':None})
        with self.host.chat.store.connection() as db:db.execute("UPDATE lc_sessions SET created_at='2000-01-01T00:00:00Z'")
        self.assertEqual(self.summarize(),'committed')
        self.host.memory_reviewer.adapter=Adapter()
        self.assertEqual(self.host.memory_reviewer.run(force=True)['status'],'completed')
        apk=self.root/'synthetic.apk';apk.write_bytes(b'NOT_AN_INSTALLABLE_APK');self.apk=apk
        self.manifest={'schemaVersion':1,'artifactId':str(uuid.uuid4()),'packageName':'com.hecate.companion','versionCode':1,'versionName':'synthetic',
                       'size':apk.stat().st_size,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),'signerCertificateSha256':['a'*64],'minSdkVersion':24}
        self.start_publisher()
        self.assertEqual(self.tls('/v1/layers/info',authenticated=False)[0],401)
        invite=self.publisher.issue_invitation();self.device=str(uuid.uuid4())
        code,self.auth=self.tls('/v1/pair',{'serverId':invite['serverId'],'deviceId':self.device,'pairingSecret':invite['pairingSecret']},authenticated=False);self.assertEqual(code,200)
        code,self.info=self.tls('/v1/layers/info');self.assertEqual(code,200);self.assertEqual(self.info['researchCacheV2'],'gernze-research-cache-v2')
        self.owner=self.host.chat.store.owner;self.calls=[];self.control_key=secrets.token_hex(24)
    def open_host(self,path,research):
        host=server.WorkbenchServer(path,research_enabled=research)
        self.thread=threading.Thread(target=host.serve,daemon=True);self.thread.start();return host
    def close_host(self):
        if self.host:
            self.host.stop();self.thread.join(3);self.host.server_close();self.host=None
    def start_publisher(self):
        self.publisher=Publisher(self.root/'publisher',self.apk,self.manifest,'127.0.0.1',memory_path=self.root/'enabled/workbench/companion-memory.sqlite3').start()
    def close(self):
        if self.control:self.control.shutdown();self.control.server_close();self.control=None
        if self.publisher:self.publisher.close();self.publisher=None
        self.close_host()
    def desktop(self,command,params):
        request=Request(self.host.origin+'/api/call',data=json.dumps({'command':command,'params':params}).encode(),
                        headers={'Authorization':'Bearer '+self.host.token,'Content-Type':'application/json'},method='POST')
        with urlopen(request,timeout=10) as response:return json.load(response)['result']
    def tls(self,path,body=None,authenticated=True):
        context=ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(self.publisher.der))
        payload=json.dumps(body).encode() if body is not None else b''
        headers=f'{"POST" if body is not None else "GET"} {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.publisher.port}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n'
        if authenticated:headers+='Authorization: Bearer '+self.auth['token']+'\r\nX-Hebao-Pairing: '+self.auth['pairingId']+'\r\n'
        with socket.create_connection(('127.0.0.1',self.publisher.port),timeout=5) as sock:
            with context.wrap_socket(sock,server_hostname='hebao.local') as tls:
                tls.sendall(headers.encode()+b'\r\n'+payload);answer=b''
                while block:=tls.recv(65536):answer+=block
        head,value=answer.split(b'\r\n\r\n',1);return int(head.split()[1]),json.loads(value)
    def summarize(self):
        manager=ContextManager(summarizer=self.worker,keep_recent=6,batch_size=3,min_batch=3,summary_timeout=2,summary_output_limit=500)
        chat=self.host.chat
        with chat.research_provider.request_scope('合成摘要触发',str(uuid.uuid4()),chat.store.session_id,'user'):
            return manager.summarize(chat.store,chat.store.session_id)
    def dispatch(self,op,body):
        if op in ('layers','raw'):
            code,result=self.tls('/v1/'+('layers' if op=='layers' else 'raw')+'/exchange',body)
            self.assertEqual(code,200,result);self.calls.append(op);return result
        if op=='derive':
            archive=PhoneResearchArchive(self.host.chat.store.path,self.publisher.server_id,self.info['scope_id'])
            self.assertEqual(len(archive.metadata()),12)
            with archive.connection(True) as db:db.execute("UPDATE pr_receipts SET received_at='2000-01-01T00:00:00Z'")
            self.worker.text='SYNTHETIC_PHONE_DERIVED';self.assertEqual(self.summarize(),'committed')
            result=self.host.memory_reviewer.run(force=True);self.assertEqual(result['status'],'completed',result)
            self.assertEqual(result['researchTypes'],{'desktop':0,'phone':1});self.assertEqual(result['userFactsWritten'],0)
            self.assertEqual(self.host.chat.store.owner,self.owner)
            return result
        if op=='restart':
            self.publisher.close();self.publisher=None;self.close_host()
            self.host=self.open_host(self.root/'enabled',True);self.start_publisher()
            self.assertEqual(self.tls('/v1/layers/info')[0],200)
            archive=PhoneResearchArchive(self.host.chat.store.path,self.publisher.server_id,self.info['scope_id'])
            self.assertEqual(len(archive.metadata()),12)
            with self.host.chat.store.read_connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM rc_phone_summary_meta').fetchone()[0],1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM rc_summary_reviews WHERE status='supported'").fetchone()[0],2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            return {'reopened':True}
        if op=='withdraw':
            self.host.chat.store.catalog.change_source(*self.source,state='withdrawn')
            archive=PhoneResearchArchive(self.host.chat.store.path,self.publisher.server_id,self.info['scope_id'])
            raw=archive.raw(self.device,body['sessionId'],0);self.assertEqual(archive.source_status(raw['research']),'changed')
            return {'rawKept':len(archive.metadata())==12,'state':'changed'}
        raise AssertionError('unknown fixture operation')
    def test_desktop_phone_review_restart_and_withdrawal_roundtrip(self):
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,status,value,mime='application/json'):
                data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path=='/':return self.respond(200,b'<!doctype html><meta charset="utf-8"><div id="host"></div>','text/html; charset=utf-8')
                if self.path=='/fixture':return self.respond(200,{'binding':{'serverId':fixture.publisher.server_id,'scope_id':fixture.info['scope_id']},'snapshot':empty(fixture.info['scope_id']),'key':fixture.control_key})
                name='src/workbench/chat-protocol.json' if self.path=='/src/workbench/chat-protocol.json' else 'mobile/'+self.path[1:] if re.fullmatch(r'/(src|tests)/[\w./-]+',self.path) and '..' not in self.path else None
                if name:
                    candidate=fixture.overlay/name;path=candidate if candidate.is_file() else fixture.live/name
                    if path.is_file():return self.respond(200,path.read_bytes(),'application/json' if path.suffix=='.json' else 'text/javascript')
                self.respond(404,{'error':'fixture_not_found'})
            def do_POST(self):
                if self.headers.get('Authorization')!='Bearer '+fixture.control_key:return self.respond(403,{'error':'fixture_auth'})
                try:
                    n=int(self.headers.get('Content-Length',0));assert 0<n<=600000
                    result=fixture.dispatch(self.path.removeprefix('/fixture/'),json.loads(self.rfile.read(n)));self.respond(200,result)
                except Exception as e:self.respond(500,{'error':type(e).__name__,'message':str(e)})
        self.control=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.control.serve_forever,daemon=True).start()
        runner=self.overlay/'mobile/tests/run-research-roundtrip.cjs'
        if not runner.exists():runner=self.live/'mobile/tests/run-research-roundtrip.cjs'
        result=subprocess.run([self.node,str(runner),'http://127.0.0.1:'+str(self.control.server_port)],capture_output=True,text=True,encoding='utf-8',timeout=100)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        browser=json.loads(result.stdout);self.assertTrue(browser['success']);self.assertEqual(browser['checkpoints'],14)
        with self.host.chat.store.read_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_approved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lm_working').fetchone()[0],0)
        self.evidence.append({'scenario':'desktop-phone-review-restart-withdrawal','browser':browser,'pairedTlsCalls':self.calls,
                              'desktopHttpRequests':len(self.http.requests),'summaryCalls':len(self.worker.calls),'realModelCalls':0,'defaultProfileResearchDisabled':True})

if __name__=='__main__':unittest.main(verbosity=2)
