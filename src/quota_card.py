"""A / 星夜书房 DeepSeek details. Requests and credentials belong to the host."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox

from usage_monitor.models import Snapshot
from ui_theme import (BG, PANEL, RAISED, INK, MUTED, GOLD, BORDER, FOCUS, ERROR,
                       GOOD, Button, Switch, ScrollFrame, font, label, header, configure_window)


NAVY = BG


@dataclass(frozen=True)
class CardState:
    key_present: bool = False
    credential_error: bool = False
    enabled: bool = False
    visible: bool = True
    busy: bool = False
    snapshot: Snapshot | None = None
    error: str = ""
    notice: str = ""
    cooldown_remaining: float = 0
    next_refresh_remaining: float | None = None
    demo: bool = False


def _number(value: Decimal) -> str:
    # Decimal stays exact; do not sum balances in different currencies.
    return format(value, "f")


def present(state: CardState, *, wall_time: float | None = None) -> dict:
    """Derive one coherent display state; used by the app and offline checks."""
    from time import time
    now = time() if wall_time is None else wall_time
    snapshot = state.snapshot
    rows = tuple((b.currency, _number(b.total), _number(b.topped_up),
                  _number(b.granted)) for b in snapshot.balances) if snapshot else ()
    first = next((r for r in rows if r[0] == "CNY"), rows[0] if rows else None)
    if state.credential_error:
        short, detail = "密钥读取失败", "请检查 Windows 凭据管理器"
    elif state.busy:
        short, detail = "读取中…", "正在连接 DeepSeek 官方余额接口"
    elif state.error:
        short, detail = "本次读取失败", state.error[:80]
    elif not state.key_present:
        short, detail = "未保存密钥", "打开“管理密钥”并在本机保存"
    elif not state.enabled:
        short, detail = "读取已停用", "密钥仍保存在本机"
    elif not state.visible:
        short, detail = "已暂停", "重新显示面板后恢复读取"
    elif snapshot and snapshot.available is False:
        short, detail = "当前不可用", "官方接口返回账户不可用"
    elif snapshot:
        short, detail = "最近成功结果", "来自 DeepSeek 官方余额接口"
    else:
        short, detail = "等待读取", "开启后将自动更新"
    if state.demo:
        short, detail = "模拟余额 · 非真实账户", "离线演示数据；不会读取密钥或联网"
    if snapshot and (state.error or state.busy or not state.enabled or not state.visible):
        short += " · 旧余额"
    updated = ("更新：" + datetime.fromtimestamp(snapshot.observed_at).strftime("%m-%d %H:%M")
               if snapshot else "上次更新：尚无")
    if state.busy:
        refresh = "读取中…"
    elif state.cooldown_remaining > 0:
        refresh = "冷却至 " + datetime.fromtimestamp(now + state.cooldown_remaining).strftime("%H:%M")
    else:
        refresh = "刷新余额"
    refresh_allowed = (state.enabled and state.visible and state.key_present
                       and not state.credential_error and not state.busy
                       and state.cooldown_remaining <= 0)
    schedule = "显示且启用时每 15 分钟自动刷新 · 手动冷却 5 分钟"
    if state.enabled and state.visible and state.next_refresh_remaining is not None:
        schedule = ("下次自动刷新：" + datetime.fromtimestamp(now + state.next_refresh_remaining)
                    .strftime("%H:%M") + " · 手动冷却 5 分钟")
    return dict(rows=rows, main=first, short=short, detail=detail, updated=updated,
                refresh=refresh, refresh_allowed=refresh_allowed,
                switch=state.enabled, schedule=schedule,
                key="离线预览 · 不读密钥" if state.demo else
                "密钥读取失败" if state.credential_error else
                "密钥已保存" if state.key_present else "密钥未保存")


class QuotaCard(tk.Toplevel):
    """State-only DeepSeek detail; the original host owns requests and keys."""
    def __init__(self, parent, *, on_save, on_delete, on_toggle, on_refresh, on_close):
        super().__init__(parent)
        configure_window(self, '莉宝 · DeepSeek 余额与设置', 580, 565)
        self.attributes('-topmost', True)
        self._on_save, self._on_delete = on_save, on_delete
        self._on_toggle, self._on_refresh, self._on_close = on_toggle, on_refresh, on_close
        self._state, self._key_dialog = CardState(), None
        self._balance_dialog = None
        self.protocol('WM_DELETE_WINDOW', on_close)
        self.bind('<Escape>', lambda _: self._on_close())
        self.bind('<F5>', lambda _: self._refresh())
        self.bind('<Control-k>', lambda _: self.open_key_manager())
        self.bind('<Unmap>', self._hidden, add='+')
        header(self, 'DeepSeek', '官方余额与本机设置')
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill='both', expand=True, padx=22, pady=(0, 17))
        body = tk.Frame(self.scroll.body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        body.pack(fill='both', expand=True)
        self.value = label(body, '—', 40, INK)
        self.value.configure(font=font(self, 40, serif=True))
        self.value.pack(anchor='w', padx=22, pady=(18, 4))
        self.status = label(body, '', 12, GOLD, wraplength=460)
        self.status.pack(fill='x', padx=22, pady=(0, 8))
        self.updated = label(body, '', 11, MUTED)
        self.updated.pack(anchor='w', padx=22, pady=(0, 12))
        self.detail = label(body, '', 12, MUTED, wraplength=465)
        self.detail.pack(fill='x', padx=22, pady=(0, 12))
        self.details_button = Button(body, text='按币种查看余额明细', command=self.show_balance_details)
        self.details_button.pack(fill='x', padx=22, pady=(0, 15))
        self.refresh_button = Button(body, text='刷新余额', command=self._refresh, primary=True)
        self.refresh_button.pack(fill='x', padx=22, pady=(0, 8))
        self._enabled = tk.BooleanVar(self)
        self.toggle_button = Switch(body, self._enabled, command=self._on_toggle, text='自动刷新')
        self.toggle_button.pack(fill='x', padx=22, pady=(0, 9))
        self.key_button = Button(body, text='管理密钥', command=self.open_key_manager)
        self.key_button.pack(fill='x', padx=22, pady=(0, 12))
        self.key_status = label(body, '', 11, MUTED, wraplength=465)
        self.key_status.pack(fill='x', padx=22, pady=(0, 8))
        self.schedule = label(body, '', 11, MUTED, wraplength=465)
        self.schedule.pack(fill='x', padx=22, pady=(0, 17))
        self.bind('<Configure>', self._wrap, add='+')
        self.render(self._state)

    def _wrap(self, event):
        if event.widget == self:
            for widget in (self.status, self.detail, self.key_status, self.schedule):
                widget.configure(wraplength=max(280, event.width-96))

    def _refresh(self):
        if present(self._state)['refresh_allowed']:
            self._on_refresh()

    def render(self, state: CardState):
        self._state = state
        value = present(state)
        self.value.configure(text=(value['main'][0]+' '+value['main'][1]) if value['main'] else '—')
        # present() remains compatible. Show full long errors in a wrapping field.
        self.status.configure(text=('离线示例 · '+present(replace(state, demo=False))['short']) if state.demo else value['short'])
        self.updated.configure(text=value['updated'])
        self.detail.configure(text=state.error or state.notice or value['detail'],
                              fg=ERROR if state.error or state.credential_error else MUTED)
        self.refresh_button.configure(text=value['refresh'],
                                      state='normal' if value['refresh_allowed'] else 'disabled')
        self.details_button.configure(state='normal' if value['rows'] else 'disabled')
        self._enabled.set(state.enabled)
        self.key_status.configure(text=value['key'])
        self.schedule.configure(text=value['schedule'])

    def show_balance_details(self):
        rows = present(self._state)['rows']
        if not rows:
            return
        if self._balance_dialog is not None and self._balance_dialog.winfo_exists():
            self._balance_dialog.lift()
            return
        dialog = tk.Toplevel(self)
        self._balance_dialog = dialog
        configure_window(dialog, 'DeepSeek · 按币种展示', 540, 330)
        dialog.transient(self)
        header(dialog, '余额明细', '不同币种分别展示，不合并计算。')
        area = ScrollFrame(dialog, background=PANEL)
        area.pack(fill='both', expand=True, padx=22, pady=(0, 14))
        body = area.body
        if self._state.demo:
            label(body, '离线虚构数据 · 非真实账户', 11, GOLD).pack(anchor='w', padx=14, pady=10)
        for currency, total, top, grant in rows:
            label(body, f'{currency}   总余额 {total}\n充值 {top}  ·  赠金 {grant}',
                  13, INK, wraplength=450).pack(anchor='w', padx=14, pady=10)
        Button(dialog, text='关闭', command=dialog.destroy).pack(pady=(0, 14))
        dialog.bind('<Escape>', lambda _: dialog.destroy())

    def _hidden(self, event):
        if event.widget == self:
            self.close_key_manager()
            if self._balance_dialog is not None and self._balance_dialog.winfo_exists():
                self._balance_dialog.destroy()
            self._balance_dialog = None

    def clear_key_input(self):
        if self._key_dialog is not None and self._key_dialog.winfo_exists():
            self._key_dialog._key_var.set('')

    def close_key_manager(self):
        if self._key_dialog is not None and self._key_dialog.winfo_exists():
            self.clear_key_input()
            self._key_dialog.destroy()
        self._key_dialog = None

    def open_key_manager(self):
        if self._key_dialog is not None and self._key_dialog.winfo_exists():
            self._key_dialog.lift()
            return
        dialog = tk.Toplevel(self)
        configure_window(dialog, '管理 DeepSeek API Key', 525, 395)
        dialog.transient(self)
        dialog.attributes('-topmost', True)
        self._key_dialog = dialog
        dialog._key_var = tk.StringVar(dialog)
        header(dialog, '管理密钥', '离线示例 · 假设已有密钥' if self._state.demo else
               '已保存在本机' if self._state.key_present else '尚未保存密钥')
        body = tk.Frame(dialog, bg=PANEL)
        body.pack(fill='both', expand=True, padx=22, pady=(0, 16))
        hint = ('离线预览：只输入示例字符，不读取或保存密钥。' if self._state.demo else
                '请输入 DeepSeek API Key，输入内容始终遮挡。')
        label(body, hint, 12, GOLD, wraplength=435).pack(anchor='w', padx=18, pady=(16, 8))
        entry = tk.Entry(body, textvariable=dialog._key_var, show='●', exportselection=False,
                         font=font(dialog), bg=RAISED, fg=INK, insertbackground=INK,
                         relief='flat', bd=9, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=FOCUS)
        entry.pack(fill='x', padx=18, pady=(0, 12))
        self.key_entry = entry
        response = tk.StringVar(dialog)
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill='x', padx=18)
        def save():
            value = dialog._key_var.get().strip()
            dialog._key_var.set('')
            if not value:
                response.set('先输入一段内容。')
                return
            if self._state.demo:
                response.set('已模拟保存，输入已清空；未写入任何存储。')
                return
            try:
                self._on_save(value)
            except Exception:
                response.set('保存未完成，请检查本机凭据设置。输入已清空。')
                return
            self.close_key_manager()
        def delete():
            dialog._key_var.set('')
            if self._state.demo:
                response.set('离线预览不删除真实凭据。')
                return
            if messagebox.askyesno('确认删除本机密钥',
                    '将停用余额读取并删除本机保存的 API Key。\n仅关闭自动刷新不会删除密钥。确定删除吗？',
                    icon='warning', default='no', parent=dialog):
                try:
                    self._on_delete()
                except Exception:
                    response.set('删除未完成，请检查本机凭据设置。')
                    return
                self.close_key_manager()
        Button(actions, text='保存 / 更换', command=save, primary=True).pack(side='left')
        Button(actions, text='删除本机密钥', command=delete).pack(side='right')
        label(body, '', 11, GOOD, textvariable=response, wraplength=435).pack(fill='x', padx=18, pady=(12, 6))
        label(body, '关闭或取消立即清空输入。', 11, MUTED).pack(anchor='w', padx=18, pady=(0, 12))
        dialog.protocol('WM_DELETE_WINDOW', self.close_key_manager)
        dialog.bind('<Escape>', lambda _: self.close_key_manager())
        dialog.bind('<Return>', lambda _: save())
        entry.focus_set()
