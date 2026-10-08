"""Feature-scoped API settings. Opening/saving never sends a request."""
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlsplit
from hecate_ui import BG, PANEL, INK, MUTED, QUIET, ERROR, GOOD, PREFIX, font, label, header, Button, Switch, ScrollFrame, panel, configure_window


class VoiceAPIWindow(tk.Toplevel):
    def __init__(self, pet):
        config = pet.voice_module.api_config()
        super().__init__(pet.root)
        self.pet = pet
        self.closed = False
        configure_window(self, '赫宝 · 声音专用 API', 670, 620, (540, 400))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda _: self.close())
        header(self, '声音专用 API', '这里的设置只用于声音对话。输入文字直接朗读时不需要它。')
        page = ScrollFrame(self)
        page.pack(fill='both', expand=True, padx=22, pady=(0, 18))
        self.enabled = tk.BooleanVar(self, bool(config['enabled']))
        self.endpoint = tk.StringVar(self, config['endpoint'])
        self.model = tk.StringVar(self, config['model'])
        self.key = tk.StringVar(self, '')
        body = panel(page.body, '连接设置')
        Switch(body, self.enabled, text='启用声音对话 API').pack(fill='x', pady=(0, 10))
        for title, variable, hidden in (
            ('完整接口地址（以 /chat/completions 结尾）', self.endpoint, False),
            ('模型名称', self.model, False),
            ('API 密钥（留空会保留已保存密钥）', self.key, True),
        ):
            label(body, title, 12, MUTED).pack(anchor='w', pady=(0, 5))
            entry = ttk.Entry(body, textvariable=variable, show='●' if hidden else '',
                              style=PREFIX+'TEntry', font=font(self))
            entry.pack(fill='x', pady=(0, 12))
        label(body, '兼容 Chat Completions 的接口。密钥保存在 Windows 凭据管理器。',
              11, QUIET, wraplength=570).pack(fill='x')
        controls = tk.Frame(page.body, bg=BG)
        controls.pack(fill='x', pady=(0, 10))
        self.save_button = Button(controls, text='保存设置', primary=True, command=self.save)
        self.save_button.pack(side='left', padx=(0, 8))
        self.delete_button = Button(controls, text='移除已保存密钥', command=self.delete)
        self.delete_button.pack(side='left')
        self.message = tk.StringVar(self, '保存后，到“文字与 API 说话”选择 API 回复模式。')
        self.message_label = label(page.body, textvariable=self.message, size=12, color=MUTED, wraplength=600)
        self.message_label.pack(fill='x')
        label(page.body, '固定录音使用本地文件，不依赖此接口。', 11, QUIET,
              wraplength=600).pack(fill='x', pady=(12, 0))

    def validate(self):
        endpoint, model = self.endpoint.get().strip(), self.model.get().strip()
        parts = urlsplit(endpoint)
        if endpoint and (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError('请填写完整接口地址，密钥请放在单独的密钥栏。')
        if endpoint and (parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in ('127.0.0.1', 'localhost', '::1'))):
            raise ValueError('远程接口请使用 HTTPS；本机接口可以使用 HTTP。')
        if self.enabled.get() and (not endpoint or not model):
            raise ValueError('启用前，请先填写接口地址和模型名称。')
        return endpoint, model

    def save(self):
        if self.pet.voice_module.busy:
            self.message.set('正在处理语音，请停止或等待结束后再保存。')
            return
        try:
            endpoint, model = self.validate()
            self.pet.voice_module.configure_api(enabled=self.enabled.get(), endpoint=endpoint,
                model=model, key=self.key.get().strip() or None)
        except ValueError as exc:
            self.message.set(str(exc))
            self.message_label.configure(fg=ERROR)
            return
        except Exception:
            self.message.set('设置未完整保存，请检查本地配置或 Windows 凭据管理器后重试。')
            self.message_label.configure(fg=ERROR)
            return
        self.key.set('')
        self.message.set('已保存声音专用设置。尚未发送联网请求。')
        self.message_label.configure(fg=GOOD)

    def delete(self):
        if self.pet.voice_module.busy:
            self.message.set('正在处理语音，请停止或等待结束后再移除密钥。')
            return
        try:
            self.pet.voice_module.delete_api_key()
        except Exception:
            self.message.set('密钥未移除，请检查 Windows 凭据管理器后重试。')
            self.message_label.configure(fg=ERROR)
            return
        self.key.set('')
        self.message.set('已移除声音对话密钥；其他模块的设置保留。')
        self.message_label.configure(fg=GOOD)

    def close(self):
        if self.closed:
            return
        self.key.set('')
        self.closed = True
        self.pet.voice_api_window = None
        self.destroy()


def open_voice_api(pet):
    if pet.closing:
        return
    pet.show()
    existing = getattr(pet, 'voice_api_window', None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return existing
    try:
        window = VoiceAPIWindow(pet)
    except (OSError, ValueError, RuntimeError):
        from tkinter import messagebox
        messagebox.showerror('赫宝 · 声音', '声音设置暂时无法读取，请检查独立语音模块。', parent=pet.root)
        return
    pet.voice_api_window = window
    return window
