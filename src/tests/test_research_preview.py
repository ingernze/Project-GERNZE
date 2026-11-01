"""Dedicated preview profiles and scoped fake credentials; no real keys/data."""
import hashlib,http.client,io,json,os,sqlite3,subprocess,sys,tempfile,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
import research_preview as preview
from contextlib import closing,redirect_stdout
from workbench import companion_chat as cc
from workbench.encounter_composition import create_desktop_chat
from workbench.memory_layers import MemoryLayers
from workbench.research_books import ResearchBooks
from workbench.server import WorkbenchServer
from research_context_test import HTTP


class Keys:
    def __init__(self):self.values={};self.calls=[]
    def get(self,target):self.calls.append(('get',target));return self.values.get(target,'')
    def set(self,target,value):self.calls.append(('set',target));self.values[target]=value
    def delete(self,target):self.calls.append(('delete',target));self.values.pop(target,None)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.profile=self.root/'research';self.keys=Keys();self.http=HTTP()
        core=lambda:{'schemaVersion':1,'entries':[]}
        def chat(path,**kwargs):return create_desktop_chat(path,opener=self.http,**kwargs)
        for item in [patch.object(cc,'system_prompt',return_value='合成人设'),patch.object(cc,'MemoryLayers',side_effect=lambda store:MemoryLayers(store,core_loader=core)),
                     patch('workbench.server.create_desktop_chat',side_effect=chat),
                     patch('workbench.server.STATIC',Path(os.environ.get('GERNZE_TEST_SOURCE',Path(__file__).resolve().parents[2]))/'src/workbench/static')]:
            item.start();self.addCleanup(item.stop)
    def open(self,**kwargs):return preview.preview_server(self.profile,keys_backend=self.keys,**kwargs)
    def test_existing_unmarked_profile_is_not_modified(self):
        self.profile.mkdir();file=self.profile/'chat.json';file.write_bytes(b'ORIGINAL_PROFILE')
        with self.assertRaises(ValueError):preview.prepare_profile(self.profile)
        self.assertEqual(file.read_bytes(),b'ORIGINAL_PROFILE');self.assertFalse((self.profile/preview.MARKER).exists())
    def test_marker_identity_is_stable_but_relative_and_unknown_profiles_refused(self):
        first=preview.prepare_profile(self.profile);self.assertEqual(preview.prepare_profile(self.profile),first)
        with self.assertRaises(ValueError):preview.prepare_profile('relative-preview')
        (self.profile/preview.MARKER).write_text('{"format":"unknown","id":"bad"}',encoding='utf-8')
        with self.assertRaises(ValueError):preview.prepare_profile(self.profile)
    def test_copied_old_journal_is_refused_without_migration(self):
        preview.prepare_profile(self.profile);file=self.profile/'workbench/chat-sessions.sqlite3';file.parent.mkdir()
        with closing(sqlite3.connect(file)) as db:
            db.execute('PRAGMA user_version=1');db.execute('CREATE TABLE keep(value)');db.execute("INSERT INTO keep VALUES ('ORIGINAL')");db.commit()
        before=hashlib.sha256(file.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            with self.open():pass
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),before)
    def test_same_endpoint_key_reads_writes_and_deletes_stay_in_preview_namespace(self):
        path,ident=preview.prepare_profile(self.profile);keys=preview.PreviewKeys(path,ident,self.keys);target='Hecate/CompanionChat/default'
        self.keys.values[target]='LIVE_KEY';self.assertEqual(keys.get(target),'');keys.set(target,'PREVIEW_KEY');self.assertEqual(keys.get(target),'PREVIEW_KEY');keys.delete(target)
        self.assertEqual(self.keys.values,{target:'LIVE_KEY'});self.assertTrue(all(t!=target for _,t in self.keys.calls))
    def test_cloned_marker_at_another_path_has_a_different_key_namespace(self):
        path,ident=preview.prepare_profile(self.profile);other=self.root/'other';other.mkdir();(other/preview.MARKER).write_bytes((path/preview.MARKER).read_bytes())
        self.assertNotEqual(preview.PreviewKeys(path,ident,self.keys).target('same'),preview.PreviewKeys(other,ident,self.keys).target('same'))
    def test_real_server_starts_research_with_review_paused_and_no_provider_calls(self):
        with self.open() as s:
            self.assertTrue(s.research_chat.status()['available']);self.assertTrue(s.research_preview)
            self.assertFalse(s.chat.config()['configured']);self.assertFalse(s.memory_reviewer.status()['enabled'])
            s.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'synthetic','key':'PREVIEW'})
            self.assertEqual(s.memory_reviewer.run(force=True)['status'],'disabled');self.assertEqual(self.http.requests,[])
            with s.chat.store.read_connection() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
    def test_startup_option_defaults_do_not_change_normal_host_key_targets(self):
        with patch('workbench.server.DesktopMemoryReview.start') as start:
            s=WorkbenchServer(self.root/'normal',chat_keys=self.keys)
            try:
                self.assertIsNone(s.chat.research_provider);self.assertIs(s.chat.keys,self.keys);start.assert_called_once()
                with s.chat.store.read_connection() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            finally:s.stop();s.server_close()
    def test_saved_connection_and_samples_survive_reopen_without_auto_review(self):
        with self.open(samples=True) as s:
            s.chat.configure({'enabled':True,'endpoint':'https://fixture.invalid/chat/completions','model':'synthetic','key':'PREVIEW'})
            ident=s.chat.store.owner;self.assertTrue(s.chat.config()['configured']);s.memory_reviewer.configure(True)
            rows=ResearchBooks(s.chat.store).groups()['groups'];self.assertEqual(sum(r['count'] for r in rows),2)
        with self.open(samples=True) as s:
            self.assertTrue(s.chat.config()['configured']);self.assertNotEqual(s.chat.store.owner,ident)
            self.assertFalse(s.memory_reviewer.status()['enabled']);self.assertEqual(self.http.requests,[])
            self.assertEqual(sum(r['count'] for r in ResearchBooks(s.chat.store).groups()['groups']),2)
    def test_reopening_samples_does_not_revive_withdrawn_source(self):
        with self.open(samples=True) as s:
            with s.chat.store.read_connection() as db:source=db.execute('SELECT id,revision FROM rc_sources LIMIT 1').fetchone()
            s.chat.store.catalog.change_source(*source,state='withdrawn')
        with self.open(samples=True) as s:
            with s.chat.store.read_connection() as db:self.assertEqual(db.execute('SELECT state FROM rc_sources WHERE id=?',(source[0],)).fetchone()[0],'withdrawn')
    def test_context_close_stops_scheduler(self):
        with self.open() as s:self.assertTrue(s.memory_reviewer.thread.is_alive())
        s.memory_reviewer.thread.join(2);self.assertFalse(s.memory_reviewer.thread.is_alive());self.assertTrue(s.closing)
    def test_preview_html_label_keeps_live_authenticated_transport(self):
        with self.open() as s:
            thread=threading.Thread(target=s.serve,daemon=True);thread.start()
            try:
                c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3);c.request('GET','/');r=c.getresponse();html=r.read().decode();c.close()
                self.assertIn('data-research-preview="true"',html);self.assertIn('研究测试版</title>',html);self.assertNotIn('data-preview="true"',html)
                c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3);c.request('POST','/api/call',json.dumps({'command':'chat.research.status','params':{}}),{'Authorization':'Bearer '+s.token,'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,200);self.assertTrue(json.loads(r.read())['result']['available']);c.close()
                with patch('mobile_update_launcher.open_publisher') as launch:
                    c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3);c.request('POST','/api/call',json.dumps({'command':'mobile_updates.open','params':{}}),{'Authorization':'Bearer '+s.token,'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,400);self.assertIn('原版',json.loads(r.read())['error']);c.close();launch.assert_not_called()
            finally:s.stop();thread.join(3)
    def test_profile_process_lock_is_held_for_runtime(self):
        code="""import os,sys
f=open(sys.argv[1],'a+b')
try:
 if os.name=='nt':
  import msvcrt
  f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
 else:
  import fcntl
  fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError:sys.exit(73)
sys.exit(0)
"""
        with self.open():
            r=subprocess.run([sys.executable,'-B','-c',code,str(self.profile/'preview.lock')],capture_output=True,timeout=5);self.assertEqual(r.returncode,73,r.stderr)
    def test_native_window_constructor_failure_still_releases_host_and_profile(self):
        created=[];original=preview.preview_server
        from contextlib import contextmanager
        @contextmanager
        def tracked(path,**kwargs):
            with original(path,keys_backend=self.keys) as s:created.append(s);yield s
        with patch.object(preview,'preview_server',tracked),patch.dict(sys.modules,{'workbench_window':types.SimpleNamespace(WorkbenchWindow=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic')))}),redirect_stdout(io.StringIO()):
            self.assertEqual(preview.main(['--profile',str(self.profile)]),1)
        self.assertTrue(created[0].closing)
        with self.open():pass
    def test_native_window_ready_and_exit_release_profile_without_exposing_session_url(self):
        original=preview.preview_server;windows=[]
        from contextlib import contextmanager
        @contextmanager
        def tracked(path,**kwargs):
            with original(path,keys_backend=self.keys) as s:yield s
        class Window:
            def __init__(self,*a,on_closed,**k):
                self.closed=False;self.on_closed=on_closed;self.ready=threading.Event();self.ready.set();self.error=None;self.hwnd=1;windows.append(self)
            def open(self,url):self.on_closed();return True
            def close(self):self.closed=True
        output=io.StringIO()
        with patch.object(preview,'preview_server',tracked),patch.dict(sys.modules,{'workbench_window':types.SimpleNamespace(WorkbenchWindow=Window)}),redirect_stdout(output):
            self.assertEqual(preview.main(['--profile',str(self.profile)]),0)
        self.assertTrue(windows[0].closed);self.assertNotIn('#session=',output.getvalue())
        with self.open():pass



class DesktopResearchHostTests(unittest.TestCase):
    setUp=PreviewTests.setUp
    def host(self,**kwargs):
        from workbench_host import WorkbenchHost
        resources=self.root/'resources';resources.mkdir(exist_ok=True)
        (resources/'handoff_status.json').write_text('{"id":"synthetic","records":[]}',encoding='utf-8')
        return WorkbenchHost(self.root/'ordinary',resources,lambda *a,**k:None,**kwargs)
    def scoped_keys(self):return patch.object(cc,'WindowsKeys',return_value=self.keys)
    def test_real_desktop_host_opt_in_and_close_reopen_release_thread_gate(self):
        callback=lambda event:None
        with self.scoped_keys():
            host=self.host(research_profile=self.profile,voice_notify=callback)
            try:
                first=host.open(launch_browser=False)
                self.assertTrue(first.research_preview);self.assertIs(first.voice_notify,callback)
                self.assertIs(first.entrance,host.entrance)
                self.assertFalse(first.memory_reviewer.status()['enabled'])
                self.assertTrue(first.research_chat.status()['available'])
                identity=preview.prepare_profile(self.profile)[1]
                host.close_service();self.assertFalse(host.worker.is_alive())
                second=host.open(launch_browser=False);self.assertIsNot(first,second)
                self.assertEqual(preview.prepare_profile(self.profile)[1],identity)
                self.assertEqual(self.http.requests,[])
            finally:host.close()
    def test_default_old_database_and_rollback_route_remain_ordinary_v1(self):
        with self.scoped_keys():
            ordinary=self.host();old=ordinary.open(launch_browser=False)
            path=old.chat.store.path;ordinary.close()
            with closing(sqlite3.connect(path)) as db:
                db.execute('create table preserved_marker(value text)');db.execute("insert into preserved_marker values ('UNCHANGED')");db.commit()
            original=path.read_bytes()
            research=self.host(research_profile=self.profile)
            try:research.open(launch_browser=False)
            finally:research.close()
            self.assertEqual(path.read_bytes(),original)
            rollback=self.host()
            try:
                server=rollback.open(launch_browser=False);self.assertIsNone(server.chat.research_provider)
                with server.chat.store.read_connection() as db:
                    self.assertEqual(db.execute('pragma user_version').fetchone()[0],1)
                    self.assertEqual(db.execute('select value from preserved_marker').fetchone()[0],'UNCHANGED')
            finally:rollback.close()
    def test_bad_research_profile_never_falls_back_or_modifies_old_directory(self):
        self.profile.mkdir();(self.profile/'existing.txt').write_text('KEEP',encoding='utf-8')
        with self.scoped_keys():
            host=self.host(research_profile=self.profile)
            try:
                with self.assertRaises(RuntimeError):host.open(launch_browser=False)
                self.assertFalse(host.worker.is_alive());self.assertIsNone(host.server)
                self.assertFalse((self.root/'ordinary/workbench').exists())
                self.assertEqual((self.profile/'existing.txt').read_text(encoding='utf-8'),'KEEP')
            finally:host.close()
    def test_same_or_relative_profile_is_refused_before_creating_a_writer(self):
        for profile in (self.root/'ordinary',Path('relative')):
            with self.assertRaises(ValueError):self.host(research_profile=profile)
        self.assertFalse((self.root/'ordinary').exists())
    def test_failed_browser_open_still_releases_research_worker_and_profile(self):
        with self.scoped_keys():
            host=self.host(research_profile=self.profile,opener=lambda url:False)
            try:
                with self.assertRaises(RuntimeError):host.open()
                self.assertFalse(host.worker.is_alive())
                with preview.preview_server(self.profile,keys_backend=self.keys) as server:
                    self.assertTrue(server.research_chat.status()['available'])
            finally:host.close()
    def test_native_window_uses_research_profile_and_keeps_normal_location(self):
        windows=[]
        class Window:
            def __init__(self,path,logger):self.path=path;self.on_closed=None;windows.append(self)
            def open(self,url):return True
            def close(self):pass
        with self.scoped_keys(),patch.dict(sys.modules,{'workbench_window':types.SimpleNamespace(WorkbenchWindow=Window)}):
            host=self.host(research_profile=self.profile)
            try:
                host.open();self.assertEqual(windows[0].path,self.profile)
                self.assertEqual(host.data_dir,self.root/'ordinary')
            finally:host.close()

if __name__=='__main__':unittest.main(verbosity=2)
