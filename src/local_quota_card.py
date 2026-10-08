"""Multi-source summary; all callbacks belong to the existing Tk host."""
from __future__ import annotations
from dataclasses import dataclass
import tkinter as tk
from datetime import datetime
from hecate_ui import (BG, PANEL, INK, MUTED, GOLD, BORDER, ERROR, Button, Switch,
                       ScrollFrame, configure_window, header, font, label)
from hebao_quota.local_snapshot import LocalHistory, history_view

NAVY = BG


@dataclass(frozen=True)
class OverviewState:
    deepseek_snapshot: object = None
    deepseek_enabled: bool = False
    deepseek_error: str = ""
    local_enabled: bool = True
    local_history: LocalHistory | None = None
    local_busy: bool = False
    local_error: str = ""
    local_read: bool = False


def overview_view(state, previous=None):
    ds = state.deepseek_snapshot
    balance = next((b for b in ds.balances if b.currency == 'CNY'),
                   next(iter(ds.balances), None)) if ds else None
    history = state.local_history if state.local_enabled else None
    if history is None and state.local_enabled and (state.local_busy or state.local_error):
        history = previous
    view = history_view(history)
    local_status = ('读取失败 · 上次历史' if history else '读取失败') if state.local_error else (
        '读取中 · 上次历史' if history else '读取中') if state.local_busy else (
        view['status'] if state.local_enabled else '已停用 · 本次历史已清空')
    values = dict(
        deepseek_value=f'{balance.currency} {balance.total}' if balance else '尚无余额',
        deepseek_source='DeepSeek 官方余额接口',
        deepseek_status=('读取失败 · 旧余额' if ds else '读取失败') if state.deepseek_error else
                        '读取已启用' if state.deepseek_enabled else '读取已停用 · 旧余额' if ds else '读取已停用',
        deepseek_updated='更新：'+datetime.fromtimestamp(ds.observed_at).strftime('%m-%d %H:%M') if ds else '上次更新：尚无',
        deepseek_row1=f'充值 {balance.topped_up}  ·  赠金 {balance.granted}' if balance else '配置密钥后可读取余额',
        deepseek_row2=state.deepseek_error or '不同币种分别展示；详情沿用原刷新设置。',
        codex_value='当前额度：未知', codex_source=view['source'],
        codex_status='当前账号未确认 · '+local_status,
        codex_updated='记录时间：'+view['updated']+(' · 非实时' if history else ''),
        codex_row1='  /  '.join(a+'：'+b for a,b in view['rows']) if view['rows'] else '没有可用历史快照',
        codex_row2=state.local_error or ('正在读取本地历史，不查询账号。' if state.local_busy else
                    '本地读取已停用；本次历史已清空。' if not state.local_enabled else
                    '历史仅作参考，不能确认当前账号或实时额度。'))
    return values


class QuotaOverview(tk.Toplevel):
    def __init__(self, parent, *, on_deepseek, on_read, on_toggle, on_close):
        super().__init__(parent)
        configure_window(self, '赫宝 · 额度总览', 740, 550, (580, 380))
        self.attributes('-topmost', True)
        self.protocol('WM_DELETE_WINDOW', on_close)
        self.bind('<Escape>', lambda _: on_close())
        self._on_read, self._on_toggle = on_read, on_toggle
        self._state, self._previous_history = OverviewState(), None
        self._labels, self._cards = {}, []
        header(self, '额度总览', '把余额与历史，分开看清楚。')
        self.area = ScrollFrame(self)
        self.area.pack(fill='both', expand=True, padx=20, pady=(0, 12))
        self.area.body.bind('<Configure>', self._layout, add='+')
        for index, key in enumerate(('deepseek', 'codex')):
            card = tk.Frame(self.area.body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            self._cards.append(card)
            label(card, '◷  DeepSeek' if index == 0 else '▤  Codex', 16, GOLD).pack(anchor='w', padx=17, pady=(15, 9))
            for name, size, color in (('value', 28, INK), ('status', 11, GOLD),
                                      ('row1', 12, INK), ('source', 11, MUTED),
                                      ('updated', 11, MUTED), ('row2', 11, MUTED)):
                widget = self.label(card, '', size, color)
                widget.pack(fill='x', padx=17, pady=(2, 6))
                self._labels[key+'_'+name] = widget
            actions = tk.Frame(card, bg=PANEL)
            actions.pack(fill='x', padx=17, pady=(8, 15))
            if index == 0:
                self.details_button = self.button(actions, '余额设置 / 详情', on_deepseek)
                self.details_button.pack(fill='x')
            else:
                self.read_button = self.button(actions, '读取本地历史', on_read)
                self.read_button.pack(fill='x')
                self._enabled = tk.BooleanVar(self, True)
                self.toggle_button = Switch(actions, self._enabled, command=on_toggle, text='启用本地历史读取')
                self.toggle_button.pack(fill='x', pady=(5, 0))
        label(self, '历史 / 非实时 / 当前未知始终分开；来源与时间可见。', 11, MUTED).pack(anchor='w', padx=22, pady=(0, 13))
        self._columns = None
        self.render(self._state)

    def _layout(self, event):
        columns = 2 if event.width >= 640 else 1
        if columns != self._columns:
            self._columns = columns
            for index, card in enumerate(self._cards):
                card.grid(row=index//columns, column=index%columns, sticky='nsew',
                          padx=(0, 7) if columns == 2 and index == 0 else (7, 0) if columns == 2 else 0,
                          pady=(0, 10))
            for column in (0, 1):
                self.area.body.columnconfigure(column, weight=1 if column < columns else 0,
                                               uniform='cards' if columns == 2 else '')
        width = max(190, event.width//columns-52)
        for widget in self._labels.values():
            widget.configure(wraplength=width)

    def label(self, parent, text, size, color):
        return label(parent, text, size, color, wraplength=280)

    def button(self, parent, text, callback, secondary=False):
        return Button(parent, text=text, command=callback, primary=not secondary)

    def render(self, state: OverviewState):
        self._state = state
        if not state.local_enabled:
            self._previous_history = None
        elif state.local_history is not None:
            self._previous_history = state.local_history
        values = overview_view(state, self._previous_history)
        for name, value in values.items():
            self._labels[name].configure(text=value)
        self._labels['deepseek_row2'].configure(fg=ERROR if state.deepseek_error else MUTED)
        self._labels['codex_row2'].configure(fg=ERROR if state.local_error else MUTED)
        self.read_button.configure(state='normal' if state.local_enabled and not state.local_busy else 'disabled',
                                   text='读取中…' if state.local_busy else '读取本地历史')
        self._enabled.set(state.local_enabled)
