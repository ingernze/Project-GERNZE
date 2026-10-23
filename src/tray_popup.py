"""Native Tk trial of the supplied midnight-blue tray menu design."""
import ctypes
import math
import tkinter as tk
try:
    import win32api
except ImportError:
    win32api = None
from ui_theme import portrait, clamp_popup, absolute_position


class TrayPopup(tk.Toplevel):
    def __init__(self, pet, x, y):
        super().__init__(pet.root)
        self.pet=pet
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost',True)
        try:self.attributes('-toolwindow',True)
        except tk.TclError:pass
        self.configure(bg='#161d31')
        monitor=win32api.MonitorFromPoint((x,y),2) if win32api else None
        work=win32api.GetMonitorInfo(monitor)['Work'] if monitor else (0,0,self.winfo_screenwidth(),self.winfo_screenheight())
        dpi=ctypes.c_uint(96);dy=ctypes.c_uint(96)
        try:
            call=ctypes.windll.shcore.GetDpiForMonitor
            call.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
            call.restype=ctypes.c_long
            call(int(monitor),0,ctypes.byref(dpi),ctypes.byref(dy))
        except (OSError,AttributeError):pass
        self.s=max(0.75,dpi.value/96*0.75)
        self.natural_width,self.natural_height=round(288*self.s),round(704*self.s)
        px,py,self.width,self.height=clamp_popup(x,y,self.natural_width,self.natural_height,work)
        self.geometry(f'{self.width}x{self.height}{px:+d}{py:+d}')
        self.c=tk.Canvas(self,width=self.width,height=self.height,bg='#161d31',highlightthickness=1,highlightbackground='#45465e')
        self.c.pack(fill="both",expand=True)
        self.c.configure(scrollregion=(0,0,self.natural_width,self.natural_height))
        self._photo=portrait(self,max(32,round(48*self.s)))
        self.items=[]
        self.hover=None
        self.pressed=None
        self.key_index=0
        self._focus_job=None
        self.draw()
        self.c.bind('<Motion>',self.motion)
        self.c.bind('<Leave>',self.leave)
        self.c.bind('<ButtonPress-1>',self.press)
        self.c.bind('<ButtonRelease-1>',self.release)
        self.bind('<Escape>',lambda e:self.close())
        self.bind('<Down>',lambda e:self.navigate(1))
        self.bind('<Up>',lambda e:self.navigate(-1))
        self.bind('<Tab>',lambda e:self.navigate(1))
        self.bind('<Shift-Tab>',lambda e:self.navigate(-1))
        self.bind('<ISO_Left_Tab>',lambda e:self.navigate(-1))
        self.bind('<Return>',lambda e:self.activate(self.key_index))
        self.bind('<space>',lambda e:self.activate(self.key_index))
        self.bind('<FocusOut>',self.focus_out)
        self.deiconify()
        absolute_position(self,px,py,self.width,self.height)
        self.lift()
        self.focus_force()

    def rect(self,box,fill,outline=''):
        return self.c.create_rectangle(*(v*self.s for v in box),fill=fill,outline=outline)

    def text(self,x,y,t,size=14,color='#eeeaf3',anchor='w'):
        self.c.create_text(x*self.s,y*self.s,text=t,fill=color,anchor=anchor,font=('Microsoft YaHei UI',-round(size*self.s)))

    def icon(self,kind,x,y):
        s=self.s;c=self.c;color='#d8c29a'
        def line(points):c.create_line(*(v*s for v in points),fill=color,width=max(1,1.5*s))
        if kind=='book':
            line([x-8,y-7,x,y-5,x+8,y-7,x+8,y+7,x,y+9,x-8,y+7,x-8,y-7]);line([x,y-5,x,y+9])
        elif kind=='eye':
            c.create_oval((x-8)*s,(y-5)*s,(x+8)*s,(y+5)*s,outline=color,width=s)
            c.create_oval((x-2)*s,(y-2)*s,(x+2)*s,(y+2)*s,fill=color,outline='')
        elif kind=='exit':line([x,y-8,x-7,y-8,x-7,y+8,x,y+8]);line([x-2,y,x+9,y,x+5,y-4]);line([x+9,y,x+5,y+4])
        elif kind=='sound':line([x-7,y-3,x-3,y-3,x+2,y-7,x+2,y+7,x-3,y+3,x-7,y+3,x-7,y-3]);line([x+6,y-5,x+9,y,x+6,y+5])
        else:
            line([x,y-8,x+2,y-2,x+8,y,x+2,y+2,x,y+8,x-2,y+2,x-8,y,x-2,y-2,x,y-8])

    def draw(self):
        self.c.delete('all');self.items=[]
        self.rect((0,0,288,90),'#1e2841')
        self.c.create_image(22*self.s,17*self.s,image=self._photo,anchor='nw')
        self.text(80,34,'莉宝',19);self.text(80,58,'桌面上的小魔女',11,'#aaa8bf')
        self.text(268,61,'✦',17,'#d8c29a','e')
        self.rect((0,89,288,90),'#45465e')
        self.text(21,107,'• 已显示' if self.pet.visible else '• 已隐藏',10,'#aaa8bf')
        self.text(267,107,f'{self.pet.scale}× · '+('正在读书' if self.pet.reading_index is not None else '陪在这里'),10,'#aaa8bf','e')
        self.row(119,'eye','隐藏莉宝' if self.pet.visible else '显示莉宝','hide' if self.pet.visible else 'show')
        self.row(156,'sound','取消静音' if self.pet.muted else '静音','mute','开' if self.pet.muted else '关')
        self.text(22,212,'人物大小',11,'#aaa8bf')
        for n in (1,2,3):
            x=150+(n-1)*36;box=(x,197,x+33,225);idx=len(self.items)
            selected=self.pet.scale==n
            self.rect(box,'#c4b7ed' if selected else '#303a58' if self.hover==idx else '#1e2841','#f2d499' if self.hover==idx else '#45465e')
            self.text(x+16,211,f'{n}×',11,'#211c38' if selected else '#eeeaf3','center')
            self.items.append((box,f'size:{n}'))
        self.rect((21,235,267,236),'#45465e');self.text(22,249,'日常',10,'#aaa8bf')
        self.row(261,'book','打开工作台','workbench:open')
        self.row(298,'book','提醒与资料工具','modules:open')
        reading=self.pet.reading_index is not None
        self.row(335,'star','额度总览','quota:open')
        self.rect((21,378,267,379),'#45465e');self.text(22,392,'开发者工具',10,'#aaa8bf')
        self.row(404,'book','开发者：结束读书' if reading else '开发者：读书预览','reading:finish' if reading else 'reading:play')
        self.row(441,'star','开发者：走路预览','walk:open')
        self.row(477,'star','开发者：睡觉 / 摸头预览','actions:open')
        self.row(514,'star','开发者：人物风格 / 语音','style:open')
        self.row(551,'star','开发者：Codex 活动观察','codex-activity:open')
        self.row(588,'sound','开发者：声音模块','voice_modules:open')
        self.rect((0,633,288,634),'#45465e')
        self.row(644,'exit','退出莉宝','exit')
        self.text(22,691,'GERNZE',9,'#86879e');self.text(267,691,'Esc 收起 · ↑↓ 选择',9,'#86879e','e')

    def row(self,y,icon,label,command,tail=''):
        idx=len(self.items);box=(13,y,275,y+35)
        if self.hover==idx or self.pressed==idx:
            self.rect(box,'#161d31' if self.pressed==idx else '#303a58','#f2d499' if self.pressed==idx else '#45465e')
        shift=1 if self.pressed==idx else 0
        self.icon(icon,33,y+17+shift);self.text(55,y+17+shift,label,12 if command in ("walk:open","actions:open","reading:play","reading:finish","style:open","codex-activity:open","voice_modules:open") else 13)
        if tail:self.text(262,y+17,tail,11,'#aaa8bf','e')
        self.items.append((box,command))

    def hit(self,event):
        x,y=self.c.canvasx(event.x)/self.s,self.c.canvasy(event.y)/self.s
        return next((i for i,(b,_) in enumerate(self.items) if b[0]<=x<=b[2] and b[1]<=y<=b[3]),None)

    def motion(self,event):
        i=self.hit(event)
        if i!=self.hover:self.hover=i;self.draw()

    def leave(self,event):
        self.hover=None;self.draw()

    def press(self,event):
        self.pressed=self.hit(event);self.draw()

    def release(self,event):
        i=self.hit(event);p=self.pressed;self.pressed=None
        if i is not None and i==p:self.activate(i)
        else:self.draw()

    def navigate(self,delta):
        self.key_index=(self.key_index+delta)%len(self.items)
        self.hover=self.key_index;self.draw()
        y0=self.items[self.key_index][0][1]*self.s
        y1=self.items[self.key_index][0][3]*self.s
        if y0<self.c.canvasy(0) or y1>self.c.canvasy(0)+self.height:self.c.yview_moveto(max(0,y0-12)/self.natural_height)
        return 'break'

    def activate(self,i):
        if i is None:return
        command=self.items[i][1]
        self.close()
        self.pet._enqueue_command(command)

    def focus_out(self,event):
        if self._focus_job is None:self._focus_job=self.after_idle(self.check_focus)

    def check_focus(self):
        self._focus_job=None
        focus=self.focus_displayof()
        if focus is None or focus.winfo_toplevel()!=self:self.close()

    def close(self):
        if self._focus_job is not None:self.after_cancel(self._focus_job)
        self._focus_job=None
        self.destroy()

