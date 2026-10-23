"""Windows tray icon with event-driven delivery to the Tk main thread."""
from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path

import win32api
import win32con
import win32gui


CALLBACK = win32con.WM_USER + 31
TRAY_CLASS = "HecatePixelTrayDeepSeekTrial"
SHOW, HIDE, MUTE, EXIT, SIZE_1, SIZE_2, SIZE_3, QUOTA, READING = range(2001, 2010)
ACTIONS = {
    SHOW: "show",
    HIDE: "hide",
    MUTE: "mute",
    EXIT: "exit",
    SIZE_1: "size:1",
    SIZE_2: "size:2",
    SIZE_3: "size:3",
    QUOTA: "quota:open",
    READING: "reading:play",
    2010: "voice_modules:open",
}


class TrayIcon(threading.Thread):
    def __init__(self, commands: queue.Queue, logger, notify, icon_path: Path):
        super().__init__(name="hebao-tray", daemon=True)
        self.commands = commands
        self.logger = logger
        self.notify = notify
        self.icon_path = Path(icon_path)
        self.ready = threading.Event()
        self.error = None
        self.hwnd = None
        self.icon = None
        self.icon_id = 1

    def _post(self, command: str):
        self.commands.put(command)
        try:
            self.notify()
        except (RuntimeError, OSError) as exc:
            self.logger("tray_notify_failed", command=command, error=str(exc))

    def run(self):
        try:
            if not self.icon_path.is_file():
                raise FileNotFoundError(self.icon_path)
            hinstance = win32api.GetModuleHandle(None)
            wc = win32gui.WNDCLASS()
            wc.hInstance = hinstance
            wc.lpszClassName = TRAY_CLASS
            wc.lpfnWndProc = self.wndproc
            win32gui.RegisterClass(wc)
            self.hwnd = win32gui.CreateWindow(
                TRAY_CLASS, "莉宝桌宠托盘", 0, 0, 0, 0, 0, 0, 0, hinstance, None
            )
            self.icon = win32gui.LoadImage(
                0, str(self.icon_path), win32con.IMAGE_ICON, 16, 16,
                win32con.LR_LOADFROMFILE,
            )
            nid = (
                self.hwnd, self.icon_id,
                win32gui.NIF_MESSAGE | win32gui.NIF_ICON | win32gui.NIF_TIP,
                CALLBACK, self.icon, "莉宝桌宠",
            )
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
            self.logger("tray_ready", hwnd=self.hwnd, icon=str(self.icon_path))
            self.ready.set()
            win32gui.PumpMessages()
        except Exception as exc:
            self.error = str(exc)
            self.logger("tray_error", error=str(exc), trace=traceback.format_exc())
            self.ready.set()

    def wndproc(self, hwnd, msg, wparam, lparam):
        if msg == CALLBACK:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                self._post("show")
            elif lparam in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
                self.show_menu(hwnd)
            return 0
        if msg == win32con.WM_COMMAND:
            action = ACTIONS.get(wparam & 0xFFFF)
            if action:
                self._post(action)
            return 0
        if msg == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, self.icon_id))
            finally:
                if self.icon:
                    win32gui.DestroyIcon(self.icon)
                win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def show_menu(self, hwnd):
        x,y=win32gui.GetCursorPos()
        self._post(f'menu:{x}:{y}')
        return

    def show_native_fallback_menu(self, hwnd):
        menu = win32gui.CreatePopupMenu()
        try:
            for command, label in [
                (SHOW, "显示莉宝"), (HIDE, "隐藏莉宝"),
                (MUTE, "切换静音"), (SIZE_1, "大小 1×"),
                (SIZE_2, "大小 2×"), (SIZE_3, "大小 3×"),
                (QUOTA, "DeepSeek 额度设置"),
                (READING, "立即看书（试装）"),
                (2010, "开发者：声音模块"),
                (EXIT, "退出"),
            ]:
                win32gui.AppendMenu(menu, win32con.MF_STRING, command, label)
            x, y = win32gui.GetCursorPos()
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            chosen = win32gui.TrackPopupMenu(
                menu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                x, y, 0, hwnd, None,
            )
            action = ACTIONS.get(chosen)
            if action:
                self._post(action)
            win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
        finally:
            win32gui.DestroyMenu(menu)

    def stop(self):
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
