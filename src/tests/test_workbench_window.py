import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from workbench_window import WorkbenchWindow
from tray_popup import TrayPopup

class Process:
    pid = 100
    def poll(self): return None
    def wait(self, timeout=None): return 0

class Gui:
    def __init__(self):
        self.windows = []; self.focus = []; self.shown = []; self.closed = []; self.minimized = False
    def EnumWindows(self, callback, data):
        for hwnd in list(self.windows): callback(hwnd, data)
    def IsWindowVisible(self, hwnd): return True
    def GetClassName(self, hwnd): return 'Chrome_WidgetWin_1'
    def IsIconic(self, hwnd): return self.minimized
    def ShowWindow(self, hwnd, mode): self.shown.append((hwnd, mode)); self.minimized = False
    def SetForegroundWindow(self, hwnd): self.focus.append(hwnd)
    def SendMessageTimeout(self, hwnd, *args): self.closed.append(hwnd); self.windows.remove(hwnd)

class WindowChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gui = Gui(); self.launches = []
        con = SimpleNamespace(SW_SHOW=5, SW_RESTORE=9, WM_CLOSE=16, SMTO_ABORTIFHUNG=2)
        # HWND 999 is an unrelated browser window and must be ignored.
        api = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 999 if hwnd == 999 else 100))
        def launch(args, **kwargs):
            self.launches.append(args); self.gui.windows.append(10); return Process()
        self.window = WorkbenchWindow(self.tmp.name, lambda *a, **kw: None,
            native=(self.gui, api, con), launcher=launch, browser='browser.exe')
        self.addCleanup(self.window.close)
    def test_new_hosts_use_distinct_browser_sessions(self):
        self.window.open('http://127.0.0.1:123/#session=first')
        self.assertTrue(self.window.ready.wait(2))
        other = WorkbenchWindow(self.tmp.name, lambda *a, **kw: None,
            native=(self.gui, self.window.process_api, self.window.con),
            launcher=self.window.launcher, browser='browser.exe')
        self.addCleanup(other.close)
        other.open('http://127.0.0.1:124/#session=second')
        self.assertTrue(other.ready.wait(2))
        self.assertNotEqual(self.window.profile, other.profile)
        self.assertEqual(self.window.profile.parent, other.profile.parent)
    def test_unverified_scratch_is_preserved_without_blocking_exit(self):
        outside = tempfile.TemporaryDirectory(prefix='outside-')
        path = Path(outside.name)
        self.window._profile_temp = outside
        self.window.profile = path
        try:
            self.window.close()
            self.assertTrue(path.is_dir())
            self.assertIsNone(self.window._profile_temp)
            self.assertFalse(outside._finalizer.alive)
        finally:
            outside.cleanup()

    def test_forwarding_launcher_exit_does_not_close_live_owner(self):
        transient = SimpleNamespace(pid=101, wait=lambda: 0, poll=lambda: 0)
        owner = SimpleNamespace(pid=100, poll=lambda: None)
        self.window.processes = [owner, transient]
        closed = []
        self.window._watch_exit(transient, lambda: closed.append(True))
        self.assertEqual(closed, [])
        self.window.processes = []
    def test_stub_exit_alone_never_stops_workbench(self):
        owner = SimpleNamespace(pid=100, wait=lambda: 0, poll=lambda: 0)
        self.window.processes = [owner]
        closed = []
        self.window._watch_exit(owner, lambda: closed.append(True))
        self.assertEqual(closed, [])

    def test_profile_owner_window_survives_exited_launcher(self):
        transient=SimpleNamespace(pid=101,poll=lambda:0,wait=lambda:0)
        self.window.processes=[transient]
        self.window.profile=Path(self.tmp.name)/'dedicated-session'
        self.gui.FindWindowEx=lambda parent,after,kind,title:20 if title==str(self.window.profile) else 0
        self.window.process_api.GetWindowThreadProcessId=lambda hwnd:(1,200 if hwnd in (10,20) else 999)
        self.gui.windows=[10,999]
        self.assertEqual(self.window._windows(),[10])
        self.window.profile=None
        self.assertEqual(self.window._windows(),[])
        self.gui.windows=[];self.window.processes=[]

    def test_repeated_open_restores_same_window_and_minimized_state(self):
        self.window.open('http://127.0.0.1:123/#session=fake')
        self.assertTrue(self.window.ready.wait(2))
        self.gui.minimized = True
        self.window.open('http://127.0.0.1:123/#session=fake')
        self.assertEqual(len(self.launches), 1)
        self.assertIn((10, 9), self.gui.shown)
        self.assertEqual(self.gui.focus[-1], 10)
    def test_unrelated_browser_is_not_focused_or_closed(self):
        self.gui.windows = [999]
        self.window.open('http://127.0.0.1:123/#session=fake')
        self.assertTrue(self.window.ready.wait(2))
        self.window.close()
        self.assertEqual(self.gui.windows, [999])
        self.assertNotIn(999, self.gui.focus)
        self.assertNotIn(999, self.gui.closed)
        self.assertTrue(any(x.startswith('--user-data-dir=' + self.tmp.name) for x in self.launches[0]))
        self.assertFalse(any('remote-debugging' in x for x in self.launches[0]))
    def test_closed_window_reopens(self):
        url = 'http://127.0.0.1:123/#session=fake'
        self.window.open(url); self.assertTrue(self.window.ready.wait(2))
        self.window.worker.join(2); self.gui.windows.clear()
        self.window.open(url); self.assertTrue(self.window.ready.wait(2))
        self.assertEqual(len(self.launches), 2)
    def test_fast_second_open_during_startup_does_not_launch_again(self):
        gate = threading.Event()
        self.window.launcher = lambda *a, **kw: (self.launches.append(a[0]) or Process())
        self.window.open('http://127.0.0.1:123/#session=fake')
        self.window.open('http://127.0.0.1:123/#session=fake')
        self.assertEqual(len(self.launches), 1)
        self.gui.windows.append(10)
        self.assertTrue(self.window.ready.wait(2))
    def test_new_session_closes_old_owned_window(self):
        self.window.open('http://127.0.0.1:123/#session=first')
        self.assertTrue(self.window.ready.wait(2)); self.window.worker.join(2)
        self.window.open('http://127.0.0.1:124/#session=second')
        self.assertTrue(self.window.ready.wait(2))
        self.assertIn(10, self.gui.closed)
        self.assertEqual(len(self.launches), 2)

class TrayPlacementChecks(unittest.TestCase):
    def test_reading_is_in_developer_group_both_states(self):
        for reading in (None, 0):
            drawn = []
            fake = SimpleNamespace(pet=SimpleNamespace(visible=True,scale=2,muted=False,reading_index=reading),
                c=SimpleNamespace(delete=lambda *a:None,create_image=lambda *a,**kw:None),
                s=1,_photo=None,hover=None,pressed=None,items=[],
                rect=lambda *a:None,text=lambda x,y,t,*a:drawn.append(('text',y,t)),
                row=lambda y,icon,label,command,*a:drawn.append(('row',y,command)))
            TrayPopup.draw(fake)
            header=next(y for kind,y,value in drawn if kind=='text' and value=='开发者工具')
            manual=next(y for kind,y,value in drawn if kind=='row' and value.startswith('reading:'))
            quota=next(y for kind,y,value in drawn if kind=='row' and value=='quota:open')
            self.assertLess(quota,header)
            self.assertGreater(manual,header)

if __name__ == '__main__': unittest.main()
