"""Offline UI preview. Synthetic values only; never reads a key or connects."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import time
import tkinter as tk

from usage_monitor.models import Balance, Snapshot
from quota_card import CardState, QuotaCard


root = tk.Tk()
root.withdraw()
started = time.time()
snapshot = Snapshot("deepseek", "demo", "离线示例", started,
                   balances=(Balance("CNY", Decimal("48.50"), Decimal("40.00"),
                                     Decimal("8.50")),), available=True)
state = CardState(key_present=True, enabled=True, snapshot=snapshot, demo=True)


def redraw(**changes):
    global state
    state = replace(state, **changes)
    card.render(state)


def refresh():
    if state.busy:
        return
    redraw(busy=True, error="", notice="模拟读取中（不联网）")
    root.after(850, lambda: redraw(busy=False, snapshot=replace(snapshot, observed_at=time.time()),
                                  notice="模拟读取完成（不联网）"))


def toggle():
    redraw(enabled=not state.enabled, notice="演示状态已切换（不写入设置）")


card = QuotaCard(root, on_save=lambda _value: None, on_delete=lambda: None,
                 on_toggle=toggle, on_refresh=refresh,
                 on_close=root.destroy)
card.render(state)
root.mainloop()
