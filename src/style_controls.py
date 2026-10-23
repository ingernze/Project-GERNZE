"""Developer skin selector; prepare all replacement resources before changing state."""
import tkinter as tk
import json
from PIL import Image, ImageTk
from style_resources import STYLE_NAMES,style_paths,make_photo
from reading_action import load_reading_action
from walk_trial import WalkTrial,load_action
from manual_actions import ManualActionTrial
from grab_sway import GrabSway
from autonomous_actions import AutonomousActions

class StyleControlsMixin:
    def set_style(self,style):
        import app
        if self.closing:return False
        if style==self.character_style:return True
        try:
            paths=style_paths(app.ROOT,style)
            manifest,frames=app.load_manifest(paths['idle'])
            reading=(load_reading_action(paths['reading'],frames[0][0]) if paths['reading'] is not None else (None,[],None,None))
            directions=json.loads((paths['walk']/'manifest.json').read_text(encoding='utf-8'))['directions']
            if not directions and style=='original':raise ValueError('No walking directions')
            for direction in directions:
                load_action(paths['walk'],direction,manifest['canvas'],manifest['foot_anchor'])
            resampling=Image.Resampling.LANCZOS if style=='style2' else Image.Resampling.NEAREST
            size=(128*self.scale,128*self.scale)
            photos=[make_photo(im,size,resampling) for im,ms in frames]
            reading_photos=[make_photo(im,size,resampling) for im,ms in reading[1]]
        except (OSError,ValueError,KeyError,TypeError,AssertionError,tk.TclError) as exc:
            app.log('style_switch_rejected',style=style,reason=str(exc))
            self._style_notice('素材未通过检查，保留当前风格。')
            return False
        self.voice.stop()
        self._cancel_drag();self._reset_idle();self.autonomous.cancel(reset_wait=True)
        self.manifest,self.frames=manifest,frames
        self.reading_resource,self.reading_frames,self.reading_wait,self.reading_duration=reading
        self.character_style=style;self.style_asset_paths=paths;self.style_resampling=resampling
        self.photos={self.scale:photos};self.reading_photos={self.scale:reading_photos}
        self.walk_trial=WalkTrial(self,paths['walk'])
        self.manual_action=ManualActionTrial(self,paths['actions'])
        self.grab_sway=GrabSway(self,paths['grab'])
        self.autonomous=AutonomousActions(self,app.ROOT/'behavior_config.json',paths['walk'])
        # This art trial uses manual walks until the user has seen the motion.
        if style=='style2':self.autonomous.suspended=True
        self.style2_motion=manifest.get('motion','rest')
        self._sway_entry=[];self._sway_exit_target=None
        self.idle_blink.bind()
        self.frame_index=0;self.label.configure(image=photos[0])
        self.settings['character_style']=style;app.save_settings(self.settings)
        self._schedule_next_frame();self._schedule_reading()
        panel=getattr(self,'walk_controls',None)
        if panel is not None and panel.winfo_exists():panel.refresh_directions()
        self._style_notice('当前：'+STYLE_NAMES[style]+('。静息呼吸＋眨眼＋低头摆脚；拖拽摇晃v07与睡眠V11已试装。' if style=='style2' else '。原有动作全部恢复。'))
        app.log('character_style_changed',style=style,version=manifest.get('version'),visual_acceptance='pending' if style=='style2' else 'previously_accepted')
        return True

    def set_style2_motion(self,name,*,automatic=False,cycles=None):
        import app,random
        from foot_sway import sequence,photos_for
        if self.closing or name not in ('rest','foot_sway'):return False
        if automatic and not self.autonomous.sway.available():return False
        if self.character_style!='style2' and not self.set_style('style2'):return False
        if self.style2_motion=='foot_sway':
            if name=='rest':self._sway_finish_requested=True
            return True
        if name=='rest':return True
        if (not self.visible or self.drag_start is not None or self.manual_action.active
                or self.walk_trial.active or self.reading_index is not None or self.coast.motion.frame.active):return False
        prefs=self.settings['activity_timing']
        if cycles is None:cycles=random.randint(prefs['foot_sway_min_cycles'],prefs['foot_sway_max_cycles'])
        try:
            manifest,frames,landing=sequence(self.style_asset_paths['idle']/'foot_sway',cycles)
            if manifest['canvas']!=self.manifest['canvas'] or manifest['foot_anchor']!=self.manifest['foot_anchor']:
                raise ValueError('Motion canvas or common anchor differs')
            photos=photos_for(frames,(128*self.scale,128*self.scale),self.style_resampling)
        except (OSError,ValueError,KeyError,TypeError,AssertionError,tk.TclError) as exc:
            app.log('style_motion_rejected',motion=name,reason=str(exc))
            self._style_notice('动作素材未通过检查，保留当前动作。');return False
        self._reset_idle()
        self._sway_exit_target=(self.manifest,self.frames,self.photos[self.scale])
        self._sway_finish_requested=False;self._sway_landing=landing;self._sway_cycles=cycles
        self.manifest,self.frames=manifest,frames
        self.photos={self.scale:photos};self.style2_motion='foot_sway';self.frame_index=0
        self.label.configure(image=photos[0]);self._schedule_next_frame()
        self._style_notice(f'摆腿{cycles}轮；开始与结束各一次，完成后回到站立。')
        app.log('foot_sway_started',cycles=cycles,automatic=automatic,version=manifest['version'])
        return True

    def _commit_sway_exit(self):
        target=getattr(self,'_sway_exit_target',None)
        if target is None:return False
        self._sway_exit_target=None;self._sway_entry=[];self._sway_finish_requested=False
        self.manifest,self.frames,photos=target
        if photos[0].width()!=128*self.scale:
            from foot_sway import photos_for
            photos=photos_for(self.frames,(128*self.scale,128*self.scale),self.style_resampling)
        self.photos={self.scale:photos};self.style2_motion='rest';self.frame_index=0
        self.idle_blink.bind();self.label.configure(image=photos[0])
        self._style_notice('已回到站立静息待机。')
        return True

    def _style_notice(self,text):
        if getattr(self,'style_status',None) is not None:self.style_status.set(text)

    def open_style_controls(self):
        if self.closing:return
        self.show()
        window=getattr(self,'style_controls',None)
        if window is not None and window.winfo_exists():window.deiconify();window.lift();return window
        window=tk.Toplevel(self.root);self.style_controls=window
        window.title('莉宝 · 人物风格试装');window.attributes('-topmost',True)
        panel=tk.Frame(window,padx=18,pady=16);panel.pack()
        tk.Label(panel,text='选择人物风格',font=('Microsoft YaHei UI',12)).pack(anchor='w')
        for style,name in STYLE_NAMES.items():
            tk.Button(panel,text=name,width=26,pady=6,command=lambda s=style:self.set_style(s)).pack(pady=5)
        self.style_status=tk.StringVar(value='当前：'+STYLE_NAMES[self.character_style])
        tk.Label(panel,textvariable=self.style_status,wraplength=300,justify='left').pack(pady=8)
        # User-approved large sizes are opt-in buttons in developer tools.
        tk.Label(panel,text='开发者尺寸试看').pack(pady=(8,2))
        sizes=tk.Frame(panel);sizes.pack(pady=4)
        for n in (2,4,5):
            tk.Button(sizes,text=f'{n}倍'+(' · 恢复' if n==2 else ''),width=9,
                      command=lambda scale=n:self.set_scale(scale)).pack(side='left',padx=3)
        tk.Button(panel,text='文字转语音 / 两套声音',command=self.open_voice_text).pack(pady=5)
        tk.Button(panel,text='语音场景检查 / 21条试听',command=self.open_voice_controls).pack(pady=5)
        tk.Label(panel,text='插画风格动作试看').pack(pady=(8,2))
        tk.Label(panel,text='拖拽v07：按住人物移动鼠标，停止后回荡收稳。',wraplength=300).pack(pady=4)
        tk.Button(panel,text='静息呼吸 · 2秒',width=26,command=lambda:self.set_style2_motion('rest')).pack(pady=4)
        tk.Button(panel,text='低头摆腿 · 随机1～3轮',width=26,command=lambda:self.set_style2_motion('foot_sway')).pack(pady=4)
        tk.Button(panel,text='打开走路试装（像素备用）',command=self.open_walk_controls).pack(pady=4)
        window.protocol('WM_DELETE_WINDOW',lambda:(setattr(self,'style_status',None),window.destroy()))
        return window
