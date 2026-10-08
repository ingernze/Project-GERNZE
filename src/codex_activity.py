"""Manually launched metadata viewer; owns only its own child process."""
import os
import subprocess
from pathlib import Path
import win32gui
import win32process
import win32con


class CodexActivityWindow:
    def __init__(self, root, log, *, sessions=None, launcher=None, native=None):
        self.exe = Path(root) / 'assets/codex_monitor/QuietCodexMonitor.exe'
        self.sessions = Path(sessions) if sessions is not None else Path.home() / '.codex/sessions'
        self.log = log
        self.launcher = launcher or subprocess.Popen
        self.gui, self.api, self.con = native or (win32gui, win32process, win32con)
        self.process = None

    def windows(self):
        proc = self.process
        if proc is None or proc.poll() is not None:
            return []
        found = []
        def visit(hwnd, _):
            try:
                if (self.api.GetWindowThreadProcessId(hwnd)[1] == proc.pid
                        and self.gui.IsWindowVisible(hwnd)
                        and self.gui.GetClassName(hwnd).startswith('WindowsForms')):
                    found.append(hwnd)
            except Exception:
                pass
        self.gui.EnumWindows(visit, None)
        return found

    def open(self):
        if self.process is not None and self.process.poll() is None:
            for hwnd in self.windows():
                self.gui.ShowWindow(hwnd, self.con.SW_RESTORE)
                try: self.gui.SetForegroundWindow(hwnd)
                except Exception: pass
            return self.process
        if not self.exe.is_file():
            raise FileNotFoundError('Codex 活动观察组件未找到，请重新打包。')
        self.process = self.launcher([str(self.exe), str(self.sessions), str(os.getpid())],
            shell=False, cwd=str(self.exe.parent))
        self.log('codex_activity_opened', metadata_only=True)
        return self.process

    def hide(self):
        # WinForms stops its watcher on minimize. Restore does not restart it.
        for hwnd in self.windows():
            self.gui.ShowWindow(hwnd, self.con.SW_MINIMIZE)

    def close(self):
        proc = self.process
        if proc is None or proc.poll() is not None:
            self.process = None
            return
        for hwnd in self.windows():
            try:
                self.gui.SendMessageTimeout(hwnd, self.con.WM_CLOSE, 0, 0,
                    self.con.SMTO_ABORTIFHUNG, 250)
            except Exception: pass
        try: proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            # Only this owned viewer, e.g. its folder dialog is still open.
            proc.terminate()
            try: proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired: pass
        self.process = None
