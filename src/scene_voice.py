
"""Approved local WAVs only. Single asynchronous Windows channel, no audio loop."""
from pathlib import Path
import json,hashlib,random,time,wave,array,sys,tempfile
from datetime import datetime

def validate_volume(value):
    if type(value) is not int or not 0<=value<=100:raise ValueError('volume must be integer 0..100')
    return value

def volume_wav(source,cache_dir,percent):
    """Attenuate PCM samples only; original, timing and pitch remain unchanged."""
    percent=validate_volume(percent);source=Path(source)
    if percent==100:return source
    raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    cache=Path(cache_dir);cache.mkdir(parents=True,exist_ok=True)
    target=cache/(digest+'-pcm16-v1-'+str(percent)+'.wav')
    if target.is_file():return target
    with wave.open(str(source),'rb') as w:
        params=w.getparams()
        if w.getsampwidth()!=2 or w.getcomptype()!='NONE':raise ValueError('volume requires PCM16 WAV')
        samples=array.array('h',w.readframes(w.getnframes()))
    if sys.byteorder!='little':samples.byteswap()
    scaled=array.array('h',(round(value*percent/100) for value in samples))
    if sys.byteorder!='little':scaled.byteswap()
    pending=target.with_suffix('.tmp')
    try:
        with wave.open(str(pending),'wb') as w:w.setparams(params);w.writeframes(scaled.tobytes())
        pending.replace(target)
    finally:
        if pending.exists():pending.unlink()
    return target

class WaveBackend:
    def __init__(self,*,volume=lambda:100,cache_dir=None):
        import winsound
        self.api=winsound;self.volume=volume
        self.cache_dir=Path(cache_dir) if cache_dir is not None else Path(tempfile.gettempdir())/'HecateSceneVoiceCache'
    def play(self,path):
        path=volume_wav(path,self.cache_dir,validate_volume(self.volume()))
        w=self.api
        w.PlaySound(str(path),w.SND_FILENAME|w.SND_ASYNC|w.SND_NODEFAULT)
    def stop(self):
        self.api.PlaySound(None,0)

