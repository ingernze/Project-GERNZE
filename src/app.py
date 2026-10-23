"""Hecate's two-dimensional desktop pet for Windows 11."""
from __future__ import annotations
import ctypes
import json
import os
import queue
import random
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageGrab, ImageTk
from walk_trial import WalkTrial, position_window
from walk_controls import WalkControls
from reading_action import load_reading_action
from manual_actions import ManualActionTrial
from action_controls import ActionControls
from autonomous_actions import AutonomousActions
from character_inertia import Bounds, CoastController
from grab_sway import GrabSway
from tray_popup import TrayPopup
from style_resources import style_paths, decode_atlas, make_photo
from style_controls import StyleControlsMixin
from idle_blink import IdleBlink
from activity_timing import DEFAULTS as ACTIVITY_DEFAULTS, stored_preferences, validate_preferences, DesktopSettingsRequest
from module_hooks import ModuleHooks
from scene_voice import SceneVoice, open_voice_controls
from voice_module import VoiceModuleController
from voice_text_window import open_voice_text
from win_bridge import WinMessageBridge
from tray_win32 import TrayIcon, CALLBACK, TRAY_CLASS, SHOW, HIDE, EXIT
import win32gui, win32con, win32api, win32process, win32event, winerror

ROOT = Path(__file__).resolve().parent
STATE_ROOT = (
    Path(os.environ['HECATE_STATE_DIR']).resolve()
    if os.environ.get('HECATE_STATE_DIR')
    else (
        Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'HecatePixelPetDeepSeekTrial'
        if getattr(sys, 'frozen', False) else ROOT
    )
)
OUTPUT = STATE_ROOT / 'output'
ASSET_DIR = ROOT / 'assets' / 'pixel' / 'libao' / 'idle'
MANIFEST = ASSET_DIR / 'manifest.json'
READING_DIR = ROOT / 'assets' / 'pixel' / 'libao' / 'reading'
READING_MANIFEST = READING_DIR / 'manifest.json'
ICON_PATH = ROOT / 'assets' / 'icons' / 'libao.ico'
SETTINGS = STATE_ROOT / 'settings.json'
LOG = OUTPUT / 'app_events.jsonl'
KEY = '#ff00ff'
MUTEX_NAME = r'Local\HecatePixelPetDeepSeekTrial'


def log(event, **data):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'time':time.time(),'event':event,**data},ensure_ascii=False)+'\n')


def load_settings():
    defaults={'x':None,'y':None,'display_scale':2,'muted':True,'visible':True,
              'feature_modules':{'cet6':False},'character_style':'style2','voice_volume_percent':30,'activity_timing':dict(ACTIVITY_DEFAULTS)}
    try:
        supplied=json.loads(SETTINGS.read_text(encoding='utf-8'))
        if not isinstance(supplied,dict):raise ValueError('settings root must be object')
    except FileNotFoundError:
        return defaults
    except (json.JSONDecodeError,UnicodeDecodeError,ValueError) as exc:
        backup=SETTINGS.with_name('settings.invalid.'+time.strftime('%Y%m%d-%H%M%S')+'.json')
        try:backup.write_bytes(SETTINGS.read_bytes())
        except OSError:backup=None
        log('settings_default_fallback',reason=str(exc),backup=str(backup) if backup else None)
        return defaults
    result={**defaults,**supplied}
    result['activity_timing']=stored_preferences(supplied.get('activity_timing'))
    # Start at 2x even when the last session saved a different size.
    result['display_scale']=2
    for p in ('x','y'):
        if not isinstance(result.get(p),int):result[p]=None
    result['muted']=bool(result.get('muted',True))
    result['visible']=bool(result.get('visible',True))
    if type(result.get('voice_volume_percent')) is not int or not 0<=result['voice_volume_percent']<=100:result['voice_volume_percent']=30
    result['feature_modules']={'cet6':False}
    if result.get('character_style') not in ('original','style2'):result['character_style']='style2'
    return result


def save_settings(settings):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temp=SETTINGS.with_suffix('.json.tmp')
    temp.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,SETTINGS)


def load_manifest(asset_dir=None):
    import hashlib
    asset_dir=Path(asset_dir or ASSET_DIR).resolve()
    data=json.loads((asset_dir/'manifest.json').read_text(encoding='utf-8'))
    assert data.get('canvas')==[128,128], 'Logical display canvas not 128x128'
    entries=data.get('frames')
    assert isinstance(entries,list) and 1<=len(entries)<=60
    loaded=[];cache={}
    for entry in entries:
        name=entry['file'];path=(asset_dir/name).resolve()
        if path.parent!=asset_dir or path.suffix.lower()!='.png':raise ValueError('frame path escapes asset folder')
        duration=int(entry['duration_ms'])
        if not 30<=duration<=10000:raise ValueError('frame duration out of range')
        if name not in cache:
            raw=path.read_bytes()
            if entry.get('sha256') and hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('Frame checksum differs: '+name)
            with Image.open(path) as source:
                if entry.get('native_frame'):
                    if source.mode!='RGBA' or list(source.size)!=data.get('source_canvas'):
                        raise ValueError('Wrong native frame format or canvas')
                    alpha=source.getchannel('A')
                    if alpha.getbbox() is None or alpha.getextrema()[0]!=0:
                        raise ValueError('Native frame must contain real transparency')
                    # Keep original art resolution; resize once when creating the display photo.
                    image=source.copy()
                else:
                    image=decode_atlas(source,entry,(128,128)) if 'atlas_box' in entry else source.convert('RGBA')
                    if image.size!=(128,128):raise ValueError(f'Wrong frame size: {name}')
            cache[name]=image
        loaded.append((cache[name],duration))
    return data,loaded




