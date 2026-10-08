"""Real-time spring pose selection; supplied PNGs and baked watch are untouched."""
import hashlib
import json
import math
import time
from pathlib import Path
from PIL import Image, ImageTk
from style_resources import make_photo
from walk_trial import position_window


class BodySpring:
    def __init__(self, config):
        self.config=config
        self.cancel()

    def cancel(self):
        self.angle=0.0;self.velocity=0.0;self.cursor_speed=0.0
        self.x=0.0;self.pointer_time=0.0;self.updated=0.0;self.last_motion=0.0

    def begin(self,x,now):
        self.cancel();self.x=x;self.pointer_time=self.updated=self.last_motion=now

    def move(self,x,now):
        self.update(now)
        dt=now-self.pointer_time
        if dt<=0:return
        dx=x-self.x;c=self.config
        raw=max(-c['max_cursor_speed'],min(c['max_cursor_speed'],dx/dt))
        self.cursor_speed+=(raw-self.cursor_speed)*(1-math.exp(-dt/c['speed_smoothing']))
        self.x=x;self.pointer_time=now
        if abs(dx)>=0.5:self.last_motion=now

    def update(self,now):
        elapsed=max(0,now-self.updated);self.updated=now
        # Treat a long UI suspension as a fresh hold instead of integrating millions of steps.
        if elapsed>2:self.angle=self.velocity=self.cursor_speed=0.0;return
        steps=max(1,math.ceil(elapsed/0.02));dt=elapsed/steps;c=self.config
        for i in range(steps):
            self.cursor_speed*=math.exp(-dt/c['speed_smoothing'])
            if now-elapsed+(i+1)*dt-self.last_motion>0.12:self.cursor_speed*=math.exp(-dt*10)
            target=max(-c['max_angle'],min(c['max_angle'],-self.cursor_speed*c['velocity_gain']))
            acceleration=c['frequency']**2*(target-self.angle)-2*c['damping_ratio']*c['frequency']*self.velocity
            self.velocity+=acceleration*dt
            self.angle=max(-c['max_angle'],min(c['max_angle'],self.angle+self.velocity*dt))
        if self.quiet():self.angle=self.velocity=self.cursor_speed=0.0

    def quiet(self):
        return abs(self.angle)<0.35 and abs(self.velocity)<1 and abs(self.cursor_speed)<2


