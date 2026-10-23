"""Launch only the existing project-owned mobile publisher, with no caller paths."""
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import os

_lock=threading.Lock()
_process=None

def publisher_directory():
    root=Path(sys.executable).resolve().parent.parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    return root/'mobile'/'update-publisher'

def open_publisher(data_dir=None):
    global _process
    with _lock:
        if _process is not None and _process.poll() is None:
            return {'opened':True,'alreadyOpen':True}
        folder=publisher_directory()
        script=folder/'publish-window.py'
        python=shutil.which('pythonw.exe')
        if not python or not script.is_file() or not (folder/'current-release.json').is_file():
            raise ValueError('手机更新窗口尚未准备好，请交给主干检查。')
        env=os.environ.copy()
        if data_dir is not None:env['HECATE_STATE_DIR']=str(Path(data_dir).resolve())
        _process=subprocess.Popen([python,str(script),'--auto-start'],cwd=str(folder),env=env,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return {'opened':True,'alreadyOpen':False}