class HecatePet(StyleControlsMixin):
    def __init__(self, *, self_test=False):
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.settings=load_settings()
        self.character_style=self.settings.get('character_style','style2')
        self.style_asset_paths=style_paths(ROOT,self.character_style)
        try:self.manifest,self.frames=load_manifest(self.style_asset_paths['idle'])
        except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
            log('style_startup_fallback',reason=str(exc))
            self.character_style='original';self.settings['character_style']='original'
            self.style_asset_paths=style_paths(ROOT,'original');self.manifest,self.frames=load_manifest()
        self.style_resampling=Image.Resampling.LANCZOS if self.character_style=='style2' else Image.Resampling.NEAREST
        try:
            if self.style_asset_paths['reading'] is None:
                self.reading_resource,self.reading_frames,self.reading_wait,self.reading_duration=None,[],None,None
            else:self.reading_resource,self.reading_frames,self.reading_wait,self.reading_duration=load_reading_action(self.style_asset_paths['reading'],self.frames[0][0])
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.reading_resource=None
            self.reading_frames=[]
            self.reading_wait=self.reading_duration=None
            log('reading_unavailable',reason=str(exc))
        self.commands=queue.Queue()
        self.closing=False
        self.ui_thread=threading.get_ident()
        self.root=tk.Tk()
        self.root.title('莉宝桌宠')
        self.root.report_callback_exception=lambda kind,error,tb:log('callback_error',error=str(error),trace=''.join(traceback.format_exception(kind,error,tb)))
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY)
        self.root.wm_attributes('-transparentcolor',KEY)
        self.root.wm_attributes('-topmost',True)
        self.root.wm_attributes('-toolwindow',True)
        self.root.protocol('WM_DELETE_WINDOW',self.quit)
        self.modules=ModuleHooks(self.root,STATE_ROOT / "modules")
        self.bridge=WinMessageBridge('HecateActiveEventReceiver',self._consume_commands,
            self.show,self._desktop_environment_changed,log,scheduler=self.root)
        self.photos={}
        self.reading_photos={}
        self.scale=self.settings['display_scale']
        self._prepare_photos()
        self.label=tk.Label(self.root,image=self.photos[self.scale][0],bg=KEY,
                            bd=0,highlightthickness=0)
        self.label.place(x=0,y=0)
        self.frame_index=0
        self.style2_motion=self.manifest.get('motion','rest')
        self.frame_job=None
        self.reading_job=None
        self.reading_start_job=None
        self.reading_due_at=None
        self.reading_end_job=None
        self.reading_index=None
        self.reading_phase=None
        self.reading_steps=[]
        self.reading_step=0
        self.reading_finish_requested=False
        self.visible=True
        self.drag_start=None
        self.drag_origin=None
        self.drag_moved=False
        self.head_click_candidate=False
        self.walk_trial=WalkTrial(self,self.style_asset_paths['walk'])
        self.walk_controls=None
        self.manual_action=ManualActionTrial(self,self.style_asset_paths['actions'])
        self.action_controls=None
        self.grab_sway=GrabSway(self,self.style_asset_paths['grab'])
        self.coast=CoastController(self.root,self._coast_place,
            self._coast_state_changed,self._coast_settled,clock=time.monotonic)
        self.root.bind('<Configure>',self._coast_geometry_changed,add='+')
        self.autonomous=AutonomousActions(self,ROOT / 'behavior_config.json',self.style_asset_paths['walk'])
        if self.character_style=='style2':self.autonomous.suspended=True
        self.tray_popup=None
        self.muted=bool(self.settings['muted'])
        from optional_modules import OptionalModules
        self.optional_modules=OptionalModules(ROOT,STATE_ROOT)
        self.packages_window=None
        self.voice=SceneVoice(self.optional_modules.fixed_home(),enabled=lambda:not self.muted and self.visible and not self.closing,logger=log,
            volume=lambda:self.settings['voice_volume_percent'],cache_dir=STATE_ROOT/'voice_cache',bindings=self.settings.get('scene_voice_bindings',{}))
        if self.optional_modules.installed('fixed_voice'):
            self.settings['scene_voice_bindings']=dict(self.voice.binding_overrides)
        self.voice_bindings_window=None
        self.voice_controls=None
        self.voice_modules_window=None
        self.voice_text_window=None
        self.voice_api_window=None
        self.voice_module=VoiceModuleController(self,ROOT,STATE_ROOT)
        self.idle_blink=IdleBlink(self)
        self._place_initial()
        self.label.bind('<ButtonPress-1>',self._drag_begin)
        # Captured events outside the sprite are routed to the toplevel.
        # Descendant label events also reach these bindings through bindtags.
        self.root.bind('<B1-Motion>',self._drag_move)
        self.root.bind('<ButtonRelease-1>',self._drag_end)
        self.label.bind('<Button-3>',lambda e:self.hide())
        self.tray=TrayIcon(self.commands,log,self._notify_commands,ICON_PATH)
        self.tray.start()
        if not self.tray.ready.wait(3.0):raise RuntimeError('Tray startup timed out')
        if self.tray.error:raise RuntimeError('Tray startup failed: '+self.tray.error)
        if not self.settings['visible']:
            self.hide()
        else:
            self._schedule_next_frame()
            self._schedule_reading()
        log('started',pid=os.getpid(),dpi=ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id()),
            frames=len(self.frames),scale=self.scale,asset_status=self.manifest.get('status','unknown'),
            reference_only=self.manifest.get('status','').startswith('temporary_'),
            control_polling=False)
        if self_test:self._schedule_self_test()
        if '--benchmark' in sys.argv:self._schedule_benchmark()

    def _prepare_photos(self):
        if self.scale not in self.photos:
            size=128*self.scale
            from foot_sway import photos_for
            self.photos[self.scale]=photos_for(self.frames,(size,size),self.style_resampling)
            self.reading_photos[self.scale]=[make_photo(img,(size,size),self.style_resampling)
                                             for img,duration in self.reading_frames]

    def _place_initial(self):
        size=128*self.scale
        sw,sh=self.root.winfo_screenwidth(),self.root.winfo_screenheight()
        x=self.settings['x'] if self.settings['x'] is not None else sw-size-80
        y=self.settings['y'] if self.settings['y'] is not None else sh-size-100
        x=max(0,min(x,max(0,sw-size)));y=max(0,min(y,max(0,sh-size)))
        self.root.geometry(f'{size}x{size}+{x}+{y}')

    def _schedule_next_frame(self):
        if "--benchmark" in sys.argv or self.coast.motion.frame.active:return
        if self.manual_action.active:return
        if self.walk_trial.active:return
        if self.reading_index is not None:return
        if not self.visible or self.drag_start is not None or self.frame_job is not None:return
        if len(self.frames)<2:return
        if not self.manifest.get('loop',True) and self.frame_index==len(self.frames)-1 and not self.idle_blink.active and self.style2_motion!='foot_sway':return
        delay=self.frames[self.frame_index][1]
        self.frame_job=self.root.after(delay,self._next_frame)

    def _next_frame(self):
        self.frame_job=None
        if not self.visible:return
        if self.style2_motion=='foot_sway' and getattr(self,'_sway_exit_target',None) is not None:
            if self.frame_index==len(self.frames)-1:
                self._commit_sway_exit();self._schedule_next_frame();self._schedule_reading();return
            next_index=self.frame_index+1
            if (self._sway_finish_requested and next_index<self._sway_landing
                    and next_index>=4 and self.manifest['frames'][next_index]['file']=='F10.png'):
                next_index=self._sway_landing
            self.frame_index=next_index
        else:self.frame_index=(self.frame_index+1)%len(self.frames)
        if self.frame_index==0:self.idle_blink.on_cycle_boundary()
        self.label.configure(image=self.photos[self.scale][self.frame_index])
        self._schedule_next_frame()

    def _cancel_frame(self):
        # No deferred rest switch can fire after hide, grab, sleep or skin change.
        self._commit_sway_exit()
        self._sway_entry=[]
        if getattr(self,'idle_blink',None) is not None:self.idle_blink.cancel()
        if self.frame_job is not None:
            self.root.after_cancel(self.frame_job)
            self.frame_job=None

    def _reset_idle(self, *, preserve_reading_wait=False, preserve_position_drag=False):
        if not preserve_position_drag:self._cancel_coast()
        self.autonomous.cancel()
        self.grab_sway.cancel()
        self.manual_action.cancel()
        self.walk_trial.cancel()
        self._cancel_reading(preserve_wait=preserve_reading_wait)
        self._cancel_frame()
        self.frame_index=0
        self._sway_entry=[]
        self.label.configure(image=self.photos[self.scale][self.frame_index])

    def _cancel_reading(self, *, preserve_wait=False):
        self.voice.stop('reading')
        if not preserve_wait:self.reading_due_at=None
        for name in ('reading_job','reading_start_job','reading_end_job'):
            job=getattr(self,name)
            if job is not None:
                self.root.after_cancel(job)
                setattr(self,name,None)
        self.reading_index=None
        self.reading_phase=None
        self.reading_steps=[]
        self.reading_finish_requested=False

    def _schedule_reading(self):
        if "--benchmark" in sys.argv or self.coast.motion.frame.active:return
        if self.manual_action.active or self.walk_trial.active:return
        if not self.visible or self.closing or self.drag_start is not None or self.reading_index is not None:return
        if self.character_style=='style2' and self.style2_motion!='rest':return
        self.autonomous.sway.schedule()
        if self.autonomous.enabled():
            self.autonomous.schedule()
            return
        if self.autonomous.suspended and '--random-actions-self-test' not in sys.argv:
            # Preserve the isolated manual acceptance tests' original reading policy.
            pass
        elif self.autonomous.config.get('selector',{}).get('enabled') is False:
            return
        if self.reading_frames and self.reading_start_job is None:
            if self.reading_due_at is None:
                self.reading_due_at=time.monotonic()+random.randint(*self.reading_wait)/1000
            remaining=max(1,round((self.reading_due_at-time.monotonic())*1000))
            self.reading_start_job=self.root.after(remaining,self._start_random_reading)
        self.autonomous.schedule()

    def _start_random_reading(self):
        if self.reading_start_job is not None:
            self.root.after_cancel(self.reading_start_job)
        self.reading_start_job=None
        self.reading_due_at=None
        self.start_reading()

    def start_reading(self):
        if self.closing or self.drag_start is not None:return False
        if not self.reading_frames:
            self._reset_idle();self._schedule_next_frame();self._schedule_reading()
            log('reading_fallback_to_idle')
            return False
        if not self.visible:self.show()
        self._reset_idle()
        self._play_reading_phase('enter')
        self.voice.emit('reading_start')
        log('reading_started',version=self.reading_resource['version'])
        return True

    def _play_reading_phase(self,phase):
        if self.reading_job is not None:
            self.root.after_cancel(self.reading_job)
            self.reading_job=None
        self.reading_phase=phase
        self.reading_steps=self.reading_resource['phases'][phase]
        self.reading_step=0
        self._display_reading_step()

    def _display_reading_step(self):
        index,duration=self.reading_steps[self.reading_step]
        self.reading_index=index
        self.label.configure(image=self.reading_photos[self.scale][index])
        self.reading_job=self.root.after(duration,self._next_reading_step)

    def _next_reading_step(self):
        self.reading_job=None
        if self.reading_index is None or not self.visible or self.closing:return
        self.reading_step+=1
        if self.reading_step<len(self.reading_steps):
            self._display_reading_step()
        elif self.reading_phase=='exit':
            self._reset_idle()
            self._schedule_next_frame()
            self._schedule_reading()
            log('reading_finished')
        else:
            was_enter=self.reading_phase=='enter'
            self.reading_phase='reading'
            self.reading_index=self.reading_resource['hold_index']
            self.label.configure(image=self.reading_photos[self.scale][self.reading_index])
            if was_enter and self.reading_finish_requested:
                self._play_reading_phase('exit')
            elif was_enter:
                self.reading_end_job=self.root.after(random.randint(*self.reading_duration),self._finish_reading)
                log('reading_hold_started')
            else:log('reading_glance_finished')

    def glance_from_reading(self):
        if self.reading_phase!='reading' or self.reading_job is not None or not self.visible:return
        self._play_reading_phase('glance')
        self.voice.emit('reading_click')
        log('reading_glance_started')

    def _finish_reading(self):
        if self.reading_index is None or not self.visible or self.closing or self.reading_phase=='exit':return
        if self.reading_phase=='enter':
            self.reading_finish_requested=True
            return
        if self.reading_end_job is not None:
            self.root.after_cancel(self.reading_end_job)
            self.reading_end_job=None
        self._play_reading_phase('exit')
        log('reading_closing_started')

    def hide(self):
        self.voice_module.cancel()
        self.voice.stop()
        if self.voice_text_window is not None and self.voice_text_window.winfo_exists():self.voice_text_window.withdraw()
        if self.voice_controls is not None and self.voice_controls.winfo_exists():self.voice_controls.withdraw()
        if self.voice_bindings_window is not None and self.voice_bindings_window.winfo_exists():self.voice_bindings_window.withdraw()
        if self.voice_modules_window is not None and self.voice_modules_window.winfo_exists():self.voice_modules_window.withdraw()
        if self.voice_api_window is not None and self.voice_api_window.winfo_exists():self.voice_api_window.withdraw()
        if not self.visible:return
        self._cancel_drag()
        self.autonomous.cancel(reset_wait=True)
        self._reset_idle()
        self.drag_start=None
        self._remember_position()
        self.visible=False
        if self.walk_controls is not None and self.walk_controls.winfo_exists():self.walk_controls.withdraw()
        if self.action_controls is not None and self.action_controls.winfo_exists():self.action_controls.withdraw()
        self.root.withdraw()
        self.modules.hide()
        self.settings['visible']=False
        save_settings(self.settings)
        log('hidden',frame=self.frame_index,effective_muted=True,animation_scheduled=False)

    def show(self):
        if self.visible:return
        self._reset_idle()
        self.visible=True
        self.root.deiconify()
        self.modules.show()
        self.label.configure(image=self.photos[self.scale][self.frame_index])
        self._schedule_next_frame()
        self._schedule_reading()
        self.settings['visible']=True
        save_settings(self.settings)
        log('shown',frame=self.frame_index,animation_scheduled=self.frame_job is not None)

    def toggle_mute(self):
        self.muted=not self.muted
        self.settings['muted']=self.muted
        if self.muted:
            self.voice_module.cancel()
            self.voice.stop()
        save_settings(self.settings)
        self.voice_module.refresh_status()
        if self.voice_controls is not None and self.voice_controls.winfo_exists():self.voice_controls.refresh_sound()
        log('mute_changed',desired_muted=self.muted,effective_muted=self.muted or not self.visible)

    def set_scale(self,scale):
        if scale not in (1,2,3,4,5):return
        self.idle_blink.cancel()
        self.voice.stop()
        self._cancel_drag()
        self.scale=scale
        self._prepare_photos()
        size=128*scale
        x,y=self.root.winfo_x(),self.root.winfo_y()
        monitor=win32api.MonitorFromPoint((x+self.root.winfo_width()//2,y+self.root.winfo_height()//2),2)
        left,top,right,bottom=win32api.GetMonitorInfo(monitor)['Work']
        x,y=Bounds(left,top,max(left,right-size),max(top,bottom-size)).clamp(x,y)
        self.root.geometry(f'{size}x{size}')
        self.root.update_idletasks()
        position_window(self.root,x,y)
        self._remember_position()
        self.label.configure(image=self.photos[scale][self.frame_index])
        if self.reading_index is not None:
            self.label.configure(image=self.reading_photos[scale][self.reading_index])
        if self.walk_trial.active:self.walk_trial.display()
        if self.manual_action.active:self.manual_action.display()
        self.settings['display_scale']=scale
        save_settings(self.settings)
        log('scale_changed',scale=scale)
        self._schedule_next_frame();self._schedule_reading()

    def _coast_bounds(self):
        width,height=128*self.scale,128*self.scale
        center=(self.root.winfo_x()+width//2,self.root.winfo_y()+height//2)
        monitor=win32api.MonitorFromPoint(center,2)
        left,top,right,bottom=win32api.GetMonitorInfo(monitor)['Work']
        return Bounds(left,top,max(left,right-width),max(top,bottom-height))

    def _coast_place(self,x,y):
        if self.coast.state=='coasting':
            bounds=self._coast_bounds()
            if bounds!=self.coast.motion.bounds:
                self._cancel_coast()
                x,y=bounds.clamp(x,y)
                position_window(self.root,x,y)
                self._remember_position();save_settings(self.settings)
                self._schedule_next_frame();self._schedule_reading()
                return
        position_window(self.root,x,y)

    def _coast_state_changed(self,state):
        if state=='coasting':
            self.voice.emit('slide')
            self._coast_size=(self.root.winfo_width(),self.root.winfo_height())
            frame=self.coast.motion.frame
            log('release_coast_started',vx=round(frame.vx,2),vy=round(frame.vy,2),max_duration_s=self.coast.config.max_duration)
        elif state=='idle' and self.visible and not self.closing:
            self.frame_index=0
            self.label.configure(image=self.photos[self.scale][0])

    def _coast_settled(self,x,y):
        if self.closing or not self.visible:return
        self.settings['x'],self.settings['y']=round(x),round(y)
        save_settings(self.settings)
        log('drag_end',x=self.settings['x'],y=self.settings['y'],position_motion='settled')
        self._schedule_next_frame();self._schedule_reading()

    def _cancel_coast(self):
        coast=getattr(self,'coast',None)
        if coast is None:return
        moving=coast.motion.frame.active
        coast.cancel(notify=False)
        if moving:
            self.voice.stop('slide')
            self.root.update_idletasks()
            self._remember_position();save_settings(self.settings)
            self.frame_index=0
            self.label.configure(image=self.photos[self.scale][0])
            log('release_coast_cancelled')

    def _coast_geometry_changed(self,event):
        coast=getattr(self,'coast',None)
        if (event.widget is self.root and coast is not None and coast.motion.frame.active
                and (event.width,event.height)!=getattr(self,'_coast_size',(event.width,event.height))):
            self._cancel_coast();self._schedule_next_frame();self._schedule_reading()

    def _desktop_environment_changed(self):
        if hasattr(self,'coast'):
            self._cancel_drag();self._schedule_next_frame();self._schedule_reading()
        self.modules.clock_change()

    def _head_hit_at(self,x_root,y_root):
        if self.character_style=='style2':return False  # No matching headpat art in this style.
        x=int((x_root-self.root.winfo_x())/self.scale)
        y=int((y_root-self.root.winfo_y())/self.scale)
        # Native 128px head/hat region, excluding transparent corners and body.
        return (16<=x<116 and 8<=y<76
                and self.frames[0][0].getpixel((x,y))[3]>=20)

    def _drag_begin(self,event):
        if self.closing or not self.visible:return
        self.voice_module.cancel()
        catching_coast=self.coast.motion.frame.active
        self._cancel_coast()
        self.head_click_candidate=(not catching_coast and self.reading_index is None
            and not self.manual_action.active and not self.walk_trial.active
            and self._head_hit_at(event.x_root,event.y_root))
        self.autonomous.cancel_idle()
        self.drag_start=(event.x_root-self.root.winfo_x(),event.y_root-self.root.winfo_y())
        self.drag_origin=(event.x_root,event.y_root)
        self.drag_moved=False
        self.drag_started_at=time.monotonic()
        self.coast.begin((event.x_root,event.y_root),(self.root.winfo_x(),self.root.winfo_y()))
        # Capture before the first large pointer jump can leave the sprite.
        try:self.root.grab_set_global()
        except tk.TclError as exc:
            log('drag_global_capture_unavailable',reason=str(exc))
            try:self.root.grab_set()
            except tk.TclError:pass

    def _release_drag_capture(self):
        try:
            if self.root.grab_current() is self.root:self.root.grab_release()
        except tk.TclError:pass

    def _cancel_drag(self, *, cancel_coast=True):
        if cancel_coast:self._cancel_coast()
        self._release_drag_capture()
        self.grab_sway.cancel()
        self.drag_start=None
        self.drag_origin=None
        self.drag_moved=False
        self.head_click_candidate=False

    def _drag_move(self,event):
        if self.drag_start is None:return
        if not self.drag_moved:
            if max(abs(event.x_root-self.drag_origin[0]),abs(event.y_root-self.drag_origin[1]))<5:
                self.coast.move((event.x_root,event.y_root),(self.root.winfo_x(),self.root.winfo_y()))
                return
            self.drag_moved=True
            self.autonomous.cancel(reset_wait=True)
            self._reset_idle(preserve_position_drag=True)
            self.grab_sway.begin(self.drag_origin[0],self.drag_started_at,self.drag_origin[1])
            self.voice.emit('drag')
        self.grab_sway.move(event.x_root,time.monotonic(),event.y_root)
        x=event.x_root-self.drag_start[0]
        y=event.y_root-self.drag_start[1]
        position_window(self.root,x,y)
        self.coast.move((event.x_root,event.y_root),(x,y))

    def _drag_end(self,event):
        if self.drag_start is None:return
        # A large release jump still counts as dragging if motion was coalesced.
        if not self.drag_moved and max(abs(event.x_root-self.drag_origin[0]),abs(event.y_root-self.drag_origin[1]))>=5:
            self._drag_move(event)
        moved=self.drag_moved
        head_click=(getattr(self,'head_click_candidate',False) and not moved
                    and self._head_hit_at(event.x_root,event.y_root))
        if moved:
            # The release coordinate may be newer than the last motion event.
            position_window(self.root,event.x_root-self.drag_start[0],event.y_root-self.drag_start[1])
        if moved:
            position=(event.x_root-self.drag_start[0],event.y_root-self.drag_start[1])
            native_grab=(self.grab_sway.resource is not None and self.grab_sway.resource['renderer']=='native_grab')
            self._cancel_drag(cancel_coast=False)
            if native_grab:
                self.frame_index=0
                self.label.configure(image=self.photos[self.scale][0])
            self.voice.stop('drag')
            self.coast.release((event.x_root,event.y_root),position,self._coast_bounds())
            return
        self._cancel_drag()
        if self.reading_index is not None:
            self.glance_from_reading()
        elif head_click and not self.manual_action.active and not self.walk_trial.active:
            if self.start_manual_action('headpat'):
                log('head_click_response_started',scale=self.scale)
        self._schedule_next_frame()
        self._schedule_reading()

    def _remember_position(self):
        if self.visible:
            self.settings['x']=self.root.winfo_x()
            self.settings['y']=self.root.winfo_y()

    def _notify_commands(self):
        """A tray command schedules one Tk callback; no idle queue polling."""
        if self.closing:
            return
        try:
            self.bridge.notify()
        except (tk.TclError,RuntimeError,OSError) as exc:
            if not self.closing:
                log('tray_wakeup_failed',error=str(exc))

    def _enqueue_command(self,command):
        self.commands.put(command)
        self._notify_commands()

    def activity_settings_call(self,command,params):
        if self.closing:raise OSError('莉宝正在退出，设置未保存。')
        if command=='behavior.set':validate_preferences(params['settings'])
        request=DesktopSettingsRequest(command,params)
        if threading.get_ident()==self.ui_thread:request.execute(self)
        else:self._enqueue_command(request)
        return request.wait()

    def activity_settings_snapshot(self):
        return {'available':True,'settings':dict(self.settings['activity_timing']),
                'defaults':dict(ACTIVITY_DEFAULTS),
                'sleep_available':self.autonomous.sleep.resource_available(),
                'foot_sway_available':self.autonomous.sway.resource_available(),
                'blink_available':self.character_style=='style2' and self.idle_blink.blink_manifest is not None}

    def apply_activity_settings(self,value):
        prefs=validate_preferences(value)
        updated={**self.settings,'activity_timing':prefs}
        save_settings(updated)
        self.settings['activity_timing']=prefs
        self.idle_blink.lottery.configure(prefs['blink_min_s'],prefs['blink_max_s'])
        # An already sleeping pet keeps its chosen duration; future sleeps use
        # the new values. Disabling automatic sleep never strands a wake timer.
        self.autonomous.sleep.cancel_idle(reset_wait=True)
        self.autonomous.sleep.schedule()
        self.autonomous.sway.cancel_idle(reset_wait=True)
        self.autonomous.sway.schedule()
        log('activity_timing_saved')
        return {**self.activity_settings_snapshot(),'persisted':True}

    def _consume_commands(self):
        if threading.get_ident()!=self.ui_thread:
            raise RuntimeError('Tk command handler left its UI thread')
        while True:
            try:command=self.commands.get_nowait()
            except queue.Empty:break
            if isinstance(command,DesktopSettingsRequest):
                command.execute(self);continue
            log('tray_command',command=command,ui_thread=True)
            if command=='show':self.show()
            elif command=='hide':self.hide()
            elif command=='mute':self.toggle_mute()
            elif command=='workbench:open':getattr(self,'open_workbench',lambda:None)()
            elif command=='packages:open':
                from module_packages_window import open_packages
                open_packages(self)
            elif command=='modules:open':
                if self.optional_modules.installed('cet6'):
                    self.optional_modules.activate_study();self.modules.open()
                else:
                    from module_packages_window import open_packages
                    open_packages(self)
            elif command=='quota:open':getattr(self,'open_quota_overview',getattr(self,'open_quota_card',lambda:None))()
            elif command=='quota:drain':getattr(self,'_drain_quota',lambda:None)()
            elif command=='voice_module:drain':self.voice_module.drain()
            elif command=='voice_module:refresh':self.voice_module.refresh_status()
            elif command=='voice_modules:open':self.open_voice_modules()
            elif command=='voice_module:open':self.open_voice_text()
            elif command=='voice:open':self.open_voice_modules()
            elif command=='voice:fixed':self.open_voice_controls()
            elif command=='voice:text':self.open_voice_text()
            elif command=='voice:api':
                if not self.optional_modules.installed('voice_engine'):
                    from module_packages_window import open_packages
                    open_packages(self)
                else:
                    from voice_api_window import open_voice_api
                    open_voice_api(self)
            elif command=='voice:workbench_open':self.voice.emit('workbench')
            elif command=='voice:workbench_stop':
                self.voice.stop('workbench');self.voice.stop('workbench_scene')
            elif command=='voice:scene_sleep':self.voice.emit('sleep',owner='workbench_scene')
            elif command=='voice:scene_wake':self.voice.emit('wake',owner='workbench_scene')
            elif command=='voice:scene_stop':self.voice.stop('workbench_scene')
            elif command=='reading:play':self.start_reading()
            elif command=='reading:finish':self._finish_reading()
            elif command=='style:open':self.open_style_controls()
            elif command=='codex-activity:open':self.open_codex_activity()
            elif command.startswith('style:'):self.set_style(command.split(':',1)[1])
            elif command=='actions:open':self.open_action_controls()
            elif command=='sleep:play':self.start_manual_action('sleep')
            elif command=='sleep:wake':self.manual_action.wake()
            elif command=='headpat:play':self.start_manual_action('headpat')
            elif command=='walk:open':self.open_walk_controls()
            elif command=='walk:play':self.start_walk('right')
            elif command.startswith('menu:'):
                _,x,y=command.split(':')
                if self.tray_popup is not None and self.tray_popup.winfo_exists():self.tray_popup.close()
                self.tray_popup=TrayPopup(self,int(x),int(y))
            elif command=='exit':self.quit();return
            elif command.startswith('size:'):self.set_scale(int(command.split(':')[1]))

    def set_voice_volume(self,percent):
        from scene_voice import validate_volume
        percent=validate_volume(percent)
        if self.settings['voice_volume_percent']==percent:return
        self.voice.stop();self.settings['voice_volume_percent']=percent;save_settings(self.settings)
        self.voice_module.refresh_status()
        if self.voice_controls is not None and self.voice_controls.winfo_exists():self.voice_controls.refresh_sound()
        log('voice_volume_changed',percent=percent)

    def reload_optional_voice(self):
        self.voice=SceneVoice(self.optional_modules.fixed_home(), enabled=lambda:not self.muted and self.visible and not self.closing,logger=log,
            volume=lambda:self.settings['voice_volume_percent'],cache_dir=STATE_ROOT/'voice_cache',bindings=self.settings.get('scene_voice_bindings',{}))
        self.voice_module=VoiceModuleController(self,ROOT,STATE_ROOT)

    def open_voice_text(self):
        if not self.optional_modules.installed('voice_engine'):
            from module_packages_window import open_packages
            return open_packages(self)
        return open_voice_text(self)

    def open_voice_modules(self):
        from voice_desktop_window import open_voice_modules
        return open_voice_modules(self)

    def save_voice_bindings(self,bindings):
        if self.closing:raise ValueError('莉宝正在退出')
        validated=self.voice.validate_bindings(bindings)
        updated={**self.settings,'scene_voice_bindings':validated}
        save_settings(updated)  # Persist first; failed writes leave runtime untouched.
        self.voice.apply_bindings(validated)
        self.settings=updated
        if self.voice_controls is not None and self.voice_controls.winfo_exists():
            self.voice_controls.refresh_bindings()
        log('scene_voice_bindings_saved',custom_events=list(validated))

    def open_voice_controls(self):
        # Fixed recordings are a core feature, independent of voice_engine.
        if not self.closing:return open_voice_controls(self)

    def record_manual_event(self,event,**data):
        log(event,**data)

    def open_action_controls(self):
        if self.closing:return
        self.show()
        if self.action_controls is None or not self.action_controls.winfo_exists():
            self.action_controls=ActionControls(self)
        else:
            self.action_controls.deiconify();self.action_controls.lift()
        return self.action_controls

    def start_manual_action(self,name, *, automatic=False):
        if self.character_style=='style2':
            if name!='sleep':
                self.manual_action._notice('插画风格尚缺此动作，摸头继续暂停。')
                return False
            if self.style2_motion!='rest' and not self.set_style2_motion('rest'):return False
            self._commit_sway_exit()  # Sleep needs its exact idle endpoint before loading.
            self.idle_blink.cancel()
        started=self.manual_action.start(name,automatic=automatic)
        if started and name=='sleep':self.voice.emit('sleep')
        return started

    def open_walk_controls(self):
        if self.closing:return
        self.show()
        if self.walk_controls is None or not self.walk_controls.winfo_exists():
            self.walk_controls=WalkControls(self)
        else:
            self.walk_controls.deiconify()
            self.walk_controls.lift()
        return self.walk_controls

    def start_walk(self,direction='right',moving=True, *, automatic=False,cycles=None,speed=None):
        try:
            started=self.walk_trial.start(direction,moving=moving,automatic=automatic,cycles=cycles,speed=speed)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self._reset_idle();self._schedule_next_frame();self._schedule_reading()
            log('walk_trial_unavailable',direction=direction,reason=str(exc))
            if self.walk_controls is not None and self.walk_controls.winfo_exists():
                self.walk_controls.unavailable()
            return False
        if started:
            log('walk_trial_started',direction=direction,moving=moving,
                version=self.walk_trial.action['version'],visual_acceptance=self.walk_trial.action.get('visual_acceptance','unknown'),
                automatic=automatic,cycles=self.walk_trial.cycles)
        return started

    def quit(self):
        package_window=getattr(self,'packages_window',None)
        if package_window is not None and package_window.busy:
            from tkinter import messagebox
            messagebox.showinfo('正在整理模块','请等当前安装或移除完成，再退出莉宝。',parent=package_window)
            return
        if self.closing:return
        self.closing=True
        if self.voice_text_window is not None and self.voice_text_window.winfo_exists():self.voice_text_window.close()
        self.voice_module.close()
        self.voice.close()
        if self.voice_bindings_window is not None and self.voice_bindings_window.winfo_exists():self.voice_bindings_window.destroy()
        if self.voice_controls is not None and self.voice_controls.winfo_exists():self.voice_controls.destroy()
        if self.voice_modules_window is not None and self.voice_modules_window.winfo_exists():self.voice_modules_window.destroy()
        if self.voice_api_window is not None and self.voice_api_window.winfo_exists():self.voice_api_window.close()
        self.coast.close()
        self._cancel_drag()
        self.autonomous.cancel(reset_wait=True)
        self.grab_sway.cancel()
        self.manual_action.cancel()
        if self.action_controls is not None and self.action_controls.winfo_exists():self.action_controls.destroy()
        self.walk_trial.cancel()
        if self.walk_controls is not None and self.walk_controls.winfo_exists():self.walk_controls.destroy()
        if self.tray_popup is not None and self.tray_popup.winfo_exists():self.tray_popup.close()
        self._cancel_reading()
        self._cancel_frame()
        self._remember_position()
        self.settings['visible']=self.visible
        self.settings['muted']=self.muted
        save_settings(self.settings)
        self.tray.stop()
        self.tray.join(timeout=2.0)
        self.modules.shutdown()
        self.bridge.close()
        log('exited')
        self.root.destroy()

    def _schedule_self_test(self):
        # Exercises application actions without moving the user's physical pointer.
        def drag():
            old=(self.root.winfo_x(),self.root.winfo_y())
            event=type('E',(),{'x_root':old[0]+50,'y_root':old[1]+50})()
            self._drag_begin(event)
            event.x_root+=40;event.y_root+=30
            self._drag_move(event);self.root.update_idletasks();self._drag_end(event)
            log('self_test_drag',old=old,new=(self.root.winfo_x(),self.root.winfo_y()))
        def screenshot():
            x,y=self.root.winfo_rootx(),self.root.winfo_rooty();size=128*self.scale
            OUTPUT.mkdir(parents=True,exist_ok=True)
            ImageGrab.grab(bbox=(x,y,x+size,y+size),all_screens=True).save(OUTPUT/'desktop_running.png')
            log('desktop_screenshot_saved',path='output/desktop_running.png')
        self.root.after(300,screenshot)
        self.root.after(700,drag)
        self.root.after(1500,lambda:win32gui.PostMessage(self.tray.hwnd,win32con.WM_COMMAND,HIDE,0))
        self.root.after(2200,lambda:win32gui.PostMessage(self.tray.hwnd,win32con.WM_COMMAND,SHOW,0))
        self.root.after(3000,lambda:win32gui.PostMessage(self.tray.hwnd,win32con.WM_COMMAND,EXIT,0))

    def _schedule_benchmark(self):
        # Opt-in only. Production has no recurring performance sampler.
        from performance_self_test import schedule
        schedule(self)

    def run(self):
        self.root.mainloop()


def claim_single_instance():
    mutex=win32event.CreateMutex(None,False,MUTEX_NAME)
    if win32api.GetLastError()!=winerror.ERROR_ALREADY_EXISTS:
        return mutex
    forwarded=False
    for _ in range(30):
        hwnd=win32gui.FindWindow(TRAY_CLASS,None)
        if hwnd:
            win32gui.PostMessage(hwnd,CALLBACK,0,win32con.WM_LBUTTONDBLCLK)
            forwarded=True
            break
        time.sleep(.1)
    log('duplicate_launch',forwarded=forwarded)
    win32api.CloseHandle(mutex)
    return None


if __name__=='__main__':
    single_instance=claim_single_instance()
    if single_instance is not None:
        try:HecatePet(self_test='--self-test' in sys.argv).run()
        except Exception as exc:
            log('fatal_error',error=str(exc),trace=traceback.format_exc())
            raise
        finally:win32api.CloseHandle(single_instance)



