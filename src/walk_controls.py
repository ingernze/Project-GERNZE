"""Event-driven manual walking controls; no automatic walking."""
import tkinter as tk
import json

LABELS = {'up': '向上 ↑', 'down': '向下 ↓', 'left': '向左 ←', 'right': '向右 →'}


class WalkControls(tk.Toplevel):
    def __init__(self, pet):
        super().__init__(pet.root)
        self.pet = pet
        self.title('赫宝 · 四向八帧试走')
        self.configure(bg='#111c30')
        self.resizable(False, False)
        self.attributes('-topmost', True)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.mode = tk.StringVar(value='in_place')
        self.status = tk.StringVar(value='先选方向看原地循环，再切换移动试走。')
        self.buttons = {}
        panel = tk.Frame(self, bg='#111c30', padx=18, pady=15)
        panel.pack(fill='both', expand=True)
        tk.Label(panel, text='四向八帧 · 手动试走', bg='#111c30',
                 fg='#eeeae1', font=('Microsoft YaHei UI', 13)).pack(anchor='w')
        modes = tk.Frame(panel, bg='#111c30')
        modes.pack(anchor='w', pady=(12, 8))
        for text, value in (('原地循环', 'in_place'), ('移动试走', 'moving')):
            tk.Radiobutton(modes, text=text, variable=self.mode, value=value,
                           bg='#111c30', fg='#d5e1f1', selectcolor='#253b58',
                           activebackground='#111c30', activeforeground='#ffffff',
                           font=('Microsoft YaHei UI', 10)).pack(side='left', padx=(0, 12))
        pad = tk.Frame(panel, bg='#111c30')
        pad.pack(pady=6)
        for direction, row, column in (('up', 0, 1), ('left', 1, 0),
                                       ('right', 1, 2), ('down', 2, 1)):
            button = tk.Button(pad, text=LABELS[direction], width=9, pady=5,
                               bg='#253b58', fg='#eeeae1',
                               activebackground='#3b5578', activeforeground='#ffffff',
                               relief='flat', font=('Microsoft YaHei UI', 10),
                               command=lambda d=direction: self.play(d))
            button.grid(row=row, column=column, padx=4, pady=4)
            self.buttons[direction] = button
        tk.Button(pad, text='停止', width=9, pady=5, relief='flat',
                  bg='#3f354a', fg='#eeeae1',
                  command=self.stop).grid(row=1, column=1, padx=4, pady=4)
        tk.Label(panel, textvariable=self.status, bg='#111c30', fg='#bdcadc',
                 justify='left', wraplength=330).pack(anchor='w', pady=(8, 6))
        tk.Label(panel, text='每次3圈，结束回待机。\n各方向只做手动试走。\n确认观感后再安排随机走动。',
                 bg='#111c30', fg='#a9b8ce', justify='left',
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w')
        self.refresh_directions()
        self.update_idletasks()
        self.lift()

    def refresh_directions(self):
        try:
            directions=json.loads((self.pet.walk_trial.asset_dir/'manifest.json').read_text(encoding='utf-8'))['directions']
        except (OSError,ValueError,KeyError):directions={}
        for direction,button in self.buttons.items():button.configure(state='normal' if direction in directions else 'disabled')
        if self.pet.character_style=='style2':self.status.set('插画风格当前为静息呼吸与低头摆脚。四向走路缺少匹配素材，切到像素备用可试走。')
        else:self.status.set('像素备用四向八帧，可选原地或移动试走。')

    def play(self, direction):
        if self.pet.start_walk(direction, moving=self.mode.get() == 'moving'):
            label = LABELS[direction]
            self.status.set(label + (' · 移动试走3圈' if self.mode.get() == 'moving'
                                      else ' · 原地循环3圈') + '，结束后可选下一方向。')
        else:
            self.status.set('本次未开始，已返回可用待机。')

    def unavailable(self):
        self.status.set('这一方向的资源暂不可用，赫宝已返回待机。')

    def stop(self):
        self.pet.walk_trial.stop()
        self.status.set('已停止，返回待机。')

    def close(self):
        if not self.pet.closing and self.pet.walk_trial.active:
            self.pet.walk_trial.stop()
        self.destroy()
