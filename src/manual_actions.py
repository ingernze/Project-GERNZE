"""Manual PNG actions with manifest timing and one owned timer."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageTk
from style_resources import make_photo

def load_manual_action(asset_dir,name,idle_image,idle_anchor):
    folder=(Path(asset_dir)/name).resolve()
    data=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    native=data.get('renderer')=='native_manual'
    if name not in ('sleep','headpat') or data.get('action')!=name or data.get('renderer') not in ('pixel','native_manual'):
        raise ValueError('Unsupported manual action')
    source_canvas=data.get('source_canvas') if native else data['canvas']
    if source_canvas!=list(idle_image.size) or data['anchor']!=list(idle_anchor):
        raise ValueError('Manual canvas or anchor differs from idle')
    if native and (name!='sleep' or data['canvas']!=[128,128]):
        raise ValueError('Invalid native action logical canvas')
    entries=data['frames']
    if not isinstance(entries,list) or not 1<=len(entries)<=120:
        raise ValueError('Invalid manual frame list')
    images=[];indices={};native_cache={}
    for entry in entries:
        filename=entry['file'];path=(folder/filename).resolve()
        if filename in indices or not path.is_relative_to(folder) or path.suffix.lower()!='.png':
            raise ValueError('Invalid manual frame path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('Manual frame checksum differs')
        digest=entry['sha256']
        if native and digest in native_cache:
            image=native_cache[digest]
        else:
            with Image.open(path) as im:
                if im.mode!='RGBA' or im.size!=idle_image.size:raise ValueError('Invalid manual frame format')
                image=im.copy()
            if native:native_cache[digest]=image
        if image.getchannel('A').getbbox() is None:raise ValueError('Empty manual frame')
        indices[filename]=len(images);images.append(image)
    phases={};keys=('enter','loop','exit') if name=='sleep' else ('play',)
    for key in keys:
        sequence=data['phases'][key]
        if not isinstance(sequence,list) or not 1<=len(sequence)<=120:raise ValueError('Invalid manual phase')
        phases[key]=[]
        for i,entry in enumerate(sequence):
            ms=entry['duration_ms']
            control=name=='headpat' and i in (0,len(sequence)-1)
            if type(ms) is not int or not (30<=ms<=10000 or ms==0 and control):
                raise ValueError('Invalid manual duration')
            phases[key].append((indices[entry['file']],ms))
    endpoints=[phases[keys[0]][0][0],phases[keys[-1]][-1][0]]
    if any(images[i].tobytes()!=idle_image.tobytes() for i in endpoints):
        raise ValueError('Manual endpoint differs from idle')
    if name=='sleep':
        seam=[phases['enter'][-1][0],phases['loop'][0][0],phases['exit'][0][0]]
        if len({images[i].tobytes() for i in seam})!=1:raise ValueError('Sleep phase seam differs')
    return data,images,phases

class ManualActionTrial:
    def __init__(self,pet,asset_dir):
        self.pet=pet;self.asset_dir=Path(asset_dir)
        self.active=False;self.job=None;self.name=None;self.phase=None;self.automatic=False
        self.index=None;self.step_index=0;self.finish_requested=False
        self.frames=[];self.photos={};self.phases={};self.resource=None
    def _notice(self,text):
        panel=getattr(self.pet,'action_controls',None)
        if panel is not None and panel.winfo_exists():panel.status.set(text)
    def start(self,name, *, automatic=False):
        if self.pet.closing or self.pet.drag_start is not None:return False
        if self.active and self.name==name:return False
        try:
            data,images,phases=load_manual_action(self.asset_dir,name,self.pet.frames[0][0],self.pet.manifest['foot_anchor'])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.pet._reset_idle();self.pet._schedule_next_frame();self.pet._schedule_reading()
            self._notice('素材不可用，已返回待机')
            self.pet.record_manual_event('manual_action_unavailable',action=name,reason=str(exc))
            return False
        self.pet.show();self.pet._reset_idle()
        self.resource=data;self.frames=images;self.phases=phases;self.photos={}
        self.name=name;self.active=True;self.finish_requested=False;self.automatic=automatic
        self._play_phase('enter' if name=='sleep' else 'play')
        self.pet.record_manual_event('manual_action_started',action=name,version=data['version'],visual_acceptance=data.get('visual_acceptance','unknown'),automatic=automatic)
        return True
    def _play_phase(self,phase):
        if self.job is not None:self.pet.root.after_cancel(self.job)
        self.job=None;self.phase=phase;self.step_index=0
        self._notice({'enter':'正在摘帽坐下','loop':'正在睡觉（稍后自动醒来）' if self.automatic else '正在睡觉（只会手动唤醒）',
                      'exit':'正在醒来戴帽','play':'正在摸头回应'}.get(phase,phase))
        self._display_step()
        if phase=='loop' and self.automatic:self.pet.autonomous.sleep_holding()
        if phase=='exit':self.pet.voice.emit('wake')
    def display(self):
        if not self.active or self.index is None:return
        scale=self.pet.scale
        canvas=self.resource['canvas']
        size=(canvas[0]*scale,canvas[1]*scale)
        if self.resource.get('renderer')=='native_manual':
            if scale not in self.photos:self.photos[scale]=[None]*len(self.frames)
            if self.photos[scale][self.index] is None:
                self.photos[scale][self.index]=make_photo(self.frames[self.index],size,Image.Resampling.LANCZOS)
        elif scale not in self.photos:
            self.photos[scale]=[ImageTk.PhotoImage(im.resize(size,Image.Resampling.NEAREST)) for im in self.frames]
        self.pet.label.configure(image=self.photos[scale][self.index])
    def _display_step(self):
        if not self.active:return
        sequence=self.phases[self.phase]
        # Only explicit endpoints may have zero duration; they never schedule a zero-delay loop.
        while self.step_index<len(sequence):
            self.index,ms=sequence[self.step_index];self.display()
            if ms:
                self.job=self.pet.root.after(ms,self._advance);return
            self.step_index+=1
        self._phase_finished()
    def _advance(self):
        self.job=None
        if not self.active:return
        if not self.pet.visible or self.pet.closing:self.cancel();return
        self.step_index+=1;self._display_step()
    def _phase_finished(self):
        if self.name=='sleep' and self.phase in ('enter','loop'):
            self._play_phase('exit' if self.finish_requested else 'loop')
        else:
            name=self.name
            self.active=False  # Natural completion lets the one-shot wake clip finish.
            self.pet._reset_idle();self.pet._schedule_next_frame();self.pet._schedule_reading()
            self._notice('已回到待机')
            self.pet.record_manual_event('manual_action_finished',action=name)
    def wake(self, *, automatic=False):
        if not self.active or self.name!='sleep' or self.phase=='exit':return False
        self.pet.autonomous.cancel_wake()
        self.finish_requested=True
        self._notice('已请求醒来，等待当前动作衔接完成')
        self.pet.record_manual_event('sleep_auto_wake_requested' if automatic else 'sleep_manual_wake_requested',phase=self.phase)
        return True
    def stop(self):
        self.pet._reset_idle();self.pet._schedule_next_frame();self.pet._schedule_reading()
        self._notice('已停止试装，回到待机')
    def cancel(self):
        if self.active:self.pet.voice.stop('sleep')
        if self.job is not None:self.pet.root.after_cancel(self.job);self.job=None
        self.active=False;self.name=None;self.phase=None;self.index=None;self.automatic=False
        self.finish_requested=False;self.frames=[];self.photos={};self.phases={};self.resource=None
