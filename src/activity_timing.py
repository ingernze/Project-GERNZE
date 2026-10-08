"""Validated preferences and one-shot sleep timers; no polling or model calls."""
import copy
import math
import random
import re
import sys
import threading
import time
from datetime import datetime, timedelta

DEFAULTS = {
    'foot_sway_enabled': True, 'foot_sway_mean_min': 20,
    'foot_sway_min_cycles': 1, 'foot_sway_max_cycles': 3,
    'blink_enabled': True, 'blink_min_s': 3, 'blink_max_s': 5,
    'sleep_enabled': True, 'sleep_window_start': '22:00', 'sleep_window_end': '08:00',
    'sleep_day_mean_min': 120, 'sleep_night_mean_min': 10,
    'sleep_min_s': 30, 'sleep_max_s': 600,
}

def minute_of_day(text):
    if not isinstance(text, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', text):
        raise ValueError('时间请使用00:00到23:59的格式。')
    h, m = map(int, text.split(':'))
    return h * 60 + m

def validate_preferences(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('动作设置字段不完整或包含未知字段。')
    for name in ('blink_enabled', 'sleep_enabled', 'foot_sway_enabled'):
        if type(value[name]) is not bool: raise ValueError('开关必须是开或关。')
    for lo, hi, minimum, maximum, label in (
        ('blink_min_s', 'blink_max_s', 1, 120, '眨眼间隔'),
        ('sleep_min_s', 'sleep_max_s', 1, 3600, '睡眠时长'),
    ):
        if any(type(value[k]) is not int for k in (lo, hi)) or not minimum <= value[lo] <= value[hi] <= maximum:
            raise ValueError(f'{label}请填{minimum}～{maximum}秒，最短不能大于最长。')
    if (any(type(value[k]) is not int for k in ('foot_sway_min_cycles','foot_sway_max_cycles'))
            or not 1 <= value['foot_sway_min_cycles'] <= value['foot_sway_max_cycles'] <= 3):
        raise ValueError('摆腿轮数请填1～3，最少不能大于最多。')
    for name in ('sleep_day_mean_min', 'sleep_night_mean_min', 'foot_sway_mean_min'):
        if type(value[name]) is not int or not 1 <= value[name] <= 1440:
            raise ValueError('平均触发间隔请填1～1440分钟。')
    start = minute_of_day(value['sleep_window_start'])
    end = minute_of_day(value['sleep_window_end'])
    if start == end: raise ValueError('高发时段的开始与结束时间不能相同。')
    return dict(value)

def stored_preferences(value):
    if value is None: return dict(DEFAULTS)
    try: return validate_preferences({**DEFAULTS, **value})
    except (TypeError, ValueError): return dict(DEFAULTS)

def in_sleep_window(now, prefs):
    start, end = (minute_of_day(prefs[k]) for k in ('sleep_window_start', 'sleep_window_end'))
    current = now.hour * 60 + now.minute
    return start <= current < end if start < end else current >= start or current < end

def next_window_boundary(now, prefs):
    candidates = []
    for key in ('sleep_window_start', 'sleep_window_end'):
        minute = minute_of_day(prefs[key])
        point = now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
        if point <= now: point += timedelta(days=1)
        candidates.append(point)
    return min(candidates)

def random_wait_seconds(mean_minutes, rng):
    # A short floor avoids back-to-back sleep announcements. The shifted
    # exponential still has the chosen mean; it is not an exact appointment.
    mean = mean_minutes * 60
    return 30 + rng.expovariate(1 / (mean - 30))

class DesktopSettingsRequest:
    def __init__(self, command, params):
        self.command = command; self.params = copy.deepcopy(params)
        self.done = threading.Event(); self.lock = threading.Lock()
        self.cancelled = False; self.result = None; self.error = None

    def execute(self, pet):
        with self.lock:
            if self.cancelled: return
            try:
                if self.command == 'behavior.get': self.result = pet.activity_settings_snapshot()
                elif self.command == 'behavior.set': self.result = pet.apply_activity_settings(self.params['settings'])
                else: raise ValueError('不允许的动作设置接口。')
            except Exception as exc: self.error = exc
            finally: self.done.set()

    def wait(self, timeout=5):
        if not self.done.wait(timeout):
            with self.lock:
                if not self.done.is_set():
                    self.cancelled = True
                    raise OSError('桌宠暂时没有响应，设置未保存。')
        if self.error is not None: raise self.error
        return self.result

class SleepSchedule:
    def __init__(self, pet, *, clock=time.monotonic, local_now=datetime.now, rng=None):
        self.pet = pet; self.clock = clock; self.local_now = local_now; self.rng = rng or random.Random()
        self.job = None; self.wake_job = None; self.due = None; self.armed = False; self.failed = False
        self.suspended = any('self-test' in x or x == '--benchmark' for x in sys.argv)

    @property
    def prefs(self): return self.pet.settings['activity_timing']

    def resource_available(self):
        return self.pet.manual_action.asset_dir is not None and (self.pet.manual_action.asset_dir / 'sleep' / 'manifest.json').is_file()

    def available(self):
        p = self.pet
        return (not self.suspended and not self.failed and self.prefs['sleep_enabled']
                and not p.closing and p.visible and p.drag_start is None
                and not p.walk_trial.active and not p.manual_action.active and p.reading_index is None
                and not p.coast.motion.frame.active
                and (p.character_style != 'style2' or p.style2_motion == 'rest')
                and self.resource_available())

    def schedule(self):
        if self.job is not None or not self.available(): return
        mono, local = self.clock(), self.local_now()
        high = in_sleep_window(local, self.prefs)
        mean = self.prefs['sleep_night_mean_min' if high else 'sleep_day_mean_min']
        # Never replay missed sleeps when resuming from a hidden/busy state.
        if self.due is None or self.due <= mono: self.due = mono + random_wait_seconds(mean, self.rng)
        until_boundary = (next_window_boundary(local, self.prefs) - local).total_seconds()
        wait = min(self.due - mono, until_boundary)
        expected = mono + wait
        boundary = until_boundary <= self.due - mono
        self.job = self.pet.root.after(max(1, math.ceil(wait * 1000)),
            lambda: self._run(expected, mono, local, high, boundary))

    def _run(self, expected, sampled_mono, sampled_local, high, boundary):
        self.job = None
        now, local = self.clock(), self.local_now()
        clock_drift = abs((local - sampled_local).total_seconds() - (now - sampled_mono))
        if boundary or in_sleep_window(local, self.prefs) != high or now - expected > 60 or clock_drift > 5:
            self.due = None; self.schedule(); return
        if not self.available(): self.due = None; return
        if now + .002 < self.due: self.schedule(); return
        self.due = None
        started = self.pet.start_manual_action('sleep', automatic=True)
        if not started:
            self.failed = True
            self.pet.record_manual_event('scheduled_sleep_unavailable_until_restart')
        else: self.pet.record_manual_event('scheduled_sleep_started', high_window=high)

    def sleep_holding(self):
        action = self.pet.manual_action
        if self.armed or not action.automatic or action.finish_requested: return
        self.armed = True
        ms = self.rng.randint(self.prefs['sleep_min_s'], self.prefs['sleep_max_s']) * 1000
        self.wake_job = self.pet.root.after(ms, self._wake)
        self.pet.record_manual_event('sleep_auto_duration_started', duration_ms=ms)

    def _wake(self):
        self.wake_job = None; action = self.pet.manual_action
        if self.pet.visible and not self.pet.closing and action.active and action.automatic:
            action.wake(automatic=True)

    def cancel_idle(self, *, reset_wait=False):
        if self.job is not None: self.pet.root.after_cancel(self.job)
        self.job = None
        if reset_wait: self.due = None

    def cancel_wake(self):
        if self.wake_job is not None: self.pet.root.after_cancel(self.wake_job)
        self.wake_job = None

    def cancel(self, *, reset_wait=False):
        self.cancel_idle(reset_wait=reset_wait); self.cancel_wake(); self.armed = False