class SceneVoice:
    OWNERS={'workbench':'workbench','reading_start':'reading','reading_click':'reading','sleep':'sleep','wake':'sleep','drag':'drag','slide':'slide'}
    PRIORITY={'workbench':3,'reading_start':1,'reading_click':3,'sleep':1,'wake':2,'drag':4,'slide':4,'preview':5}
    def __init__(self,root,*,enabled=lambda:True,logger=lambda *a,**k:None,backend=None,volume=lambda:100,cache_dir=None,clock=time.monotonic,now=datetime.now,choose=random.choice,bindings=None):
        self.root=Path(root).resolve();self.enabled=enabled;self.log=logger;self.volume=volume;self.backend=backend or WaveBackend(volume=volume,cache_dir=cache_dir);self.clock=clock;self.now=now;self.choose=choose
        self.default_events={};self.binding_overrides={}
        self.closed=False;self.current=None;self.until=0.;self.owner=None;self.priority=0;self.last={};self.clips={};self.events={};self.held_back={}
        try:
            data=json.loads((self.root/'manifest.json').read_text(encoding='utf-8'))
            if data['version']!=1:raise ValueError('voice manifest version')
            self.held_back=data.get('held_back',{})
            for clip in data['clips']:
                try:
                    path=(self.root/clip['file']).resolve()
                    if self.root not in path.parents or path.suffix.lower()!='.wav':raise ValueError('invalid voice path')
                    if clip['id'] in self.clips:raise ValueError('duplicate voice id')
                    if not 0<float(clip['seconds'])<20:raise ValueError('invalid voice duration')
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=clip['sha256']:raise ValueError('voice checksum')
                    with wave.open(str(path),'rb') as w:
                        if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=32000 or w.getcomptype()!='NONE':raise ValueError('voice WAV format')
                        if abs(w.getnframes()/w.getframerate()-clip['seconds'])>.002:raise ValueError('voice duration mismatch')
                    self.clips[clip['id']]={**clip,'path':path}
                except (OSError,ValueError,KeyError,TypeError,wave.Error) as exc:self.log('voice_clip_unavailable',clip=clip.get('id'),reason=str(exc))
            self.events={key:[c for c in ids if c in self.clips and c not in self.held_back] for key,ids in data['events'].items()}
        except (OSError,ValueError,KeyError,TypeError) as exc:self.log('voice_unavailable',reason=str(exc))
        self.default_events={key:list(ids) for key,ids in self.events.items()}
        accepted={}
        if isinstance(bindings,dict):
            for key,ids in bindings.items():
                try:accepted.update(self.validate_bindings({key:ids}))
                except ValueError:self.log('voice_binding_ignored',event_name=str(key))
        self.apply_bindings(accepted)
    def validate_bindings(self,bindings):
        if not isinstance(bindings,dict):raise ValueError('语音触发设置必须是对象')
        result={}
        for key,ids in bindings.items():
            if key not in TRIGGER_LABELS:raise ValueError('未知语音触发场景')
            if not isinstance(ids,list) or len(ids)>len(self.clips):raise ValueError('录音选择无效')
            if any(not isinstance(i,str) or i not in self.clips for i in ids):raise ValueError('录音未通过检查或已经移除')
            if len(set(ids))!=len(ids):raise ValueError('录音选择重复')
            result[key]=list(ids)
        return result
    def apply_bindings(self,bindings):
        accepted=self.validate_bindings(bindings)
        self.events={key:list(ids) for key,ids in self.default_events.items()}
        self.events.update(accepted)
        self.binding_overrides=accepted
    def _active(self):
        return self.current is not None and self.clock()<self.until
    def emit(self,event):
        if self.closed or not self.enabled():return False
        if event not in self.PRIORITY or event=='preview':return False
        key=event
        if event=='wake':
            hour=self.now().hour;key='wake_morning' if hour<12 else 'wake_afternoon' if hour<17 else 'wake_evening'
        ids=self.events.get(key,[])
        if not ids:return False
        now=self.clock()
        # Fast repeated commands/clicks do not replay a clip; different actions can interrupt.
        if now-self.last.get(event,-1e10)<.35:return False
        if self._active() and self.PRIORITY[event]<self.priority:return False
        identifier=self.choose(ids)
        if self._play(identifier,self.OWNERS[event],self.PRIORITY[event]):
            self.last[event]=now;return True
        return False
    def preview(self,identifier):
        if self.closed or not self.enabled():return False
        return self._play(identifier,'preview',self.PRIORITY['preview'])
    def _play(self,identifier,owner,priority):
        clip=self.clips.get(identifier)
        if clip is None:return False
        return self._play_path(identifier,clip['path'],clip['seconds'],owner,priority,clip.get('model_code'))
    def play_generated(self,path,*,output_root,sha256,identifier):
        if self.closed or not self.enabled():return False
        if self._active() and self.priority>3:return False
        try:
            path=Path(path).resolve();output_root=Path(output_root).resolve()
            if output_root not in path.parents or path.suffix.lower()!='.wav':raise ValueError('generated path outside outputs')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=sha256:raise ValueError('generated checksum')
            with wave.open(str(path),'rb') as w:
                if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=32000 or w.getcomptype()!='NONE':raise ValueError('generated WAV format')
                seconds=w.getnframes()/w.getframerate()
                if not 0<seconds<=600:raise ValueError('generated duration')
            return self._play_path(identifier,path,seconds,'voice_module',3,None)
        except (OSError,ValueError,TypeError,wave.Error) as exc:
            self.log('generated_voice_rejected',error=type(exc).__name__);return False
    def _play_path(self,identifier,path,seconds,owner,priority,model):
        self.stop()
        if validate_volume(self.volume())==0:return False
        try:self.backend.play(path)
        except (OSError,RuntimeError) as exc:
            self.log('voice_play_failed',clip=identifier,error=type(exc).__name__);return False
        self.current=identifier;self.owner=owner;self.priority=priority;self.until=self.clock()+seconds
        self.log('voice_played',clip=identifier,owner=owner,model=model,seconds=seconds,volume_percent=self.volume(),local_only=True)
        return True
    def stop(self,owner=None):
        if owner is not None and owner!=self.owner:return
        if self.current is not None:
            try:self.backend.stop()
            except (OSError,RuntimeError) as exc:self.log('voice_stop_failed',error=type(exc).__name__)
            self.log('voice_stopped',clip=self.current,owner=self.owner)
        self.current=None;self.owner=None;self.until=0.;self.priority=0
    def close(self):
        self.stop();self.closed=True


TRIGGER_LABELS = {
    'workbench': '首次启动赫宝打开工作台，入场动画接住怀表约2.1秒时；同一进程不重播',
    'reading_start': '进入看书动作时，随机播放其中一条',
    'reading_click': '看书时单击赫宝，抬脸回应时随机播放',
    'sleep': '进入抱帽睡觉动作时',
    'wake_morning': '从睡觉醒来时，本地时间0:00—11:59',
    'wake_afternoon': '从睡觉醒来时，本地时间12:00—16:59',
    'wake_evening': '从睡觉醒来时，本地时间17:00—23:59',
    'drag': '开始鼠标抓取拖动时，随机播放其中一条',
    'slide': '松手后触发惯性滑行时，随机播放其中一条',
}


def fixed_voice_rows(voice):
    """Describe the actual validated runtime bindings, without changing them."""
    rows = []
    for identifier, clip in voice.clips.items():
        triggers = [TRIGGER_LABELS.get(key, key) for key, ids in voice.events.items() if identifier in ids]
        pending = identifier in voice.held_back
        if triggers:
            description = '\n'.join(triggers)
            state = '已接入触发'
        else:
            state = '仅供手动试听'
            description = '尚未自动触发。'
        if pending and not triggers:
            description += (' 开场早中晚时段尚未确定。' if identifier.startswith('WB_OPEN_02') else ' 特殊睡醒开场的呼吸声和镜头尚未完成。')
        rows.append({'id':identifier, 'text':clip.get('text') or '受惊短气声',
                     'scene':clip.get('scene') or '固定语音', 'state':state,
                     'trigger':description, 'seconds':clip['seconds'],
                     'model':'第一套' if clip.get('model_code')=='A' else '第二套' if clip.get('model_code')=='B' else '已认可录音'})
    return rows


def open_voice_controls(pet):
    from fixed_voice_window import open_fixed_voice_window
    return open_fixed_voice_window(pet)
