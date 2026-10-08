"""Window-local A / 星夜书房 components. No theme switch, network or polling."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, font as tkfont
from PIL import Image, ImageDraw, ImageTk

BG = '#161d31'
PANEL = '#1e2841'
RAISED = '#25304b'
INK = '#eeeaf3'
MUTED = '#aaa8bf'
QUIET = '#86879e'
ACCENT = '#c4b7ed'
ACCENT_INK = '#211c38'
GOLD = '#d8c29a'
BORDER = '#45465e'
HOVER = '#303a58'
FOCUS = '#f2d499'
ERROR = '#edaaa9'
GOOD = '#b4d7cb'
PREFIX = 'Hecate.'
_resources = {}


def family(widget):
    names = set(tkfont.families(widget))
    return next((n for n in ('Microsoft YaHei UI', 'Microsoft YaHei',
                             'Noto Sans CJK SC', 'WenQuanYi Micro Hei') if n in names),
                tkfont.nametofont('TkDefaultFont', root=widget).actual('family'))


def ui_scale(widget):
    if os.name != 'nt':
        return 1.0
    try:
        get_dpi = ctypes.windll.user32.GetDpiForWindow
        get_dpi.argtypes = [ctypes.c_void_p]
        get_dpi.restype = ctypes.c_uint
        dpi = get_dpi(widget.winfo_toplevel().winfo_id())
        return max(1.0, dpi / 96.0) if dpi else 1.0
    except (AttributeError, OSError, tk.TclError):
        return 1.0


def font(widget, size=13, bold=False, serif=False):
    name = family(widget)
    if serif:
        names = set(tkfont.families(widget))
        name = next((n for n in ('Georgia', 'Liberation Serif', 'DejaVu Serif')
                     if n in names), name)
    return name, -round(size * ui_scale(widget)), 'bold' if bold else 'normal'


def _button_photo(root, fill, border):
    image = Image.new('RGBA', (20, 20))
    ImageDraw.Draw(image).rounded_rectangle((1, 1, 18, 18), radius=6,
                                           fill=fill, outline=border, width=1)
    return ImageTk.PhotoImage(image, master=root)


def install_styles(widget):
    """Register namespaced elements in the current theme; leave T* unchanged."""
    root = widget._root()
    key = str(root.tk)
    if key in _resources:
        return ttk.Style(root)
    style = ttk.Style(root)
    # Vista native fields ignore dark colors. Import only these namespaced
    # elements from clam; never change the process-wide ttk theme.
    if os.name == 'nt':
        for alias, source in [('Horizontal.Scale.trough','Horizontal.Scale.trough'),
                              ('Horizontal.Scale.slider','Horizontal.Scale.slider'),
                              ('Horizontal.Progressbar.trough','Horizontal.Progressbar.trough'),
                              ('Horizontal.Progressbar.pbar','Horizontal.Progressbar.pbar'),
                              ('Entry.field','Entry.field'),
                              ('Combobox.field','Combobox.field'),
                              ('Combobox.downarrow','Combobox.downarrow'),
                              ('Checkbutton.indicator','Checkbutton.indicator'),
                              ('Notebook.client','Notebook.client'),
                              ('Notebook.tab','Notebook.tab'),
                              ('Vertical.Scrollbar.trough','Vertical.Scrollbar.trough'),
                              ('Vertical.Scrollbar.thumb','Vertical.Scrollbar.thumb'),
                              ('Vertical.Scrollbar.uparrow','Vertical.Scrollbar.uparrow'),
                              ('Vertical.Scrollbar.downarrow','Vertical.Scrollbar.downarrow')]:
            style.element_create(PREFIX+alias, 'from', 'clam', source)
        style.layout(PREFIX+'TEntry', [(PREFIX+'Entry.field', {'sticky':'nswe', 'children':[
            ('Entry.padding', {'sticky':'nswe', 'children':[('Entry.textarea', {'sticky':'nswe'})]})]})])
        style.layout(PREFIX+'TCombobox', [(PREFIX+'Combobox.field', {'sticky':'nswe', 'children':[
            (PREFIX+'Combobox.downarrow', {'side':'right', 'sticky':'ns'}),
            ('Combobox.padding', {'expand':1, 'sticky':'nswe', 'children':[
                ('Combobox.textarea', {'sticky':'nswe'})]})]})])
        style.layout(PREFIX+'TCheckbutton', [('Checkbutton.padding', {'sticky':'nswe','children':[
            (PREFIX+'Checkbutton.indicator', {'side':'left','sticky':''}),
            ('Checkbutton.focus', {'side':'left','sticky':'w','children':[
                ('Checkbutton.label', {'sticky':'nswe'})]})]})])
        style.layout(PREFIX+'TNotebook', [(PREFIX+'Notebook.client', {'sticky':'nswe'})])
        style.layout(PREFIX+'TNotebook.Tab', [(PREFIX+'Notebook.tab', {'sticky':'nswe','children':[
            ('Notebook.padding', {'side':'top','sticky':'nswe','children':[
                ('Notebook.focus', {'side':'top','sticky':'nswe','children':[
                    ('Notebook.label', {'side':'top','sticky':''})]})]})]})])
        style.layout(PREFIX+'Vertical.TScrollbar', [(PREFIX+'Vertical.Scrollbar.trough', {'sticky':'ns','children':[
            (PREFIX+'Vertical.Scrollbar.uparrow', {'side':'top','sticky':''}),
            (PREFIX+'Vertical.Scrollbar.downarrow', {'side':'bottom','sticky':''}),
            (PREFIX+'Vertical.Scrollbar.thumb', {'sticky':'nswe'})]})])
    if os.name == 'nt':
        style.layout(PREFIX+'Horizontal.TScale', [(PREFIX+'Horizontal.Scale.trough', {'sticky':'we','children':[
            (PREFIX+'Horizontal.Scale.slider', {'side':'left','sticky':''})]})])
        style.layout(PREFIX+'Horizontal.TProgressbar', [(PREFIX+'Horizontal.Progressbar.trough', {'sticky':'nswe','children':[
            (PREFIX+'Horizontal.Progressbar.pbar', {'side':'left','sticky':'ns'})]})])
    style.configure(PREFIX+'Horizontal.TScale', background=ACCENT, troughcolor=PANEL, bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
    style.map(PREFIX+'Horizontal.TScale', background=[('active', FOCUS)], bordercolor=[('focus', FOCUS)])
    style.configure(PREFIX+'Horizontal.TProgressbar', background=ACCENT, troughcolor=PANEL,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, thickness=5, borderwidth=0)
    photos = []
    for name, colors in {'Button': (RAISED, HOVER, BG, RAISED, INK),
                         'Primary': (ACCENT, '#d2c5f6', '#aa9ed2', RAISED, ACCENT_INK)}.items():
        normal, hover, pressed, disabled, foreground = colors
        states = [_button_photo(root, normal, BORDER if name == 'Button' else ACCENT),
                  _button_photo(root, disabled, BORDER),
                  _button_photo(root, pressed, '#a69abf'),
                  _button_photo(root, hover, '#a69abf'),
                  _button_photo(root, normal, FOCUS)]
        photos.extend(states)
        element = PREFIX + name
        style.element_create(element, 'image', states[0], ('disabled', states[1]),
                             ('pressed', states[2]), ('active', states[3]),
                             ('focus', states[4]), border=8, sticky='nsew')
        style.layout(element + '.TButton', [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [
                ('Button.label', {'sticky': 'nsew'})]})]})])
        style.configure(element + '.TButton', foreground=foreground, background=BG,
                        font=font(root), padding=(9, 3), anchor='center')
        style.map(element + '.TButton', foreground=[('disabled', QUIET)])
    for name, color in [('TFrame', BG), ('Panel.TFrame', PANEL), ('TLabel', BG),
                        ('Panel.TLabel', PANEL), ('TLabelframe', PANEL)]:
        style.configure(PREFIX + name, background=color, foreground=INK,
                        font=font(root), borderwidth=0)
    style.configure(PREFIX + 'TLabelframe.Label', background=PANEL, foreground=GOLD,
                    font=font(root, 12))
    style.configure(PREFIX + 'TEntry', fieldbackground=RAISED, foreground=INK,
                    insertcolor=INK, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, padding=7, font=font(root))
    style.map(PREFIX + 'TEntry', bordercolor=[('focus', FOCUS)],
              foreground=[('disabled', QUIET)])
    style.configure(PREFIX + 'TCombobox', fieldbackground=RAISED, background=RAISED,
                    foreground=INK, arrowcolor=MUTED, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=6, font=font(root))
    style.map(PREFIX + 'TCombobox', fieldbackground=[('readonly', RAISED)],
              foreground=[('disabled', QUIET), ('readonly', INK)],
              selectbackground=[('readonly', ACCENT)],
              selectforeground=[('readonly', ACCENT_INK)],
              bordercolor=[('focus', FOCUS)])
    style.configure(PREFIX + 'TCheckbutton', background=PANEL, foreground=INK,
                    font=font(root), padding=(0, 5))
    style.map(PREFIX + 'TCheckbutton', background=[('active', PANEL)],
              foreground=[('disabled', QUIET)])
    style.configure(PREFIX + 'TNotebook', background=BG, borderwidth=0,
                    tabmargins=(0, 0, 0, 8), bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure(PREFIX + 'TNotebook.Tab', background=BG, foreground=MUTED,
                    padding=(20, 11), font=font(root), bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map(PREFIX + 'TNotebook.Tab', background=[('selected', PANEL), ('active', HOVER)],
              foreground=[('selected', INK)])
    style.configure(PREFIX + 'Vertical.TScrollbar', background=BORDER,
                    troughcolor=BG, arrowcolor=MUTED, borderwidth=0, arrowsize=12)
    _resources[key] = photos
    root.bind('<Destroy>', lambda event: _resources.pop(key, None) if event.widget == root else None, add='+')
    return style


def label(parent, text='', size=13, color=INK, **kwargs):
    if 'wraplength' in kwargs:
        kwargs['wraplength'] = round(kwargs['wraplength'] * ui_scale(parent))
    widget = tk.Label(parent, text=text, fg=color, bg=parent.cget('background'),
                      font=font(parent, size), anchor='w', justify='left', **kwargs)
    if 'wraplength' in kwargs:
        limit = kwargs['wraplength']
        widget.bind('<Configure>', lambda event: widget.configure(
            wraplength=max(80, min(limit, event.width-4))))
    return widget


class Button(ttk.Button):
    """Native keyboard/press semantics with a one-idle-turn activation lock."""
    def __init__(self, parent, text='', command=None, primary=False, **kwargs):
        install_styles(parent)
        self._callback = command
        self._busy = False
        self._job = None
        self._mouse_armed = False
        self._last_mouse_completed = False
        super().__init__(parent, text=text, command=self._activate,
                         style=PREFIX + ('Primary' if primary else 'Button') + '.TButton',
                         takefocus=True, **kwargs)
        self.bind('<Destroy>', self._destroy, add='+')
        self.bind('<Return>', self._keyboard_activate)
        self.bind('<KP_Enter>', self._keyboard_activate)
        self.bind('<ButtonPress-1>', self._mouse_press)
        self.bind('<ButtonRelease-1>', self._mouse_release)
        self.bind('<Double-Button-1>', self._double_press)
        self.bind('<Double-ButtonRelease-1>', self._double_release)

    def _keyboard_activate(self, _event):
        self.invoke()
        return 'break'

    def _double_release(self, _event):
        if not self._last_mouse_completed:
            return self._mouse_release(_event)
        self._mouse_armed = False
        self.state(['!pressed'])
        return 'break'

    def _double_press(self, event):
        if self._last_mouse_completed:
            return 'break'
        self._mouse_press(event)

    def _mouse_press(self, _event):
        self._mouse_armed = not self.instate(['disabled'])
        self._last_mouse_completed = False

    def _mouse_release(self, event):
        armed, self._mouse_armed = self._mouse_armed, False
        if not armed or not (0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()):
            self._last_mouse_completed = False
            self.state(['!pressed', '!active'])
            return 'break'
        self._last_mouse_completed = True

    def _activate(self):
        if self._busy or self.instate(['disabled']):
            return
        self._busy = True
        try:
            if self._callback:
                return self._callback()
        finally:
            try:
                if self.winfo_exists():
                    self._job = self.after_idle(self._unlock)
            except tk.TclError:
                self._busy = False

    def _unlock(self):
        self._job = None
        self._busy = False

    def _destroy(self, event):
        if event.widget == self and self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None


class Switch(tk.Canvas):
    def __init__(self, parent, variable, command=None, text='', **kwargs):
        self.variable, self.command, self.text = variable, command, text
        self.disabled = False
        self.focused = False
        self._pressed = False
        self._trace = None
        super().__init__(parent, width=kwargs.pop('width', 320), height=round(34*ui_scale(parent)), bg=parent.cget('background'),
                         highlightthickness=0, takefocus=True, cursor='hand2', **kwargs)
        self._trace = variable.trace_add('write', lambda *_: self.draw())
        for event in ('<ButtonRelease-1>', '<space>', '<Return>'):
            self.bind(event, self.activate)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<FocusIn>', lambda _: self._focus(True))
        self.bind('<FocusOut>', lambda _: self._focus(False))
        self.bind('<Destroy>', self._destroy, add='+')
        self.bind('<Configure>', lambda _: self.draw())
        self.draw()

    def _focus(self, value):
        self.focused = value
        self.draw()

    def activate(self, event=None):
        if self.disabled:
            return 'break'
        if event is not None and event.type == tk.EventType.ButtonRelease:
            armed, self._pressed = self._pressed, False
            if not armed or not (0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()):
                return 'break'
        self.focus_set()
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return 'break'

    def _press(self, event):
        self._pressed = not self.disabled
        if self._pressed:
            self.focus_set()

    def draw(self):
        if not self.winfo_exists():
            return
        self.delete('all')
        on = bool(self.variable.get())
        fill = ACCENT if on and not self.disabled else RAISED
        s = ui_scale(self)
        self.create_oval(3*s, 9*s, 19*s, 25*s, fill=fill, outline=fill)
        self.create_rectangle(11*s, 9*s, 26*s, 25*s, fill=fill, outline=fill)
        self.create_oval(18*s, 9*s, 34*s, 25*s, fill=fill, outline=fill)
        x = 20 if on else 5
        self.create_oval(x*s, 11*s, (x+12)*s, 23*s, fill=ACCENT_INK if on else MUTED, outline='')
        self.create_text(45*s, 17*s, text=self.text, font=font(self, 12), anchor='w',
                         fill=QUIET if self.disabled else INK)
        if self.focused:
            self.create_rectangle(1, 2, max(40, self.winfo_width()-2), round(32*s),
                                  outline=FOCUS, width=2)

    def _destroy(self, event):
        if event.widget == self and self._trace:
            self.variable.trace_remove('write', self._trace)
            self._trace = None


class ScrollFrame(tk.Frame):
    def __init__(self, parent, background=BG):
        super().__init__(parent, bg=background)
        install_styles(parent)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0,
                                bd=0, yscrollincrement=24)
        self.bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                 style=PREFIX+'Vertical.TScrollbar')
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = tk.Frame(self.canvas, bg=background)
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._content)
        self.canvas.bind('<Configure>', self._width)
        self._top = self.winfo_toplevel()
        self._bindings = [(event, self._top.bind(event, self._wheel, add='+'))
                          for event in ('<MouseWheel>', '<Button-4>', '<Button-5>')]
        self._bindings.append(('<FocusIn>', self._top.bind('<FocusIn>', self._reveal_focus, add='+')))
        self.bind('<Destroy>', self._destroy, add='+')

    def _content(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _width(self, event):
        self.canvas.itemconfigure(self.item, width=event.width)

    def _wheel(self, event):
        target = event.widget
        if not self.winfo_ismapped() or target.winfo_class() in ('Text', 'Listbox', 'Treeview', 'TCombobox'):
            return
        belongs = False
        while target is not None:
            if target == self.body or target == self.canvas:
                belongs = True
                break
            target = getattr(target, 'master', None)
        if not belongs:
            return
        direction = -1 if getattr(event, 'num', 0) == 4 else 1
        if getattr(event, 'delta', 0):
            direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction*2, 'units')
        return 'break'

    def _destroy(self, event):
        if event.widget == self:
            for sequence, identifier in self._bindings:
                try:
                    self._top.unbind(sequence, identifier)
                except tk.TclError:
                    pass

    def _reveal_focus(self, event):
        target = event.widget
        ancestor = target
        while ancestor is not None and ancestor != self.body:
            ancestor = getattr(ancestor, 'master', None)
        if ancestor != self.body or not self.winfo_ismapped():
            return
        bounds = self.canvas.bbox('all')
        if not bounds or bounds[3] <= self.canvas.winfo_height():
            return
        top = target.winfo_rooty()-self.body.winfo_rooty()
        bottom = top+target.winfo_height()
        visible, height = self.canvas.canvasy(0), self.canvas.winfo_height()
        if top < visible:
            self.canvas.yview_moveto(max(0, top-10)/bounds[3])
        elif bottom > visible+height:
            offset = top-10 if target.winfo_height() >= height else bottom-height+10
            self.canvas.yview_moveto(max(0, offset)/bounds[3])


class ActionBar(tk.Frame):
    """Wrap native buttons at actual requested widths rather than crop them."""
    def __init__(self, parent, background=None):
        super().__init__(parent, bg=background or parent.cget('background'))
        self.buttons = []
        self.bind('<Configure>', self._layout)

    def add(self, text, command, primary=False):
        button = Button(self, text=text, command=command, primary=primary)
        self.buttons.append(button)
        self._layout()
        return button

    def _layout(self, event=None):
        width = event.width if event else max(300, self.winfo_width())
        used, row, column = 0, 0, 0
        for button in self.buttons:
            desired = button.winfo_reqwidth()+8
            if used and used+desired > width:
                row, column, used = row+1, 0, 0
            button.grid(row=row, column=column, padx=(0, 8), pady=(3, 3), sticky='w')
            used, column = used+desired, column+1


def panel(parent, title, subtitle=''):
    outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    outer.pack(fill='x', pady=(0, 14))
    head = tk.Frame(outer, bg=PANEL)
    head.pack(fill='x', padx=18, pady=(14, 8))
    label(head, title, 14, GOLD).pack(anchor='w')
    if subtitle:
        label(head, subtitle, 11, MUTED, wraplength=830).pack(anchor='w', pady=(4, 0))
    body = tk.Frame(outer, bg=PANEL)
    body.pack(fill='both', expand=True, padx=18, pady=(0, 15))
    return body


def skin_widget(widget):
    """Only called on descendants of our candidate windows."""
    try:
        if isinstance(widget, ttk.Combobox):
            widget.configure(style=PREFIX+'TCombobox', font=font(widget))
        elif isinstance(widget, ttk.Entry):
            widget.configure(style=PREFIX+'TEntry', font=font(widget))
        elif isinstance(widget, ttk.LabelFrame):
            widget.configure(style=PREFIX+'TLabelframe')
        elif isinstance(widget, ttk.Frame):
            widget.configure(style=PREFIX+'Panel.TFrame')
        elif isinstance(widget, ttk.Label):
            widget.configure(style=PREFIX+'Panel.TLabel', font=font(widget))
        elif isinstance(widget, ttk.Checkbutton):
            widget.configure(style=PREFIX+'TCheckbutton')
        elif isinstance(widget, ttk.Scrollbar):
            widget.configure(style=PREFIX+'Vertical.TScrollbar')
        elif isinstance(widget, tk.Frame):
            widget.configure(bg=PANEL)
        elif isinstance(widget, tk.Canvas):
            widget.configure(bg=PANEL, highlightthickness=0)
        elif isinstance(widget, tk.Scrollbar):
            widget.configure(bg=BORDER, activebackground=HOVER, troughcolor=BG, relief='flat', bd=0)
        elif isinstance(widget, tk.Text):
            widget.configure(bg=RAISED, fg=INK, insertbackground=INK,
                             selectbackground=ACCENT, selectforeground=ACCENT_INK,
                             font=font(widget), padx=12, pady=10, relief='flat',
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=FOCUS)
        elif isinstance(widget, tk.Listbox):
            widget.configure(bg=RAISED, fg=INK, selectbackground=ACCENT,
                             selectforeground=ACCENT_INK, font=font(widget),
                             activestyle='none', relief='flat', exportselection=False,
                             highlightbackground=BORDER, highlightcolor=FOCUS)
    except tk.TclError:
        pass


def skin_tree(widget):
    skin_widget(widget)
    for child in widget.winfo_children():
        skin_tree(child)


def configure_window(window, title, width, height, minimum=(420, 320)):
    install_styles(window)
    window.title(title)
    icon = Path(__file__).parent/'assets/icons/hebao.ico'
    if os.name == 'nt' and icon.is_file():
        try:window.iconbitmap(str(icon))
        except tk.TclError:pass
    window.configure(bg=BG)
    scale = ui_scale(window)
    width, height = round(width*scale), round(height*scale)
    minimum = tuple(round(value*scale) for value in minimum)
    sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
    width, height = min(width, sw-40), min(height, sh-60)
    window.geometry(f'{width}x{height}+{max(0,(sw-width)//2)}+{max(0,(sh-height)//2)}')
    window.minsize(min(minimum[0], width), min(minimum[1], height))


def header(parent, title, subtitle=''):
    top = tk.Frame(parent, bg=BG)
    top.pack(fill='x', padx=22, pady=(18, 12))
    label(top, '✦  '+title, 20, INK).pack(anchor='w')
    if subtitle:
        label(top, subtitle, 12, MUTED, wraplength=900).pack(anchor='w', pady=(5, 0))
    return top


def clamp_popup(x, y, width, height, work):
    left, top, right, bottom = work
    width, height = min(width, right-left), min(height, bottom-top)
    return (max(left, min(x-width, right-width)),
            max(top, min(y-height-8, bottom-height)), width, height)


def absolute_position(window, x, y, width, height):
    window.geometry(f'{width}x{height}{x:+d}{y:+d}')
    if os.name == 'nt':
        # Tk interprets negative geometry offsets relative to a screen edge;
        # place the owning HWND with absolute virtual-screen coordinates.
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        window.update_idletasks()
        handle = user.GetAncestor(window.winfo_id(), 2)
        if handle:
            user.SetWindowPos(handle, None, x, y, width, height, 0x0014)


def portrait(widget, pixels=54):
    source = Path(__file__).parent/'assets/pixel/hebao/idle/frame_00.png'
    with Image.open(source) as image:
        return ImageTk.PhotoImage(image.convert('RGBA').resize((pixels, pixels),
                                  Image.Resampling.NEAREST), master=widget)
