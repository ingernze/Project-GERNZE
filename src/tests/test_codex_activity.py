import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from codex_activity import CodexActivityWindow

class FakeProcess:
    pid=12
    def __init__(self): self.exited=False;self.terminated=False;self.timeout=False
    def poll(self): return 0 if self.exited else None
    def wait(self,timeout=None):
        if self.timeout and not self.terminated: raise subprocess.TimeoutExpired('owned',timeout)
        self.exited=True;return 0
    def terminate(self): self.terminated=True;self.exited=True

class Gui:
    def __init__(self): self.windows=[1,999];self.shown=[];self.focus=[];self.closed=[]
    def EnumWindows(self,callback,data):
        for hwnd in list(self.windows): callback(hwnd,data)
    def IsWindowVisible(self,hwnd): return True
    def GetClassName(self,hwnd): return 'WindowsForms10.Window'
    def ShowWindow(self,hwnd,mode):self.shown.append((hwnd,mode))
    def SetForegroundWindow(self,hwnd):self.focus.append(hwnd)
    def SendMessageTimeout(self,hwnd,*args):self.closed.append(hwnd)

class ActivityChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);exe=root/'assets/codex_monitor/QuietCodexMonitor.exe'
        exe.parent.mkdir(parents=True);exe.touch()
        self.gui=Gui();self.launches=[]
        api=SimpleNamespace(GetWindowThreadProcessId=lambda hwnd:(1,12 if hwnd==1 else 999))
        con=SimpleNamespace(SW_RESTORE=9,SW_MINIMIZE=6,WM_CLOSE=16,SMTO_ABORTIFHUNG=2)
        def launch(args,**kw):self.launches.append((args,kw));return FakeProcess()
        self.window=CodexActivityWindow(root,lambda *a,**kw:None,sessions=root/'sessions',launcher=launch,native=(self.gui,api,con))
        self.addCleanup(self.window.close)
    def test_launch_is_manual_explicit_no_shell_and_parent_scoped(self):
        self.assertIsNone(self.window.process)
        self.window.open();args,kw=self.launches[0]
        self.assertFalse(kw['shell']);self.assertEqual(len(args),3)
        self.assertEqual(Path(args[1]),self.window.sessions)
        self.assertTrue(args[2].isdigit())
    def test_fast_repeat_reuses_owned_process_without_other_focus(self):
        self.window.open();self.window.open()
        self.assertEqual(len(self.launches),1);self.assertEqual(self.gui.focus,[1])
    def test_hide_and_close_only_touch_owned_viewer(self):
        self.window.open();self.window.hide();self.window.close()
        self.assertEqual(self.gui.shown,[(1,6)]);self.assertEqual(self.gui.closed,[1])
    def test_process_still_starting_no_second_launch(self):
        self.gui.windows=[];self.window.open();self.window.open()
        self.assertEqual(len(self.launches),1)
    def test_hung_child_cleanup_and_reopen(self):
        proc=self.window.open();proc.timeout=True;self.window.close()
        self.assertTrue(proc.terminated);self.window.open();self.assertEqual(len(self.launches),2)
    def test_missing_component_does_not_launch(self):
        self.window.exe=self.window.exe.parent/'missing.exe'
        with self.assertRaises(FileNotFoundError):self.window.open()
        self.assertFalse(self.launches)

if __name__=='__main__':unittest.main()
