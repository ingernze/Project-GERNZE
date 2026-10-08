"""Voice home, sharing the established starry-study palette and native controls."""
import tkinter as tk
from hecate_ui import BG, PANEL, MUTED, GOLD, QUIET, BORDER, label, header, Button, ScrollFrame, configure_window


def open_voice_modules(pet):
    if pet.closing:
        return
    pet.show()
    existing = getattr(pet, 'voice_modules_window', None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    window = tk.Toplevel(pet.root)
    pet.voice_modules_window = window
    configure_window(window, '赫宝 · 声音', 680, 540, (540, 360))
    header(window, '声音', '听熟悉的台词，也可以让赫宝说出你写下的话。')
    page = ScrollFrame(window)
    page.pack(fill='both', expand=True, padx=22, pady=(0, 18))
    for number, title, description, action, text, attribute in (
        ('01', '固定场景语音', '查看每句台词在什么地方触发，选中后就能试听。',
         pet.open_voice_controls, '查看台词与触发场景', 'fixed_button'),
        ('02', '文字与 API 说话', '直接朗读文字，或通过声音专用 API 回复；声音仍可分别选择。',
         pet.open_voice_text, '写一句话', 'text_button'),
    ):
        card = tk.Frame(page.body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill='x', pady=(0, 12))
        inner = tk.Frame(card, bg=PANEL)
        inner.pack(fill='both', expand=True, padx=18, pady=16)
        label(inner, number + '  ·  ' + title, 16, GOLD).pack(anchor='w')
        label(inner, description, 12, MUTED, wraplength=560).pack(fill='x', pady=(6, 12))
        button = Button(inner, text=text, command=action, primary=number == '02')
        button.pack(anchor='w')
        setattr(window, attribute, button)
    footer = tk.Frame(page.body, bg=BG)
    footer.pack(fill='x')
    label(footer, '第一套 / 第二套声音 · 当前录音与声音选择均保留', 11, QUIET,
          wraplength=560).pack(fill='x', pady=(0, 8))
    from voice_api_window import open_voice_api
    window.api_button = Button(footer, text='声音专用 API 设置', command=lambda: open_voice_api(pet))
    window.api_button.pack(anchor='w')

    def close():
        pet.voice_modules_window = None
        window.destroy()
    window.protocol('WM_DELETE_WINDOW', close)
    window.bind('<Escape>', lambda _: close())
    window.text_button.focus_set()
    return window