def load_grab(folder,canvas):
    folder=Path(folder).resolve();data=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if data.get('renderer')=='native_grab':return load_native_grab(folder,data,canvas)
    if data.get('renderer')!='pixel' or data.get('action')!='grab' or data['canvas']!=list(canvas):
        raise ValueError('Invalid grab renderer or canvas')
    anchor=data['anchor']
    if len(anchor)!=2 or any(type(v) is not int or not 0<=v<canvas[i] for i,v in enumerate(anchor)):
        raise ValueError('Invalid grab anchor')
    c=data['physics']
    for key,lo,hi in [('max_angle',1,45),('frequency',1,30),('damping_ratio',0.1,2),('velocity_gain',0.001,0.2),('speed_smoothing',0.01,1),('max_cursor_speed',100,5000),('pose_threshold',0.1,20),('tick_ms',16,100)]:
        value=c[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Invalid grab physics '+key)
    entries=data['frames']
    if not isinstance(entries,list) or not 1<=len(entries)<=120:raise ValueError('Invalid grab pose list')
    images={};angles={}
    for entry in entries:
        path=(folder/entry['file']).resolve();name=entry['name'];angle=entry['angle']
        if name in images or not path.is_relative_to(folder) or path.suffix.lower()!='.png':raise ValueError('Invalid grab pose path')
        if type(angle) not in (int,float) or not math.isfinite(angle) or not -45<=angle<=45:raise ValueError('Invalid grab pose angle')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Grab pose checksum differs')
        with Image.open(path) as im:
            if im.mode!='RGBA' or im.size!=tuple(canvas):raise ValueError('Invalid grab PNG')
            image=im.copy()
        if not image.getchannel('A').getpixel(tuple(anchor)):raise ValueError('Grab anchor is transparent')
        images[name]=image;angles[name]=angle
    if not any(angle==0 for angle in angles.values()):raise ValueError('Grab has no center pose')
    return data,images,angles


def load_native_grab(folder,data,canvas):
    if data.get('action')!='grab' or data.get('canvas')!=list(canvas):
        raise ValueError('Invalid native grab canvas')
    native=data['source_canvas']
    if (not isinstance(native,list) or len(native)!=2
        or any(type(v) is not int or not 1<=v<=4096 for v in native)):
        raise ValueError('Invalid native source canvas')
    c=data['physics']
    for key,lo,hi in [('max_angle',1,40),('frequency',1,30),('damping_ratio',0.1,2),('velocity_gain',0.001,0.2),('speed_smoothing',0.01,1),('max_cursor_speed',100,5000),('pose_threshold',0.1,20),('tick_ms',16,100)]:
        value=c[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('Invalid native physics '+key)
    entries=data['poses']
    if not isinstance(entries,list) or not 1<=len(entries)<=120:raise ValueError('Invalid native poses')
    images={};angles={}
    for entry in entries:
        name=entry['pose'];path=(folder/entry['source_path']).resolve()
        q=entry['normalized_swing_proxy'];anchor=entry['grab_xy']
        if name in images or not path.is_relative_to(folder) or path.suffix.lower()!='.png':
            raise ValueError('Invalid native pose path')
        if type(q) not in (int,float) or not math.isfinite(q) or not -1<=q<=1:
            raise ValueError('Invalid native pose coordinate')
        if len(anchor)!=2 or any(type(v) is not int or not 0<=v<native[i] for i,v in enumerate(anchor)):
            raise ValueError('Invalid native grab point')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['source_sha256']:
            raise ValueError('Native pose checksum differs')
        with Image.open(path) as im:
            if im.mode!='RGBA' or im.size!=tuple(native):raise ValueError('Invalid native PNG')
            if not im.getpixel(tuple(anchor))[3]:raise ValueError('Native grab point is transparent')
            images[name]=im.copy()
        # These are normalized authored poses, not measured geometric angles.
        angles[name]=q*c['max_angle']
    if angles.get('CENTER')!=0 or min(angles.values())>=0 or max(angles.values())<=0:
        raise ValueError('Native grab is missing center or a direction')
    for base,variant in data.get('new_direction_specific_return_poses',{}).items():
        if base not in images or variant not in images or not variant.endswith('_RETURN'):
            raise ValueError('Invalid return variant')
    return data,images,angles


def select_native_pose(resource,angle,velocity,previous=None):
    c=resource['physics']
    if abs(angle)<c['pose_threshold']:return 'CENTER'
    q=max(-1,min(1,angle/c['max_angle']))
    entries={e['pose']:e['normalized_swing_proxy'] for e in resource['poses']}
    candidates={name:value for name,value in entries.items() if not name.endswith('_RETURN')}
    if angle<0 and velocity>0.2:
        for base,variant in resource.get('new_direction_specific_return_poses',{}).items():
            candidates.pop(base,None);candidates[variant]=entries[variant]
    chosen=min(candidates,key=lambda name:abs(candidates[name]-q))
    # A small deadband avoids nearest-neighbour flicker without slowing a reversal.
    if previous in candidates and abs(candidates[previous]-q)<=abs(candidates[chosen]-q)+0.0075:
        return previous
    return chosen


class GrabSway:
    def __init__(self,pet,folder):
        self.pet=pet;self.job=None;self.active=False;self.pose=None;self.photos={};self.pointer=None
        if folder is None:
            self.resource=None;self.images={};self.angles={};self.motion=None
            return
        try:
            self.resource,self.images,self.angles=load_grab(folder,pet.manifest['canvas'])
            self.motion=BodySpring(self.resource['physics'])
        except (OSError,KeyError,TypeError,ValueError) as exc:
            self.resource=None;self.images={};self.angles={};self.motion=None
            pet.record_manual_event('grab_sway_unavailable',reason=str(exc))

    def begin(self,x,now,y=None):
        if self.resource is None:return False
        self.cancel();self.active=True;self.motion.begin(x,now)
        if y is not None:self.pointer=(x,y)
        self.display(0)
        self.pet.record_manual_event('grab_sway_started',version=self.resource['version'],pose_count=len(self.images),watch='baked_in_png')
        return True

    def move(self,x,now,y=None):
        if not self.active:return
        if y is not None:self.pointer=(x,y)
        self.motion.move(x,now)
        self._tick()

    def display(self,angle):
        if self.resource['renderer']=='native_grab':
            self.pose=select_native_pose(self.resource,angle,self.motion.velocity,self.pose)
            scale=self.pet.scale;size=tuple(v*scale for v in self.resource['canvas'])
            if scale not in self.photos:
                self.photos[scale]={name:make_photo(im,size,Image.Resampling.LANCZOS) for name,im in self.images.items()}
            self.pet.label.configure(image=self.photos[scale][self.pose])
            if self.active and self.pointer is not None and self.pet.drag_start is not None:
                entry=next(e for e in self.resource['poses'] if e['pose']==self.pose)
                native=self.resource['source_canvas']
                anchor=tuple(round(entry['grab_xy'][i]*size[i]/native[i]) for i in (0,1))
                self.pet.drag_start=anchor
                position_window(self.pet.root,self.pointer[0]-anchor[0],self.pointer[1]-anchor[1])
            return
        c=self.resource['physics'];threshold=c['pose_threshold']
        target=0 if abs(angle)<threshold else angle
        self.pose=min(self.angles,key=lambda name:abs(self.angles[name]-target))
        # Three endpoints need a bucket threshold; extra small-angle art uses nearest-angle selection.
        if len(self.angles)==3 and abs(angle)>=threshold:
            side=[name for name,a in self.angles.items() if a*angle>0]
            if side:self.pose=min(side,key=lambda name:abs(self.angles[name]-angle))
        scale=self.pet.scale
        if scale not in self.photos:
            canvas=self.resource['canvas']
            self.photos[scale]={name:ImageTk.PhotoImage(im.resize((canvas[0]*scale,canvas[1]*scale),Image.Resampling.NEAREST)) for name,im in self.images.items()}
        self.pet.label.configure(image=self.photos[scale][self.pose])

    def _tick(self):
        if self.job is not None:self.pet.root.after_cancel(self.job);self.job=None
        if not self.active or not self.pet.visible or self.pet.closing or self.pet.drag_start is None:
            self.cancel();return
        self.motion.update(time.monotonic());self.display(self.motion.angle)
        if not self.motion.quiet():
            self.job=self.pet.root.after(int(self.resource['physics']['tick_ms']),self._tick)

    def cancel(self):
        if self.job is not None:self.pet.root.after_cancel(self.job)
        self.job=None;self.active=False;self.pose=None;self.pointer=None
        if self.motion is not None:self.motion.cancel()
        # Pointer capture belongs to the host drag lifecycle, not animation.
