import copy,hashlib,json,queue,tempfile,threading,time,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from voice_module import VoiceModuleController
from scene_voice import SceneVoice

class Audio:
    def __init__(self):self.calls=[]
    def play(self,path):self.calls.append(Path(path))
    def stop(self):pass
class API:
    def __init__(self):self.enabled=False;self.calls=[];self.entered=threading.Event();self.release=threading.Event();self.block=False
    def get(self,feature):self.calls.append(('get',feature));return {'enabled':self.enabled,'endpoint':'','model':''}
    def chat(self,feature,messages):
        self.calls.append(('chat',feature));self.entered.set()
        if self.block:self.release.wait(2)
        return '你好。'
class Backend:
    def __init__(self,home):self.home=home;self._generation=0;self.calls=[];self.feature_apis=API();self.closed=False;self.entered=threading.Event();self.release=threading.Event();self.block=False
    def synthesize(self,text,**kw):
        self.calls.append((text,kw));self.entered.set()
        if self.block:self.release.wait(2)
        return {'path':str(self.home/'state/outputs/generated.wav'),'sha256':hashlib.sha256((self.home/'state/outputs/generated.wav').read_bytes()).hexdigest(),'selection':{k:v for k,v in kw.items() if not k.startswith('_')},'seconds':.1}
    def cancel(self):self._generation+=1;self.release.set()
    def close(self):self.closed=True;self.cancel();self.feature_apis.release.set()
class BridgeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.home=Path(tmp.name)
        group=[{'id':i,'label':i,'version':'v2Pro'} for i in ('voice_1','voice_2')]
        catalog={'gpt_options':group,'sovits_options':group,'references':[{'id':'ref'}],'defaults':{'gpt_id':'voice_2','sovits_id':'voice_2','reference_id':'ref'}}
        (self.home/'catalog.json').write_text(json.dumps(catalog),encoding='utf8')
        output=self.home/'state/outputs';output.mkdir(parents=True)
        with wave.open(str(output/'generated.wav'),'wb') as w:w.setparams((1,2,32000,0,'NONE',''));w.writeframes(b'\x01\x00'*3200)
        (self.home/'manifest.json').write_text(json.dumps({'version':1,'clips':[],'events':{}}))
        self.audio=Audio();self.allowed=True;self.volume=30;self.messages=queue.SimpleQueue();self.backends=[]
        voice=SceneVoice(self.home,backend=self.audio,enabled=lambda:self.allowed,volume=lambda:self.volume)
        self.pet=SimpleNamespace(voice=voice,ui_thread=threading.get_ident(),closing=False,_enqueue_command=self.messages.put)
        def factory(home):
            backend=Backend(home);self.backends.append(backend);return backend
        self.bridge=VoiceModuleController(self.pet,self.home,self.home/'user',home=self.home,factory=factory)
        self.addCleanup(self.bridge.close)
    def finish(self):
        self.bridge._worker.join(3);self.assertFalse(self.bridge._worker.is_alive());self.bridge.drain()
    def test_lazy_start_and_independent_persisted_choices(self):
        self.assertEqual(self.bridge.selection()['gpt_id'],'voice_2');self.assertEqual(self.backends,[])
        selected=self.bridge.set_selection(gpt_id='voice_1',sovits_id='voice_2',reference_id='ref')
        other=VoiceModuleController(self.pet,self.home,self.home/'user',home=self.home)
        self.assertEqual(other.selection(),selected)
        with self.assertRaises(ValueError):self.bridge.set_selection(gpt_id='unknown',sovits_id='voice_2',reference_id='ref')
        self.assertEqual(self.bridge.selection(),selected)
    def test_generated_audio_uses_desktop_channel_without_changing_fixed_library(self):
        self.bridge.speak_text('你好。');self.finish()
        self.assertEqual(len(self.audio.calls),1);self.assertEqual(self.pet.voice.owner,'voice_module');self.assertEqual(self.pet.voice.clips,{})
        self.assertEqual(self.bridge.status['state'],'played')
    def test_generate_only_while_muted_does_not_autoplay(self):
        self.allowed=False
        with self.assertRaises(RuntimeError):self.bridge.speak_text('你好。')
        self.assertEqual(self.backends,[])
        self.bridge.speak_text('你好。',play=False);self.finish();self.assertEqual(self.audio.calls,[]);self.assertEqual(self.bridge.status['state'],'ready')
    def test_muted_between_request_and_completion_discards_playback(self):
        backend=self.bridge._get_backend();backend.block=True
        self.bridge.speak_text('你好。');self.assertTrue(backend.entered.wait(1));self.allowed=False;backend.release.set();self.finish()
        self.assertEqual(self.audio.calls,[])
    def test_cancel_invalidates_completed_and_inflight_results(self):
        backend=self.bridge._get_backend();backend.block=True
        self.bridge.speak_text('你好。');self.assertTrue(backend.entered.wait(1));self.bridge.cancel();self.finish()
        self.assertEqual(self.audio.calls,[]);self.assertEqual(self.bridge.status['state'],'cancelled')
    def test_busy_rejects_instead_of_queueing(self):
        backend=self.bridge._get_backend();backend.block=True;self.bridge.speak_text('你好。')
        with self.assertRaises(RuntimeError):self.bridge.speak_text('第二句。')
        backend.release.set();self.finish();self.assertEqual(len(backend.calls),1)
    def test_dialogue_uses_only_voice_feature_and_cancel_never_starts_tts(self):
        backend=self.bridge._get_backend()
        with self.assertRaises(RuntimeError):self.bridge.dialogue([{'role':'user','content':'你好'}])
        api=backend.feature_apis;api.enabled=True;api.block=True
        self.bridge.dialogue([{'role':'user','content':'你好'}]);self.assertTrue(api.entered.wait(1));self.bridge.cancel();api.release.set();self.finish()
        self.assertEqual(backend.calls,[]);self.assertTrue(all(f=='voice_dialogue' for _,f in api.calls));self.assertEqual(self.audio.calls,[])
    def test_dialogue_reply_generates_using_selection_snapshot(self):
        backend=self.bridge._get_backend();backend.feature_apis.enabled=True;backend.block=True
        self.bridge.dialogue([{'role':'user','content':'你好'}]);self.assertTrue(backend.entered.wait(1))
        self.bridge.set_selection(gpt_id='voice_1',sovits_id='voice_1',reference_id='ref');backend.release.set();self.finish()
        self.assertEqual(backend.calls[0][1]['gpt_id'],'voice_2');self.assertEqual(self.bridge.last_result['text'],'你好。')
    def test_wrong_thread_cannot_drive_ui(self):
        errors=[]
        def work():
            try:self.bridge.drain()
            except RuntimeError:errors.append(True)
        t=threading.Thread(target=work);t.start();t.join();self.assertEqual(errors,[True])
    def test_close_invalidates_late_result_and_closes_own_backend(self):
        backend=self.bridge._get_backend();backend.block=True;self.bridge.speak_text('你好。');self.bridge.close();self.finish()
        self.assertTrue(backend.closed);self.assertEqual(self.audio.calls,[]);self.assertEqual(self.bridge.status['state'],'closed')
    def test_output_outside_registered_directory_or_wrong_hash_never_plays(self):
        path=self.home/'state/outputs/generated.wav';digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertFalse(self.pet.voice.play_generated(path,output_root=self.home/'other',sha256=digest,identifier='x'))
        self.assertFalse(self.pet.voice.play_generated(path,output_root=path.parent,sha256='0'*64,identifier='x'));self.assertEqual(self.audio.calls,[])
    def test_generated_response_does_not_interrupt_grab_or_preview(self):
        self.pet.voice.current='drag';self.pet.voice.priority=4;self.pet.voice.until=time.monotonic()+10
        self.bridge.speak_text('你好。');self.finish();self.assertEqual(self.audio.calls,[]);self.assertEqual(self.pet.voice.current,'drag')
if __name__=='__main__':unittest.main()
