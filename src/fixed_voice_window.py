"""Approved recordings with searchable actual trigger descriptions."""
import tkinter as tk
from tkinter import ttk
from hecate_ui import BG, PANEL, RAISED, INK, MUTED, ACCENT, ACCENT_INK, GOLD, QUIET, BORDER, FOCUS, GOOD, PREFIX, font, label, Button, header, configure_window


def open_fixed_voice_window(pet):
    from scene_voice import fixed_voice_rows
    if pet.closing:
        return
    pet.show()
    window = getattr(pet, 'voice_controls', None)
    if window is not None and window.winfo_exists():
        window.deiconify()
        window.lift()
        return window
    window = tk.Toplevel(pet.root)
    pet.voice_controls = window
    configure_window(window, '赫宝 · 固定场景语音', 800, 690, (620, 600))
    header(window, '固定场景语音', '选一句试听，也可以设置每个场景播放哪几句。')
    frame = tk.Frame(window, bg=BG)
    frame.pack(fill='both', expand=True, padx=22, pady=(0, 18))
    rows = sorted(fixed_voice_rows(pet.voice), key=lambda r: r['id'] != 'WB_OPEN_01')
    window.voice_rows = rows
    visible = list(rows)
    toolbar = tk.Frame(frame, bg=BG)
    toolbar.pack(fill='x', pady=(0, 10))
    search = window.search = tk.StringVar(window, '')
    label(toolbar, '搜索', 12, MUTED).pack(side='left', padx=(0, 8))
    entry = ttk.Entry(toolbar, textvariable=search, style=PREFIX+'TEntry', font=font(window), width=24)
    entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
    count = tk.StringVar(window, '')
    label(toolbar, textvariable=count, size=11, color=MUTED).pack(side='right', padx=(8, 0))
    Button(toolbar, text='清空搜索', command=lambda: search.set('')).pack(side='right')
    area = tk.Frame(frame, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    area.pack(fill='both', expand=True)
    box = tk.Listbox(area, width=45, height=8, exportselection=False, activestyle='none',
                     bg=PANEL, fg=INK, selectbackground=ACCENT, selectforeground=ACCENT_INK,
                     font=font(window, 13), relief='flat', bd=0,
                     highlightthickness=1, highlightbackground=BORDER, highlightcolor=FOCUS)
    window.voice_list = box
    scroll = ttk.Scrollbar(area, command=box.yview, style=PREFIX+'Vertical.TScrollbar')
    scroll.pack(side='right', fill='y')
    box.configure(yscrollcommand=scroll.set)
    box.pack(fill='both', expand=True, padx=8, pady=8)
    # Horizontal scroll keeps long original lines accessible without altering them.
    horizontal = tk.Scrollbar(frame, orient='horizontal', command=box.xview,
                              bg=BORDER, troughcolor=BG, relief='flat', bd=0)
    box.configure(xscrollcommand=horizontal.set)
    horizontal.pack(fill='x', pady=(2, 10))
    card = tk.Frame(frame, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill='x', pady=(0, 10))
    label(card, '触发位置与录音', 13, GOLD).pack(anchor='w', padx=14, pady=(10, 5))
    detail = tk.StringVar(window, '选择一条录音查看详情。')
    window.trigger_detail = detail
    label(card, textvariable=detail, size=12, color=INK, wraplength=720).pack(fill='x', padx=14, pady=(0, 12))
    status = tk.StringVar(window, '')
    label(frame, textvariable=status, size=12, color=MUTED, wraplength=720).pack(fill='x', pady=(0, 6))
    controls = tk.Frame(frame, bg=BG)
    controls.pack(fill='x', pady=(0, 8))

    def current():
        picked = box.curselection()
        return visible[picked[0]] if picked else None

    def selected(_event=None):
        row = current()
        window.play_button.configure(state='normal' if row else 'disabled')
        if row:
            availability = ('\n当前第二套美术暂不含看书/睡眠动作，这些台词仍可试听。'
                if getattr(pet,'character_style','original')=='style2' and row['id'].startswith(('READ','SLEEP','WAKE')) else '')
            detail.set(f"台词：{row['text']}\n触发：{row['trigger']}\n录音：{row['model']} · {row['seconds']:.2f} 秒 · {row['state']}" + availability)
        else:
            detail.set('没有匹配的录音，试试其他关键词。')

    def play(_event=None):
        row = current()
        if row:
            okay = pet.voice_module.play_fixed(row['id'])
            status.set('正在试听：'+row['text'] if okay else '当前无法播放：请显示赫宝、取消静音并调高音量。')
        return 'break'

    def stop():
        pet.voice.stop('preview')
        status.set('已停止试听。')

    def toggle():
        pet.toggle_mute()
        window.mute_button.configure(text='取消静音' if pet.muted else '静音')
        status.set('已静音。' if pet.muted else '已取消静音。')

    def open_bindings():
        from voice_bindings_window import open_voice_bindings_window
        return open_voice_bindings_window(pet)
    window.bindings_button=Button(controls,text='触发设置',command=open_bindings)
    window.bindings_button.pack(side='left',padx=(12,0))
    window.play_button = Button(controls, text='试听选中', primary=True, command=play)
    window.play_button.pack(side='left', padx=(0, 8))
    Button(controls, text='停止试听', command=stop).pack(side='left')
    window.mute_button = Button(controls, text='取消静音' if pet.muted else '静音', command=toggle)
    window.mute_button.pack(side='right')
    volume_label = tk.StringVar(window, '')
    label(frame, textvariable=volume_label, size=11, color=QUIET).pack(anchor='w')

    def change_volume(value):
        percent = int(float(value))
        if pet.settings['voice_volume_percent'] != percent:
            pet.set_voice_volume(percent)
        volume_label.set(f'声音大小：{percent}%')

    slider = ttk.Scale(frame, from_=0, to=100, orient='horizontal', command=change_volume,
                       style=PREFIX+'Horizontal.TScale', takefocus=True)
    window.volume_slider = slider
    def step_volume(delta):
        slider.set(max(0,min(100,round(slider.get())+delta)))
        return 'break'
    slider.bind('<Left>',lambda _:step_volume(-1))
    slider.bind('<Right>',lambda _:step_volume(1))
    slider.set(pet.settings['voice_volume_percent'])
    slider.pack(fill='x')
    volume_label.set(f"声音大小：{pet.settings['voice_volume_percent']}%")
    status.set('当前静音，取消静音后才能试听。' if pet.muted else '试听会播放选中录音。')
    def refresh_sound():
        window.mute_button.configure(text='取消静音' if pet.muted else '静音')
        percent = pet.settings['voice_volume_percent']
        if round(slider.get()) != percent:slider.set(percent)
        volume_label.set(f'声音大小：{percent}%')
        status.set('当前静音，取消静音后才能试听。' if pet.muted else '声音设置已更新，可以试听。')
    window.refresh_sound = refresh_sound


    def filter_rows(*_):
        previous = current()
        identity = previous['id'] if previous else None
        query = search.get().strip().casefold()
        visible[:] = [r for r in rows if query in (r['scene']+' '+r['text']+' '+r['trigger']+' '+r['state']).casefold()]
        box.delete(0, 'end')
        for row in visible:
            box.insert('end', f"{row['scene']} · {row['text']}  [{row['state']}]")
        count.set(f'{len(visible)} / {len(rows)} 句')
        if visible:
            index = next((i for i, r in enumerate(visible) if r['id'] == identity), 0)
            box.selection_set(index)
            box.activate(index)
            box.see(index)
        selected()

    def refresh_bindings():
        rows[:]=sorted(fixed_voice_rows(pet.voice),key=lambda r:r['id']!='WB_OPEN_01')
        window.voice_rows=rows
        filter_rows()
    window.refresh_bindings=refresh_bindings
    box.bind('<<ListboxSelect>>', selected)
    box.bind('<Return>', play)
    # Use Enter rather than double-click to avoid accidental repeat playback.
    window.refresh_selection = selected
    trace = search.trace_add('write', filter_rows)
    filter_rows()

    def close():
        search.trace_remove('write', trace)
        pet.voice.stop('preview')
        pet.voice_controls = None
        window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    window.bind('<Escape>', lambda _: close())
    return window
