"""Native text-to-speech entry, using existing starry-study components."""
import time
import tkinter as tk
from tkinter import ttk
from ui_theme import BG,PANEL,INK,MUTED,ACCENT,BORDER,ERROR,GOOD,QUIET,label,Button,font,header,configure_window,PREFIX

class VoiceTextWindow(tk.Toplevel):
    def __init__(self,pet):
        super().__init__(pet.root);self.pet=pet;self.module=pet.voice_module;self.closed=False
        configure_window(self,'莉宝 · 声音',700,630,(580,540))
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Escape>',lambda _:self.close())
        self.bind('<Control-Return>',self._shortcut)
        header(self,'让莉宝说一句','写下你想听的话，选择声音，然后播放。')
        body=tk.Frame(self,bg=BG);body.pack(fill='both',expand=True,padx=22,pady=(0,16));body.columnconfigure(0,weight=1);body.rowconfigure(2,weight=1)
        self._clock_job=None;self._started=None;self._last_api=False;self.reply_window=None
        self._choices=self.module.choices();selected=self.module.selection()
        selectors=tk.Frame(body,bg=PANEL,highlightbackground=BORDER,highlightthickness=1)
        selectors.grid(row=0,column=0,sticky='ew',pady=(0,14));self.combos={};self.ids={}
        for column,(key,group,title) in enumerate([('gpt_id','gpt_options','GPT 权重'),('sovits_id','sovits_options','SoVITS 权重'),('reference_id','references','参考音频')]):
            selectors.columnconfigure(column,weight=1,uniform='voice_choices')
            cell=tk.Frame(selectors,bg=PANEL);cell.grid(row=0,column=column,sticky='nsew',padx=10,pady=12)
            label(cell,title,11,MUTED).pack(anchor='w',pady=(0,6))
            entries=self._choices[group];self.ids[key]=[item['id'] for item in entries]
            combo=ttk.Combobox(cell,values=[item['label'] for item in entries],state='readonly',width=18,style=PREFIX+'TCombobox',takefocus=True)
            combo.current(self.ids[key].index(selected[key]));combo.pack(fill='x');combo.bind('<<ComboboxSelected>>',self.save_selection)
            self.combos[key]=combo
        top=tk.Frame(body,bg=BG);top.grid(row=1,column=0,sticky='ew',pady=(0,6))
        label(top,'要说的话',13,INK).pack(side='left')
        self.mode=tk.StringVar(self,'照着文字说')
        self.mode_combo=ttk.Combobox(top,textvariable=self.mode,values=['照着文字说','API 回复后说'],
            state='readonly',width=15,style=PREFIX+'TCombobox',font=font(self,12))
        self.mode_combo.pack(side='left',padx=(16,0))
        self.mode_combo.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.count=tk.StringVar(self,'0 / 500');self.count_label=label(top,size=11,color=MUTED,textvariable=self.count);self.count_label.pack(side='right')
        area=tk.Frame(body,bg=PANEL,highlightbackground=BORDER,highlightthickness=1);area.grid(row=2,column=0,sticky='nsew')
        self.text=tk.Text(area,wrap='word',height=7,bg=PANEL,fg=INK,insertbackground=ACCENT,selectbackground=ACCENT,selectforeground=BG,font=font(self,14),relief='flat',padx=14,pady=12,undo=True,highlightthickness=0)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.text.yview,style=PREFIX+'Vertical.TScrollbar');scroll.pack(side='right',fill='y')
        self.text.configure(yscrollcommand=scroll.set);self.text.pack(fill='both',expand=True)
        self.text.bind('<Control-a>',self.select_all)
        self.text.bind('<Control-A>',self.select_all)
        self.text.bind('<<Modified>>',self._changed);self.text.insert('1.0','欢迎回来，我们慢慢来。')
        helper=tk.Frame(body,bg=BG);helper.grid(row=3,column=0,sticky='ew',pady=(6,10))
        self.hint=tk.StringVar(self,'Ctrl + Enter 播放 · 首次需要加载声音')
        label(helper,textvariable=self.hint,size=11,color=QUIET,wraplength=360).pack(side='left',fill='x',expand=True)
        from voice_api_window import open_voice_api
        Button(helper,text='API 设置',command=lambda:open_voice_api(pet)).pack(side='right')
        self.notice=tk.StringVar(self,'');label(body,size=12,color=MUTED,textvariable=self.notice,wraplength=650).grid(row=4,column=0,sticky='ew',pady=(0,10))
        controls=tk.Frame(body,bg=BG);controls.grid(row=5,column=0,sticky='ew')
        self.play=Button(controls,text='生成并播放',primary=True,command=self.generate);self.play.pack(side='left',padx=(0,8))
        self.stop=Button(controls,text='停止 / 取消',command=self.cancel);self.stop.pack(side='left')
        self.mute=Button(controls,text='取消静音',command=pet.toggle_mute);self.mute.pack(side='right')
        footer=tk.Frame(body,bg=BG);footer.grid(row=6,column=0,sticky='ew',pady=(10,0))
        self.sound=tk.StringVar(self,'');label(footer,size=11,color=QUIET,textvariable=self.sound).pack(side='left')
        Button(footer,text='固定场景录音',command=pet.open_voice_controls).pack(side='right')
        self.reply_button=Button(footer,text='查看 API 回复',command=self.show_reply)
        self.reply_button.pack(side='right',padx=8)
        self.status=tk.StringVar(self,'');self.status_label=label(body,size=12,color=MUTED,textvariable=self.status,wraplength=650);self.status_label.grid(row=7,column=0,sticky='ew',pady=(10,0))
        self.progress=ttk.Progressbar(body,mode='indeterminate',length=240,style=PREFIX+'Horizontal.TProgressbar')
        self.progress.grid(row=8,column=0,sticky='ew',pady=(5,0));self.progress.grid_remove()
        self._progress_running=False
        self.module.on_change=self.refresh;self.refresh();self.text.focus_set()
    def select_all(self,_event=None):
        self.text.tag_add('sel','1.0','end-1c');self.text.mark_set('insert','end-1c');return 'break'
    def _changed(self,_event=None):
        if not self.text.edit_modified():return
        length=len(self.text.get('1.0','end-1c').strip());self.count.set(f'{length} / 500')
        self.count_label.configure(fg=ERROR if length>500 else MUTED);self.text.edit_modified(False)
    def _shortcut(self,_event):self.generate();return 'break'
    def save_selection(self,_event=None):
        try:
            self.module.set_selection(**{key:self.ids[key][combo.current()] for key,combo in self.combos.items()})
        except (OSError,ValueError,RuntimeError) as exc:self.status.set(str(exc));self.status_label.configure(fg=ERROR);return False
        return True
    def generate(self):
        if self.closed or self.module.busy:return
        if not self.save_selection():return
        try:
            value=self.text.get('1.0','end-1c').strip()
            if not value or len(value)>500:raise ValueError('请输入 1 至 500 字的文本')
            api_mode=self.mode.get()=='API 回复后说'
            if api_mode:self.module.dialogue([{'role':'user','content':value}])
            else:self.module.speak_text(value)
            self._last_api=api_mode
        except (OSError,ValueError,RuntimeError) as exc:
            self.status.set(str(exc));self.status_label.configure(fg=ERROR)
        self.refresh(preserve_error=True)
    def show_reply(self):
        result=self.module.last_result
        if not result or not self._last_api:return
        window=self.reply_window
        if window is None or not window.winfo_exists():
            window=self.reply_window=tk.Toplevel(self)
            configure_window(window,'莉宝 · API 回复',570,360,(420,260))
            header(window,'莉宝的回复')
            body=tk.Frame(window,bg=PANEL);body.pack(fill='both',expand=True,padx=22,pady=(0,18))
            area=tk.Text(body,wrap='word',bg=PANEL,fg=INK,font=font(window,14),relief='flat',
                         padx=16,pady=12,selectbackground=ACCENT,selectforeground=BG)
            scroll=ttk.Scrollbar(body,command=area.yview,style=PREFIX+'Vertical.TScrollbar')
            scroll.pack(side='right',fill='y');area.configure(yscrollcommand=scroll.set)
            area.pack(fill='both',expand=True);window.reply_area=area
            window.bind('<Escape>',lambda _:window.destroy())
        window.deiconify();window.lift()
        area=window.reply_area;area.configure(state='normal')
        area.delete('1.0','end');area.insert('1.0',result['text']);area.configure(state='disabled')
    def cancel(self):self.module.cancel();self.refresh()
    def _tick(self):
        self._clock_job=None
        if not self.closed:self.refresh()
    def refresh(self,preserve_error=False):
        if self.closed:return
        busy=self.module.busy
        playing=self.pet.voice.owner=='voice_module' and self.pet.voice._active()
        if busy and self._started is None:self._started=time.monotonic()
        if not busy:self._started=None
        if (busy or playing) and self._clock_job is None:self._clock_job=self.after(500,self._tick)
        elif not busy and not playing and self._clock_job is not None:
            self.after_cancel(self._clock_job);self._clock_job=None
        self.mode_combo.configure(state='disabled' if busy else 'readonly')
        api_mode=self.mode.get()=='API 回复后说'
        self.hint.set('把这段话发给专用 API，再朗读回复。' if api_mode else 'Ctrl + Enter 播放 · 首次需要加载声音')
        self.reply_button.configure(state='normal' if self._last_api and self.module.last_result else 'disabled')
        if busy and not self._progress_running:
            self.progress.grid();self.progress.start(40);self._progress_running=True
        elif not busy and self._progress_running:
            self.progress.stop();self.progress.grid_remove();self._progress_running=False
        self.play.configure(state='disabled' if busy else 'normal')
        self.stop.configure(state='normal' if busy or playing else 'disabled')
        for combo in self.combos.values():combo.configure(state='disabled' if busy else 'readonly')
        self.mute.configure(text='取消静音' if self.pet.muted else '静音')
        self.sound.set(f"声音大小：{self.pet.settings['voice_volume_percent']}%")
        self.notice.set('当前静音：取消静音后再播放。' if self.pet.muted else '音量为0：请在固定场景录音中调高。' if self.pet.settings['voice_volume_percent']==0 else '会联网获取回复，再用当前声音播放。' if api_mode else '莉宝会照着你输入的文字说话。')
        if not preserve_error:
            value=self.module.status
            message=value['message']
            if busy and self._started is not None:
                message+=f'  已等待 {int(time.monotonic()-self._started)} 秒'
            elif value['state']=='played':
                message='正在播放生成语音。' if playing else '播放结束，可以再写一句。'
            self.status.set(message);self.status_label.configure(fg=ERROR if value['state']=='error' else GOOD if value['state']=='played' else MUTED)
    def close(self):
        if self.closed:return
        if self._clock_job is not None:
            self.after_cancel(self._clock_job);self._clock_job=None
        self.module.on_change=None;self.progress.stop();self._progress_running=False;self.module.cancel();self.closed=True
        self.pet.voice_text_window=None;self.destroy()

def open_voice_text(pet):
    if pet.closing:return
    pet.show()
    window=getattr(pet,'voice_text_window',None)
    if window is not None and window.winfo_exists():
        window.deiconify();window.lift();window.refresh();window.text.focus_set();return window
    try:
        pet.voice_module.choices();pet.voice_module.selection()
        window=VoiceTextWindow(pet)
    except (OSError,ValueError,RuntimeError) as error:
        from tkinter import messagebox
        messagebox.showerror('莉宝 · 声音',str(error),parent=pet.root);return
    pet.voice_text_window=window;return window
