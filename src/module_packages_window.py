"""Native offline package picker; large archive work stays off the Tk thread."""
import queue, threading, tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from hecate_ui import configure_window, header, label, Button, panel, BG, MUTED
from optional_modules import IDS

def open_packages(pet):
    old = getattr(pet, 'packages_window', None)
    if old is not None and old.winfo_exists(): old.deiconify();old.lift();return old
    window = PackageWindow(pet);pet.packages_window = window;return window

class PackageWindow(tk.Toplevel):
    def __init__(self, pet):
        super().__init__(pet.root);self.pet=pet;self.manager=pet.optional_modules
        self.busy=False;self.results=queue.SimpleQueue();self.job=None
        configure_window(self,'赫宝 · 安装与移除模块',680,640,minimum=(580,600))
        header(self,'可选模块','选择单独下载的模块 ZIP 安装；移除功能时保留个人记录。').pack(fill='x')
        self.content=tk.Frame(self,bg=BG);self.content.pack(fill='both',expand=True,padx=20,pady=10)
        self.status=label(self,'',color=MUTED);self.status.pack(fill='x',padx=20,pady=8)
        self.install_button=Button(self,text='选择模块 ZIP 安装',command=self.pick);self.install_button.pack(pady=(0,15))
        self.protocol('WM_DELETE_WINDOW',self.close);self.refresh()

    def refresh(self):
        for child in self.content.winfo_children():child.destroy()
        for item in self.manager.snapshot()['items']:
            card=panel(self.content,item['title'],'已安装' if item['installed'] else '未安装')
            card.pack(fill='x',pady=4)
            if item['installed'] and self.manager.managed:
                Button(card,text='移除模块',command=lambda key=item['id']:self.remove(key)).pack(side='right',padx=10,pady=8)
            if item['id']=='voice_engine' and item['installed'] and self.manager.managed:
                Button(card,text='模型导入说明',command=self.import_help).pack(side='right',padx=10,pady=8)
        self.install_button.configure(state='disabled' if self.busy or not self.manager.managed else 'normal')
        if not self.manager.managed:self.status.configure(text='兼容版：现有模块继续保留。请用模块候选启动版体验安装与移除。')

    def import_help(self):
        import os
        os.startfile(str(self.manager.voice_home()/'00_导入声音与精简说明.md'))

    def safe_to_change(self):
        if self.busy:return False
        voice=self.pet.voice_module
        if voice.busy or (getattr(voice,'_worker',None) is not None and voice._worker.is_alive()):
            messagebox.showinfo('请先停止生成','请先停止正在生成的语音，再安装或移除模块。',parent=self);return False
        return True

    def pick(self):
        if not self.safe_to_change():return
        path=filedialog.askopenfilename(parent=self,title='选择赫宝可选模块 ZIP',filetypes=[('赫宝模块','*.zip')])
        if path:self.run(lambda:self.manager.install(path))

    def remove(self,key):
        if not self.safe_to_change():return
        if messagebox.askyesno('移除'+IDS[key],'移除功能文件，保留学习记录、导入模型和个人设置。继续吗？',parent=self):
            self.run(lambda:self.manager.uninstall(key))

    def run(self,operation):
        # Close only this candidate's owned playback and engine before replacing files.
        self.pet.voice.stop();closing=self.pet.voice_module.close_background()
        for name in ('voice_text_window','voice_api_window','voice_controls','voice_bindings_window','voice_modules_window'):
            window=getattr(self.pet,name,None)
            if window is not None and window.winfo_exists():window.destroy()
            setattr(self.pet,name,None)
        self.busy=True;self.status.configure(text='正在校验并整理模块，请稍候……');self.refresh()
        def worker():
            try:
                if closing is not None:
                    closing.join(15)
                    if closing.is_alive():raise TimeoutError('语音仍在释放，模块文件未修改，请稍后重试。')
                self.results.put((True,operation()))
            except Exception as error:self.results.put((False,str(error)))
        threading.Thread(target=worker,name='hecate-package-install',daemon=False).start()
        self.job=self.after(100,self.drain)

    def drain(self):
        try:ok,result=self.results.get_nowait()
        except queue.Empty:self.job=self.after(100,self.drain);return
        self.job=None;self.busy=False
        self.pet.reload_optional_voice()
        self.status.configure(text='已完成。工作台点击“刷新模块状态”查看变化。' if ok else '未完成：'+result)
        self.refresh()

    def close(self):
        if self.busy:
            messagebox.showinfo('正在整理','请等当前安装或移除完成，避免中断文件替换。',parent=self);return
        if self.job is not None:self.after_cancel(self.job)
        self.pet.packages_window=None;self.destroy()
