"""Small manual controls; no status polling or automatic action triggers."""
import tkinter as tk

class ActionControls(tk.Toplevel):
    def __init__(self,pet):
        super().__init__(pet.root);self.pet=pet
        self.title('赫宝 · 动作试装')
        self.configure(bg='#111c30');self.resizable(False,False)
        self.attributes('-topmost',True);self.protocol('WM_DELETE_WINDOW',self.close)
        self.status=tk.StringVar(value='候选动作，观感等待你确认')
        tk.Label(self,text='睡觉与摸头 · 手动试装',bg='#111c30',fg='#eeeae1',
                 font=('Microsoft YaHei UI',12)).pack(padx=18,pady=(14,8))
        row=tk.Frame(self,bg='#111c30');row.pack(padx=12,pady=4)
        for text,command in (('摘帽睡觉',lambda:pet.start_manual_action('sleep')),
                              ('醒来戴帽',pet.manual_action.wake),
                              ('摸头回应',lambda:pet.start_manual_action('headpat'))):
            tk.Button(row,text=text,command=command,bg='#22334c',fg='#eeeae1',
                      activebackground='#354660',activeforeground='white',
                      relief='flat',padx=10,pady=7).pack(side='left',padx=4)
        tk.Label(self,textvariable=self.status,bg='#111c30',fg='#bdcadc',
                 font=('Microsoft YaHei UI',10),wraplength=350).pack(padx=16,pady=10)
        tk.Label(self,text='睡觉会持续循环；点击人物不会自动唤醒。\n摸头按钮只播放一次；拖动、隐藏会取消动作。',
                 bg='#111c30',fg='#9eacc2',justify='left').pack(padx=16,pady=(0,10))
        tk.Button(self,text='停止并回待机',command=pet.manual_action.stop,
                  bg='#22334c',fg='#eeeae1',relief='flat',padx=12,pady=5).pack(pady=(0,14))
    def close(self):
        self.pet.manual_action.stop();self.destroy()
