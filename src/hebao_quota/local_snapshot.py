"""Bounded, read-only Codex history reader. No authentication or network imports."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import time
from typing import BinaryIO

MAX_FILES = 12
TAIL_BYTES = 2 * 1024 * 1024
MAX_LINE = 256 * 1024
STALE_SECONDS = 15 * 60


@dataclass(frozen=True)
class HistoricalWindow:
    used_percent: float
    minutes: int
    resets_at: int


@dataclass(frozen=True)
class LocalHistory:
    observed_at: float
    windows: tuple[HistoricalWindow, ...]
    scanned_files: int
    # Record metadata cannot establish the application's current login.
    current_account_verified: bool = False


def _shared_open(path: Path) -> BinaryIO:
    if os.name != "nt":
        return path.open("rb")
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(fd, "rb")


def _window(value) -> HistoricalWindow | None:
    if not isinstance(value, dict):
        return None
    used, minutes, reset = (value.get("used_percent"), value.get("window_minutes"),
                            value.get("resets_at"))
    if (isinstance(used, bool) or not isinstance(used, (int, float))
            or not math.isfinite(used) or not 0 <= used <= 100):
        return None
    if (type(minutes) is not int or not 0 < minutes <= 525600
            or type(reset) is not int or not 0 < reset < 253402300800):
        return None
    return HistoricalWindow(float(used), minutes, reset)


def _event(line: bytes, now: float):
    if len(line) > MAX_LINE or b'"rate_limits"' not in line:
        return None
    try:
        event = json.loads(line)
        if not isinstance(event, dict) or event.get("type") != "event_msg":
            return None
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return None
        rate = payload.get("rate_limits")
        if not isinstance(rate, dict) or rate.get("limit_id") != "codex":
            return None
        stamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return None
        observed = stamp.timestamp()
        if not math.isfinite(observed) or observed <= 0 or observed > now + 120:
            return None
        windows = tuple(w for lane in ("primary", "secondary")
                        if (w := _window(rate.get(lane))) is not None)
        return (observed, windows) if windows else None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def read_local_history(root: Path | None = None, *, now: float | None = None,
                       cancel=None) -> LocalHistory | None:
    now = time.time() if now is None else now
    root = (root or Path.home() / ".codex" / "sessions").resolve()
    if not root.is_dir():
        return None
    candidates = []
    entries = 0
    for base, dirs, names in os.walk(root, followlinks=False):
        if cancel is not None and cancel.is_set():
            return None
        relative = Path(base).relative_to(root)
        dirs[:] = [d for d in sorted(dirs, reverse=True)
                   if len(relative.parts) < 3 and not (Path(base) / d).is_symlink()]
        for name in names:
            entries += 1
            if entries > 5000:
                break
            if not name.startswith("rollout-") or not name.endswith(".jsonl"):
                continue
            path = Path(base) / name
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    continue
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        if entries > 5000:
            break
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    best = None
    scanned = 0
    for _, path in candidates[:MAX_FILES]:
        if cancel is not None and cancel.is_set():
            return None
        try:
            with _shared_open(path) as stream:
                stream.seek(0, 2)
                size = stream.tell()
                start = max(0, size - TAIL_BYTES)
                stream.seek(start)
                block = stream.read(TAIL_BYTES)
            if start:
                # The leading record is incomplete when reading a tail.
                block = block.partition(b"\n")[2]
            scanned += 1
            for line in block.splitlines():
                if cancel is not None and cancel.is_set():
                    return None
                parsed = _event(line, now)
                if parsed is not None and (best is None or parsed[0] > best[0]):
                    best = parsed
        except OSError:
            continue
    return LocalHistory(*best, scanned) if best is not None else None


def history_view(history: LocalHistory | None, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    result = {"current": "未知", "account": "当前账号未确认",
              "source": "Codex 本地历史快照", "updated": "尚未读取",
              "rows": (), "status": "没有可用历史快照"}
    if history is None:
        return result
    stamp = datetime.fromtimestamp(history.observed_at).strftime("%m-%d %H:%M:%S")
    expired = all(w.resets_at <= now for w in history.windows)
    old = now - history.observed_at > STALE_SECONDS
    result.update(updated=stamp, status="窗口已过期" if expired else
                  "旧记录 · 非实时" if old else "历史记录 · 非实时")
    rows = []
    for w in history.windows:
        label = "5 小时" if w.minutes == 300 else "7 天" if w.minutes == 10080 else f"{w.minutes} 分钟"
        if w.resets_at <= now:
            value = "已过期"
        else:
            value = f"当时剩余 {100 - w.used_percent:g}%"
        rows.append((label, value))
    result["rows"] = tuple(rows)
    return result

