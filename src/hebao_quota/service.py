"""Event-driven coordinator. The host calls drain() on its UI thread."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from .models import Alert, QuotaError, Result, Snapshot


@dataclass(frozen=True)
class RefreshState:
    busy: bool
    manual_cooldown_remaining: float
    next_auto_remaining: float | None


class QuotaService:
    """One active source, at most one worker, no timer while hidden or disabled.

    The optional wake_ui callback may be called on a worker thread. In Hecate v03,
    pass a callback that enqueues a command using its existing tray command path;
    never update Tk widgets in wake_ui. Call drain() on the Tk thread.
    """

    def __init__(self, providers: dict, *, wake_ui: Callable[[], None] = lambda: None,
                 interval_s: float = 900.0, manual_cooldown_s: float = 300.0,
                 auto_refresh: dict[str, bool] | None = None,
                 low_balance: dict[str, Decimal] | None = None):
        if interval_s <= 0 or manual_cooldown_s < 0:
            raise ValueError("invalid refresh interval")
        self.providers = dict(providers)
        self.wake_ui = wake_ui
        self.interval_s = interval_s
        self.manual_cooldown_s = manual_cooldown_s
        # Codex reads are manual only by default; unknown providers are manual too.
        self.auto_refresh = {"deepseek": True, "codex": False}
        if auto_refresh is not None:
            if auto_refresh.get("codex"):
                raise ValueError("Codex automatic refresh is disabled in this release")
            self.auto_refresh.update(auto_refresh)
        self.low_balance = low_balance or {"CNY": Decimal("10"), "USD": Decimal("2")}
        self.visible = False
        self.active: str | None = None
        self.enabled = False
        self._lock = threading.RLock()
        self._generation = 0
        self._closed = False
        self._running = False
        self._pending = False
        self._cancel = threading.Event()
        self._timer: threading.Timer | None = None
        self._timer_due: float | None = None
        self._events: queue.Queue[tuple[int, Result]] = queue.Queue()
        self._last_attempt: dict[str, float] = {}
        self._alerted: set[tuple] = set()

    def configure(self, *, enabled: bool, visible: bool, active: str | None):
        if active is not None and active not in self.providers:
            raise KeyError(active)
        with self._lock:
            if self._closed:
                return
            changed = (self.active != active or self.visible != visible or self.enabled != enabled)
            self.enabled, self.visible, self.active = bool(enabled), bool(visible), active
            if changed:
                self._generation += 1
                self._cancel.set()
                self._cancel_timer()
                self._pending = (self._running and self.enabled and self.visible and
                                 self.active is not None and self.auto_refresh.get(self.active, False))
        if changed:
            self._resume_auto()

    def invalidate(self, provider_id: str | None = None):
        """Call immediately when the account changes, even if provider stays the same.

        Host must also clear its visible card before a fresh result arrives.
        """
        with self._lock:
            if self._closed:
                return
            self._generation += 1
            self._cancel.set()
            self._cancel_timer()
            account_provider = provider_id or self.active
            if account_provider is not None:
                # A new key identifies a different account; the previous key's
                # cooldown and displayed result must not delay its first read.
                self._last_attempt.pop(account_provider, None)
            self._pending = (self._running and self.enabled and self.visible and
                             self.active is not None and self.auto_refresh.get(self.active, False))
        self._resume_auto()

    def read_state(self, provider_id: str = "deepseek") -> RefreshState:
        """Read-only timing for UI use. Calling this never starts polling."""
        with self._lock:
            now = time.monotonic()
            last = self._last_attempt.get(provider_id)
            cooldown = max(0.0, self.manual_cooldown_s - (now-last)) if last is not None else 0.0
            next_auto = (max(0.0, self._timer_due-now) if self._timer_due is not None
                         and self.active == provider_id else None)
            return RefreshState(self._running, cooldown, next_auto)

    def _resume_auto(self):
        """Resume after show/key change without losing the next 15-minute timer."""
        with self._lock:
            if (self._closed or not self.enabled or not self.visible or not self.active or
                    not self.auto_refresh.get(self.active, False)):
                return
            if self._running:
                self._pending = True
                return
            due = self._last_attempt.get(self.active, -float("inf")) + self.interval_s
            remaining = due - time.monotonic()
            if remaining > 0:
                self._schedule_timer(remaining)
                return
        self.refresh()

    def refresh(self, *, force: bool = False) -> bool:
        """Manual refresh uses force=True; it still obeys the safety cooldown."""
        with self._lock:
            if self._closed or not self.enabled or not self.visible or not self.active:
                return False
            if not force and not self.auto_refresh.get(self.active, False):
                return False
            if self._running:
                return False
            provider_id = self.active
            now = time.monotonic()
            minimum = self.manual_cooldown_s if force else self.interval_s
            if now - self._last_attempt.get(provider_id, -float("inf")) < minimum:
                return False
            self._last_attempt[provider_id] = now
            self._cancel_timer()
            self._cancel = threading.Event()
            cancel = self._cancel
            generation = self._generation
            self._running = True
        thread = threading.Thread(target=self._fetch, args=(provider_id, generation, cancel),
                                  name="hebao-quota-fetch", daemon=True)
        thread.start()
        try:
            self.wake_ui()  # UI updates only after the host drains on its Tk thread.
        except Exception:
            pass
        return True

    def _fetch(self, provider_id: str, generation: int, cancel: threading.Event):
        try:
            snapshot = self.providers[provider_id].fetch(cancel)
            result = Result(provider_id, snapshot, None)
        except QuotaError as exc:
            result = Result(provider_id, None, str(exc), exc.status)
        except Exception:
            # Never surface exception text; HTTP/URL errors can carry secrets.
            result = Result(provider_id, None, "额度读取失败", "unavailable")
        wake = restart = False
        with self._lock:
            self._running = False
            if not self._closed and generation == self._generation and not cancel.is_set():
                self._events.put((generation, result))
                wake = True
                self._schedule_timer()
            restart = self._pending and not self._closed
            self._pending = False
            wake = wake or restart
        if wake:
            try:
                self.wake_ui()
            except Exception:
                pass
        if restart:
            self._resume_auto()

    def _schedule_timer(self, delay: float | None = None):
        if (self._closed or not self.enabled or not self.visible or not self.active or
                not self.auto_refresh.get(self.active, False)):
            return
        self._cancel_timer()
        delay = self.interval_s if delay is None else max(0.001, delay)
        self._timer_due = time.monotonic() + delay
        self._timer = threading.Timer(delay, self._timer_fire, args=(self._generation,))
        self._timer.daemon = True
        self._timer.start()

    def _timer_fire(self, generation: int):
        with self._lock:
            if generation != self._generation or self._closed:
                return
            self._timer = None
            self._timer_due = None
        self._resume_auto()

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._timer_due = None

    def drain(self) -> tuple[list[Result], list[Alert]]:
        """Call only from the host UI thread. Empty queue needs no polling."""
        results, alerts = [], []
        while True:
            try:
                generation, result = self._events.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                if (generation != self._generation or not self.enabled or
                        not self.visible or self.active != result.provider):
                    continue
                results.append(result)
                if result.snapshot:
                    alerts.extend(self._alerts(result.snapshot))
        return results, alerts

    def _alerts(self, snapshot: Snapshot) -> list[Alert]:
        alerts: list[Alert] = []
        for window in snapshot.windows:
            remaining = window.remaining_percent
            reset = window.resets_at  # alerts repeat only after the source's window resets
            if reset is None:
                continue
            for threshold in (20, 10):
                key = (snapshot.provider, snapshot.account_id, window.limit_id,
                       window.lane, reset, threshold)
                if remaining <= threshold and key not in self._alerted:
                    self._alerted.add(key)
                    alerts.append(Alert(snapshot.provider, snapshot.account_label,
                                        f"{window.label} {window.lane} 剩余约 {remaining:g}%"))
                    break  # one reminder on this reading, not two at once
        for balance in snapshot.balances:
            threshold = self.low_balance.get(balance.currency)
            if threshold is None:
                continue
            key = (snapshot.provider, snapshot.account_id, balance.currency, str(threshold))
            if balance.total <= threshold and key not in self._alerted:
                self._alerted.add(key)
                alerts.append(Alert(snapshot.provider, snapshot.account_label,
                                    f"DeepSeek 余额 {balance.total} {balance.currency}"))
            elif balance.total > threshold:
                self._alerted.discard(key)  # permit a future alert after a top-up and re-depletion
        return alerts

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1
            self._cancel.set()
            self._cancel_timer()
            self._pending = False
        for provider in self.providers.values():
            try:
                provider.close()
            except Exception:
                pass
