"""Official, read-only sources. No browser cookies or private dashboard APIs."""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Callable, Sequence

from .models import Balance, QuotaError, QuotaWindow, Snapshot


DEEPSEEK_URL = "https://api.deepseek.com/user/balance"


def _amount(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise QuotaError("余额数据格式异常") from exc
    if not result.is_finite() or result < 0:
        raise QuotaError("余额数据格式异常")
    return result


class DeepSeekProvider:
    id = "deepseek"

    def __init__(self, key_getter: Callable[[], str | None], *, timeout: float = 8.0,
                 opener: Callable[..., object] = urllib.request.urlopen):
        self.key_getter = key_getter
        self.timeout = timeout
        self.opener = opener

    def available(self, context=None) -> bool:
        return bool((self.key_getter() or "").strip())

    def close(self):
        pass  # no persistent connection or timer

    def fetch(self, cancel: threading.Event | None = None) -> Snapshot:
        key = (self.key_getter() or "").strip()
        if not key:
            raise QuotaError("未配置 DeepSeek API key")
        if cancel is not None and cancel.is_set():
            raise QuotaError("已取消")
        # A key fingerprint scopes cache and notifications; never log or display the key.
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        request = urllib.request.Request(DEEPSEEK_URL, headers={
            "Authorization": f"Bearer {key}", "Accept": "application/json",
            "User-Agent": "HecateQuota/0.2",
        })
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(65537)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise QuotaError("DeepSeek 凭据无效或无权限", "auth_error") from None
            raise QuotaError(f"DeepSeek 请求失败（HTTP {exc.code}）") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise QuotaError("DeepSeek 网络连接失败") from None
        if len(raw) > 65536:
            raise QuotaError("DeepSeek 响应过大")
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data["is_available"], bool):
                raise ValueError("bad response")
            rows = data["balance_infos"]
            if not isinstance(rows, list) or not rows:
                raise ValueError("missing balances")
            balances = tuple(Balance(
                currency=str(row["currency"]), total=_amount(row["total_balance"]),
                topped_up=_amount(row["topped_up_balance"]),
                granted=_amount(row["granted_balance"]),
            ) for row in rows)
        except (KeyError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise QuotaError("DeepSeek 响应格式异常") from exc
        if cancel is not None and cancel.is_set():
            raise QuotaError("已取消")
        return Snapshot("deepseek", f"key:{fingerprint}", f"DeepSeek 密钥 {fingerprint[-4:]}",
                        time.time(), balances=balances, available=data["is_available"],
                        source_label="DeepSeek 官方余额接口")


class CodexProvider:
    id = "codex"

    def __init__(self, executable: str | Sequence[str] = "codex", *, timeout: float = 12.0,
                 codex_home: str | None = None):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.executable = executable
        self.timeout = timeout
        self.codex_home = codex_home  # optional existing, explicitly chosen profile
        self._processes: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    def available(self, context=None) -> bool:
        command = self.executable if isinstance(self.executable, str) else self.executable[0]
        return bool(shutil.which(command))

    def close(self):
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

    def fetch(self, cancel: threading.Event | None = None) -> Snapshot:
        cancel = cancel or threading.Event()
        if cancel.is_set():
            raise QuotaError("已取消")
        env = os.environ.copy()
        if self.codex_home:
            env["CODEX_HOME"] = self.codex_home
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            command = [self.executable] if isinstance(self.executable, str) else list(self.executable)
            proc = subprocess.Popen([*command, "app-server", "--listen", "stdio://"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1, env=env, creationflags=flags)
        except (OSError, ValueError):
            raise QuotaError("未找到可运行的 Codex") from None
        with self._lock:
            self._processes.add(proc)
        incoming: queue.Queue[dict | None] = queue.Queue()

        def read_lines():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    try:
                        msg = json.loads(line)
                        if isinstance(msg, dict):
                            incoming.put(msg)
                    except json.JSONDecodeError:
                        continue
            finally:
                incoming.put(None)

        reader = threading.Thread(target=read_lines, name="hebao-codex-rpc", daemon=True)
        reader.start()
        deadline = time.monotonic() + self.timeout

        def send(message: dict):
            if cancel.is_set():
                raise QuotaError("已取消")
            try:
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                raise QuotaError("Codex 服务未能启动") from None

        def receive(msg_id: int) -> dict:
            while True:
                if cancel.is_set():
                    raise QuotaError("已取消")
                left = deadline - time.monotonic()
                if left <= 0:
                    raise QuotaError("Codex 读取超时")
                try:
                    message = incoming.get(timeout=min(left, 0.1))
                except queue.Empty:
                    continue
                if message is None:
                    raise QuotaError("Codex 服务已退出")
                if message.get("id") != msg_id:
                    continue  # unrelated notification
                if "error" in message:
                    raise QuotaError("Codex 拒绝额度读取；请检查登录状态或版本")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise QuotaError("Codex 响应格式异常")
                return result

        try:
            send({"method": "initialize", "id": 1, "params": {
                "clientInfo": {"name": "hecate_quota", "title": "GERNZE quota card", "version": "0.2.0"}}})
            receive(1)
            send({"method": "initialized", "params": {}})
            send({"method": "account/read", "id": 2, "params": {"refreshToken": False}})
            account = receive(2).get("account")
            if not isinstance(account, dict) or account.get("type") != "chatgpt":
                raise QuotaError("Codex 尚未以 ChatGPT 账号登录", "auth_error")
            email = account.get("email")
            if not isinstance(email, str) or not email.strip():
                # Don't merge unidentified accounts into a shared cached bucket.
                raise QuotaError("Codex 未返回账号标识，无法安全区分账号")
            identity = email.strip().casefold()
            send({"method": "account/rateLimits/read", "id": 3})
            payload = receive(3)
            windows = parse_codex_windows(payload)
            if not windows:
                raise QuotaError("Codex 未返回可识别的额度窗口")
            return Snapshot("codex", identity, email.strip(), time.time(), windows=windows,
                            source_label="Codex App Server")
        finally:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    if proc.poll() is None:
                        try:
                            proc.kill()
                            proc.wait(timeout=1.0)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
            reader.join(timeout=0.5)
            if proc.stdout:
                try:
                    proc.stdout.close()
                except OSError:
                    pass
            with self._lock:
                self._processes.discard(proc)


def parse_codex_windows(payload: dict) -> tuple[QuotaWindow, ...]:
    groups = payload.get("rateLimitsByLimitId")
    if not isinstance(groups, dict) or not groups:
        single = payload.get("rateLimits")
        groups = {str(single.get("limitId") or "codex"): single} if isinstance(single, dict) else {}
    windows = []
    for key, group in groups.items():
        if not isinstance(group, dict):
            continue
        limit_id = str(group.get("limitId") or key)
        label = str(group.get("limitName") or limit_id)
        for lane in ("primary", "secondary"):
            row = group.get(lane)
            if not isinstance(row, dict):
                continue
            used = row.get("usedPercent")
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
                continue
            duration = row.get("windowDurationMins")
            reset = row.get("resetsAt")
            windows.append(QuotaWindow(
                limit_id, label, lane, float(used),
                duration if type(duration) is int and duration > 0 else None,
                reset if type(reset) is int and reset > 0 else None))
    return tuple(windows)
