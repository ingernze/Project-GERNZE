"""One app-owned Chromium window; event-driven reuse, bounded startup only.

The browser uses a separate local profile. We never enumerate tabs or read the
user's browser profile. Ownership follows Chromium's private-profile singleton, including relaunches.
"""
import os
from pathlib import Path
import subprocess
import threading
import tempfile
import time


class WorkbenchWindow:
    def __init__(self, data_dir, logger, *, native=None, launcher=None, browser=None, on_closed=None):
        if native is None:
            import win32gui
            import win32process
            import win32con
            native = (win32gui, win32process, win32con)
        self.gui, self.process_api, self.con = native
        self.launcher = launcher or subprocess.Popen
        self.browser = Path(browser) if browser else self._find_browser()
        self.profile_root = Path(data_dir) / 'workbench_browser_sessions'
        self.profile = None
        self._profile_temp = None
        self.logger = logger
        self.on_closed = on_closed
        self.watchers = []
        self.lock = threading.RLock()
        self.processes = []
        self.worker = None
        self.cancel = threading.Event()
        self.ready = threading.Event()
        self.hwnd = None
        self.url = None
        self.error = None
        self.launch_count = 0
        self.generation = 0
        self.owner_pid = None
        self.owner_cancel_handles = []

    @staticmethod
    def _find_browser():
        roots = (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'),
                 os.environ.get('LOCALAPPDATA'))
        for relative in ('Microsoft/Edge/Application/msedge.exe',
                         'Google/Chrome/Application/chrome.exe'):
            for root in roots:
                candidate = Path(root) / relative if root else None
                if candidate and candidate.is_file():
                    return candidate
        raise RuntimeError('未找到可运行工作台的 Edge 或 Chrome')

    def _profile_owner(self):
        # Chromium itself finds the profile owner through this named message-only
        # window. Exact private path matching avoids the user's normal browser.
        if self.profile is None or not hasattr(self.gui, 'FindWindowEx'):
            return None
        try:
            hwnd = self.gui.FindWindowEx(-3, 0, 'Chrome_MessageWindow', str(self.profile))
            return self.process_api.GetWindowThreadProcessId(hwnd)[1] if hwnd else None
        except Exception:
            return None

    def _windows(self):
        # Retain still-running owners when Chromium forwards a later launch to
        # its existing dedicated profile process. Never match by title alone.
        pids = {p.pid for p in self.processes if p.poll() is None}
        owner = self._profile_owner()
        if owner:
            pids.add(owner)
        found = []
        def collect(hwnd, _):
            try:
                if (self.gui.IsWindowVisible(hwnd)
                        and self.gui.GetClassName(hwnd) == 'Chrome_WidgetWin_1'
                        and self.process_api.GetWindowThreadProcessId(hwnd)[1] in pids):
                    found.append(hwnd)
            except Exception:
                pass  # A window can be destroyed during enumeration.
        self.gui.EnumWindows(collect, None)
        return found

    def _focus(self, hwnd):
        if self.gui.IsIconic(hwnd):
            self.gui.ShowWindow(hwnd, self.con.SW_RESTORE)
        else:
            self.gui.ShowWindow(hwnd, self.con.SW_SHOW)
        try:
            self.gui.SetForegroundWindow(hwnd)
        except Exception:
            # Windows can deny foreground activation after an asynchronous launch;
            # expose the existing window and notify instead of spawning a second.
            self.gui.BringWindowToTop(hwnd)
            self.gui.FlashWindow(hwnd, True)

    def open(self, url):
        with self.lock:
            if self.error:
                error, self.error = self.error, None
                raise RuntimeError(error)
            windows = self._windows()
            if windows and self.url == url:
                self.hwnd = windows[0]
                self._focus(self.hwnd)
                return True
            if self.worker and self.worker.is_alive():
                return True  # A rapid second click shares the pending launch.
            if windows:
                self._close_windows(windows)
            # A different desktop host must never forward to a stale browser
            # that owns an older loopback URL. Same-host repeated opens reuse it.
            if self._profile_temp is None:
                self.profile_root.mkdir(parents=True, exist_ok=True)
                self._profile_temp = tempfile.TemporaryDirectory(
                    prefix='session-', dir=self.profile_root)
                self.profile = Path(self._profile_temp.name)
            self.processes=[p for p in self.processes if p.poll() is None]
            self.watchers=[w for w in self.watchers if w.is_alive()]
            self.generation += 1
            self.cancel = threading.Event()
            self.ready.clear()
            self.hwnd = None
            self.url = url
            process = self.launcher([
                str(self.browser), '--app=' + url,
                '--user-data-dir=' + str(self.profile), '--no-first-run',
                '--no-default-browser-check', '--disable-background-mode',
                '--disable-extensions', '--disable-sync', '--window-size=1200,820',
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.processes.append(process)
            self.launch_count += 1
            self.worker = threading.Thread(target=self._await_window,
                                           args=(self.cancel, self.generation, self.on_closed),
                                           name='hebao-workbench-window-start', daemon=True)
            self.worker.start()
            if self.on_closed:
                watcher = threading.Thread(target=self._watch_exit,
                    args=(process,), name='hebao-workbench-browser-exit', daemon=True)
                self.watchers.append(watcher)
                watcher.start()
            return True

    def _await_window(self, cancel, generation, on_closed):
        # This finite startup wait ends when the window exists. No idle polling.
        deadline = time.monotonic() + 15
        while not cancel.is_set() and time.monotonic() < deadline:
            with self.lock:
                windows = self._windows()
                if windows:
                    self.hwnd = windows[0]
                    self._focus(self.hwnd)
                    self.logger('workbench_window_ready', hwnd=self.hwnd,
                        pid=self.process_api.GetWindowThreadProcessId(self.hwnd)[1], local_only=True)
                    self.owner_pid = self.process_api.GetWindowThreadProcessId(self.hwnd)[1]
                    # The launcher can already have exited. Wait for the actual
                    # profile owner's lifetime instead, with no idle polling.
                    if on_closed and hasattr(self.gui, 'FindWindowEx'):
                        watcher = threading.Thread(target=self._watch_owner,
                            args=(self.owner_pid, generation, cancel, on_closed),
                            name='hebao-workbench-owner-exit', daemon=True)
                        self.watchers.append(watcher); watcher.start()
                    self.ready.set()
                    return
            cancel.wait(.05)
        if not cancel.is_set():
            self.error = '工作台窗口未能启动，请再次打开重试'
            self.logger('workbench_window_start_failed', local_only=True)
        self.ready.set()

    def _watch_exit(self, process, on_closed=None):
        # A Chromium stub may forward or relaunch. Its exit is diagnostic only.
        code = process.wait()
        self.logger('workbench_launcher_exit', pid=process.pid, code=code, local_only=True)

    def _watch_owner(self, pid, generation, cancel, on_closed):
        import win32api, win32event
        handle = None; wake = None
        try:
            wake = win32event.CreateEvent(None, True, False, None)
            with self.lock:
                self.owner_cancel_handles.append(wake)
                if cancel.is_set():win32event.SetEvent(wake)
            handle = win32api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
            outcome = win32event.WaitForMultipleObjects([handle,wake], False, win32event.INFINITE)
            if outcome != win32event.WAIT_OBJECT_0:return
        except Exception:
            # The pagehide route remains the fallback; never interpret denied
            # observation as proof that a live window closed.
            self.logger('workbench_owner_wait_unavailable', local_only=True)
            return
        finally:
            if handle is not None: win32api.CloseHandle(handle)
            if wake is not None:
                with self.lock:
                    self.owner_cancel_handles.remove(wake)
                win32api.CloseHandle(wake)
        with self.lock:
            if generation == self.generation and not cancel.is_set():
                self.logger('workbench_owner_exit', pid=pid, local_only=True)
                on_closed()

    def _close_windows(self, windows):
        for hwnd in windows:
            try:
                self.gui.SendMessageTimeout(hwnd, self.con.WM_CLOSE, 0, 0,
                                            self.con.SMTO_ABORTIFHUNG, 1000)
            except Exception:
                self.logger('workbench_window_close_pending', local_only=True)

    def close(self):
        with self.lock:
            self.cancel.set()
            if self.owner_cancel_handles:
                import win32event
                for wake in self.owner_cancel_handles:win32event.SetEvent(wake)
            self.generation += 1
            closed_callback = self.on_closed
            self._close_windows(self._windows())
            self.hwnd = None
            self.url = None
        if closed_callback:
            closed_callback()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=1)
        # If shutdown races a slow browser startup, there may be no HWND yet.
        # Reclaim only process handles launched with our separate profile.
        for process in self.processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.logger('workbench_browser_exit_pending', local_only=True)
        for watcher in self.watchers:
            if watcher is not threading.current_thread():
                watcher.join(timeout=1)

        # Delete only this generated session directory after all owned browsers
        # have exited. Learning records/settings live outside this scratch path.
        if self._profile_temp is not None and self._profile_owner():
            # A forwarded/relaunched owner may outlive the stub. Preserve its
            # scratch profile rather than deleting files beneath a live browser.
            self._profile_temp._finalizer.detach()
            self._profile_temp = None
            self.profile = None
            self.logger('workbench_profile_cleanup_deferred', local_only=True)
        if self._profile_temp is not None and all(p.poll() is not None for p in self.processes):
            with self.lock:
                target = Path(self._profile_temp.name).resolve()
                if target.parent != self.profile_root.resolve() or not target.name.startswith('session-'):
                    # Preserve an unverified path, including against the temp
                    # object's automatic finalizer; cleanup cannot block exit.
                    self._profile_temp._finalizer.detach()
                    self._profile_temp = None
                    self.profile = None
                    self.logger('workbench_profile_cleanup_skipped', reason='path_boundary', local_only=True)
                    return
                try:
                    self._profile_temp.cleanup()
                except OSError:
                    self.logger('workbench_profile_cleanup_pending', local_only=True)
                else:
                    self._profile_temp = None
                    self.profile = None
