"""Main-thread Win32 notification window, served by Tcl's Windows notifier.

The tray calls PostMessage; no producer calls Tk, after(), or event_generate().
This hidden native window remains alive while the pet's Tk window is withdrawn.
"""
import threading
import ctypes

WAKE = 0x8000 + 111
ACTIVATE = WAKE + 1
DIAGNOSTIC = WAKE + 2
TEST_ACTIONS = {1: "show", 2: "hide", 3: "exit", 4: "snapshot"}


class WinMessageBridge:
    def __init__(self, class_name, on_wake, on_activate, on_clock_change,
                 logger, *, test_action=None, scheduler=None):
        import win32api
        import win32con
        import win32gui
        self.api, self.con, self.gui = win32api, win32con, win32gui
        self.owner = threading.get_ident()
        self.class_name = class_name
        self.on_wake, self.on_activate = on_wake, on_activate
        self.on_clock_change, self.logger = on_clock_change, logger
        self.test_action = test_action
        self.scheduler = scheduler
        self.pending = {}
        self.tk_binding = None
        if scheduler is not None:
            self._interp = scheduler.tk.interpaddr()
            self._tcl = ctypes.CDLL('tcl86t.dll')
            self._native_eval = self._tcl.Tcl_EvalEx
            self._native_eval.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
            self._native_eval.restype = ctypes.c_int
            self.tk_binding = scheduler.bind('<<HecateBridgeDelivery>>', self._deliver, add='+')
        self.hinstance = win32api.GetModuleHandle(None)
        self.hwnd = None
        self.closed = False
        self.registered = False
        wc = win32gui.WNDCLASS()
        wc.hInstance = self.hinstance
        wc.lpszClassName = class_name
        wc.lpfnWndProc = self._wndproc
        self.atom = win32gui.RegisterClass(wc)
        self.registered = True
        try:
            # Hidden top-level window also receives clock/resume broadcasts.
            self.hwnd = win32gui.CreateWindowEx(win32con.WS_EX_TOOLWINDOW,
                class_name, "Hecate event receiver", 0, 0, 0, 0, 0,
                0, 0, self.hinstance, None)
        except Exception as original:
            try:
                self.close()
            except Exception as cleanup_error:
                raise original from cleanup_error
            raise

    def _dispatch(self, function, *args):
        # Python's tkinter wrapper cannot reenter its saved thread state from
        # a pywin32 WndProc. Queue a virtual event using Tcl's C API instead.
        # The command has no callback at evaluation time (-when tail); Python
        # widget work runs later through Tk's ordinary binding machinery.
        if self.closed:
            return
        if self.scheduler is None:
            return function(*args)
        key = (function, args)
        if key in self.pending:
            return
        wake = not self.pending
        self.pending[key] = True
        if wake:
            result = self._native_eval(self._interp,
                b'event generate . <<HecateBridgeDelivery>> -when tail', -1, 0)
            if result:
                self.pending.clear()
                raise RuntimeError('Tk event delivery failed')

    def _deliver(self, _event=None):
        pending, self.pending = self.pending, {}
        for function, args in pending:
            if not self.closed:
                function(*args)
        return None

    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            if threading.get_ident() != self.owner:
                raise RuntimeError("Windows消息未在窗口所属线程执行")
            if self.closed:
                return self.gui.DefWindowProc(hwnd, message, wparam, lparam)
            if message == WAKE and wparam == 0 and lparam == 0:
                self._dispatch(self.on_wake)
                return 0
            if message == ACTIVATE and wparam == 0 and lparam == 0:
                self._dispatch(self.on_activate)
                return 0
            if message == DIAGNOSTIC:
                if self.test_action and wparam in TEST_ACTIONS and 0 <= lparam <= 0x7fffffff:
                    self._dispatch(self.test_action, TEST_ACTIONS[wparam], lparam)
                return 0
            if message in (self.con.WM_TIMECHANGE,self.con.WM_DISPLAYCHANGE):
                self._dispatch(self.on_clock_change)
                return 0
            if message == self.con.WM_POWERBROADCAST and wparam in (7, 18):
                self._dispatch(self.on_clock_change)
                return 1
            if message == self.con.WM_CLOSE:
                # No arbitrary native close message becomes an application command.
                return 0
        except Exception as exc:
            self.logger("bridge_handler_error", error=str(exc))
            return 0
        return self.gui.DefWindowProc(hwnd, message, wparam, lparam)

    def notify(self):
        if self.closed or not self.hwnd:
            raise RuntimeError("通知窗口已经关闭")
        self.gui.PostMessage(self.hwnd, WAKE, 0, 0)

    def close(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("通知窗口必须在创建线程销毁")
        self.closed = True
        errors = []
        def cleanup(step, function):
            try:
                function()
            except Exception as exc:
                errors.append(f"{step}: {exc}")
                self.logger("bridge_cleanup_error", step=step, error=str(exc))
        def release_window():
            if self.hwnd and self.gui.IsWindow(self.hwnd):
                self.gui.DestroyWindow(self.hwnd)
            self.hwnd = None
        def release_class():
            if self.registered:
                self.gui.UnregisterClass(self.class_name, self.hinstance)
                self.registered = False
        if self.scheduler is not None and self.tk_binding:
            cleanup("tk_binding", lambda: self.scheduler.unbind('<<HecateBridgeDelivery>>', self.tk_binding))
            self.tk_binding = None
        self.pending.clear()
        cleanup("window", release_window)
        cleanup("window_class", release_class)
        if errors:
            raise RuntimeError("通知窗口清理失败：" + "; ".join(errors))

    @property
    def released(self):
        return self.closed and self.hwnd is None and not self.registered
