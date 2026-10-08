
import json,hashlib,tempfile,unittest,wave
from pathlib import Path
from datetime import datetime
from scene_voice import SceneVoice

class Backend:
    def __init__(self):self.played=[];self.stops=0;self.failed=False
    def play(self,p):
        if self.failed:raise RuntimeError('audio device unavailable')
        self.played.append(Path(p).name)
    def stop(self):self.stops+=1

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        with wave.open(str(self.root/'one.wav'),'wb') as w:w.setparams((1,2,32000,0,'NONE',''));w.writeframes(b'\x01\x00'*3200)
        h=hashlib.sha256((self.root/'one.wav').read_bytes()).hexdigest()
        self.ids=['welcome','read','click','sleep','morning','afternoon','evening','drag','slide','held']
        self.data={'version':1,'clips':[{'id':i,'file':'one.wav','sha256':h,'seconds':.1,'model_code':'B'} for i in self.ids],
        'held_back':{'held':'not specified'},'events':{'workbench':['welcome'],'reading_start':['read'],'reading_click':['click'],'sleep':['sleep'],'wake_morning':['morning'],'wake_afternoon':['afternoon'],'wake_evening':['evening'],'drag':['drag'],'slide':['slide'],'held':['held']}}
        self.write();self.b=Backend();self.time=10.;self.allowed=True;self.hour=12
        self.v=self.new()
    def write(self):(self.root/'manifest.json').write_text(json.dumps(self.data),encoding='utf-8')
    def new(self):return SceneVoice(self.root,backend=self.b,clock=lambda:self.time,now=lambda:datetime(2026,10,6,self.hour),enabled=lambda:self.allowed,choose=lambda ids:ids[0])
    def test_silent_events_never_replay_later(self):
        self.allowed=False;self.assertFalse(self.v.emit('reading_start'));self.allowed=True;self.assertEqual(self.b.played,[]);self.assertTrue(self.v.emit('reading_start'))
    def test_rapid_same_event_is_deduplicated(self):
        self.assertTrue(self.v.emit('reading_click'));self.assertFalse(self.v.emit('reading_click'));self.time+=.36;self.assertTrue(self.v.emit('reading_click'));self.assertEqual(len(self.b.played),2)
    def test_drag_interrupts_and_uses_single_channel(self):
        self.v.emit('reading_start');self.assertTrue(self.v.emit('drag'));self.assertEqual(self.b.stops,1);self.assertEqual(self.v.owner,'drag')
    def test_background_action_does_not_interrupt_workbench(self):
        self.v.emit('workbench');self.assertFalse(self.v.emit('sleep'));self.assertEqual(len(self.b.played),1)
    def test_finished_clip_no_longer_blocks_background(self):
        self.v.emit('workbench');self.time+=1;self.assertTrue(self.v.emit('sleep'))
    def test_stop_owner_does_not_stop_another_scene(self):
        self.v.emit('workbench');self.v.stop('reading');self.assertEqual(self.b.stops,0);self.v.stop('workbench');self.assertEqual(self.b.stops,1)
    def test_close_cannot_play_again(self):
        self.v.emit('workbench');self.v.close();self.assertFalse(self.v.preview('welcome'));self.assertFalse(self.v.emit('drag'));self.assertIsNone(self.v.current)
    def test_wake_boundaries(self):
        for hour,name in [(0,'morning'),(11,'morning'),(12,'afternoon'),(16,'afternoon'),(17,'evening'),(23,'evening')]:
            self.hour=hour;self.time+=1;self.assertTrue(self.v.emit('wake'));self.assertEqual(self.v.current,name)
    def test_unknown_event_does_not_choose_a_replacement(self):
        self.assertFalse(self.v.emit('foot_sway'));self.assertFalse(self.v.emit('headpat'));self.assertEqual(self.b.played,[])
    def test_held_clip_is_preview_only(self):
        self.assertEqual(self.v.events['held'],[]);self.assertTrue(self.v.preview('held'))
    def test_corrupt_clip_is_unavailable(self):
        self.data['clips'][0]['sha256']='0'*64;self.write();v=self.new();self.assertNotIn('welcome',v.clips);self.assertFalse(v.emit('workbench'))
    def test_external_path_is_rejected(self):
        self.data['clips'][0]['file']='../one.wav';self.write();v=self.new();self.assertNotIn('welcome',v.clips)
    def test_device_failure_does_not_break_actions(self):
        self.b.failed=True;self.assertFalse(self.v.emit('reading_start'));self.assertIsNone(self.v.current)
    def test_invalid_wav_is_rejected(self):
        (self.root/'one.wav').write_bytes(b'not a wave');h=hashlib.sha256((self.root/'one.wav').read_bytes()).hexdigest()
        for c in self.data['clips']:c['sha256']=h
        self.write();v=self.new();self.assertEqual(v.clips,{})
    def test_stop_then_enable_never_resumes_old_clip(self):
        self.v.emit('workbench');self.v.stop();self.allowed=False;self.v.emit('drag');self.allowed=True;self.assertIsNone(self.v.current);self.assertEqual(len(self.b.played),1)
if __name__=='__main__':unittest.main()
