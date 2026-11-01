"""Optional browser workbench owned by the desktop host; no polling."""
import json
import threading
from pathlib import Path
from workbench.entrance import EntranceSession


class WorkbenchHost:
    def __init__(self, data_dir, resource_root, logger, *, opener=None, voice_notify=None, behavior_call=None, modules=None, module_notify=None, research_profile=None, chat_factory=None):
        if chat_factory is not None and not callable(chat_factory):
            raise ValueError("工作台聊天入口必须是可信的可调用工厂。")
        if chat_factory is not None and research_profile is not None:
            raise ValueError("自定义聊天入口不能直接接管现有研究资料目录。")
        self.chat_factory = chat_factory
        self.data_dir = Path(data_dir)
        self.resource_root = Path(resource_root)
        self.logger = logger
        self.window = None
        self.opener = opener
        self.desktop_voice_available = voice_notify is not None
        self.voice_notify = voice_notify or (lambda event: None)
        self.behavior_call = behavior_call
        self.modules = modules
        self.module_notify = module_notify
        self.server = None
        self.worker = None
        self.closed = False
        self.entrance = EntranceSession()
        self.research_profile = Path(research_profile) if research_profile is not None else None
        if self.research_profile is not None:
            if not self.research_profile.is_absolute() or self.research_profile.resolve()==self.data_dir.resolve():
                raise ValueError('研究工作台须使用独立的绝对资料目录，不能直接升级原版目录。')

    def _start_research(self):
        # preview_server holds a thread-owned reentrant gate: enter and exit
        # its context on this worker, never release that lock on the UI thread.
        from research_preview import preview_server
        ready=threading.Event();cancel=threading.Event();failed=[]
        def serve():
            try:
                with preview_server(self.research_profile,
                        voice_notify=self.voice_notify if self.desktop_voice_available else None,
                        entrance=self.entrance,behavior_call=self.behavior_call,
                        modules=self.modules,module_notify=self.module_notify) as server:
                    self.server=server
                    if cancel.is_set():return
                    ready.set();server.serve()
            except BaseException:
                failed.append(True)
            finally:ready.set()
        self.worker=threading.Thread(target=serve,name='gernze-research-workbench',daemon=True)
        self.worker.start()
        if not ready.wait(20):
            cancel.set()
            if self.server:self.server.stop()
            raise RuntimeError('研究工作台启动未完成，请保留资料后重试。')
        if failed or self.server is None:
            self.worker.join(9)
            raise RuntimeError('研究工作台未能启动，请检查独立资料目录。')
        self.logger('workbench_started',port=self.server.server_port,local_only=True,research_mode=True)

    def _seed_records(self, bridge):
        status = json.loads((self.resource_root / 'handoff_status.json').read_text(encoding='utf-8'))
        source = '二号归档同步：' + status['id']
        for row in status['records']:
            with bridge.store.connection() as db:
                exists = db.execute('SELECT 1 FROM records WHERE source=? AND title=? LIMIT 1',
                                    (source, row['title'])).fetchone()
            if not exists:
                bridge.memory.add(kind='project_log', source=source, occurred_at='2026-10-03',
                    memory_confirmed=False, scope='桌面EXE同步20261003', **row)

    def open(self, *, launch_browser=True):
        if self.closed:
            raise RuntimeError('工作台已随莉宝退出')
        if self.server and self.server.closing and self.window:
            self.window.close()
        if self.worker and self.worker.is_alive() and self.server.closing:
            self.worker.join(timeout=9)
            if self.worker.is_alive():
                raise RuntimeError('旧工作台仍在释放，请稍后再打开')
        if not self.worker or not self.worker.is_alive():
            if self.research_profile is not None:
                self._start_research()
            else:
                from workbench.server import WorkbenchServer
                chat_options = {"chat_factory": self.chat_factory} if self.chat_factory is not None else {}
                server = WorkbenchServer(self.data_dir, voice_notify=self.voice_notify if self.desktop_voice_available else None, entrance=self.entrance, behavior_call=self.behavior_call, modules=self.modules, module_notify=self.module_notify, **chat_options)
                try:
                    if self.chat_factory is None:
                        self._seed_records(server.bridge)
                except BaseException:
                    server.server_close()
                    raise
                self.server = server
                def serve():
                    try:
                        server.serve()
                    finally:
                        server.server_close()
                self.worker = threading.Thread(target=serve, name='hebao-workbench', daemon=True)
                self.worker.start()
                self.logger('workbench_started', port=server.server_port, local_only=True)
        if launch_browser:
            self.server.active()  # Cancel a previous pagehide grace timer before browser startup.
            if self.opener is None:
                from workbench_window import WorkbenchWindow
                if self.window is None:
                    self.window = WorkbenchWindow(self.research_profile or self.data_dir, self.logger)
                server_for_window = self.server
                def closed_window():
                    self.voice_notify("workbench_stop")
                    # A real native-window exit needs no reload grace period.
                    server_for_window.stop()
                self.window.on_closed = closed_window
                opener = self.window.open
            else:
                opener = self.opener  # Explicit test/embedding override only.
            if not opener(self.server.launch_url):
                self.close_service()
                raise RuntimeError('本机工作台窗口未能打开')
        return self.server

    def close_service(self):
        self.voice_notify("workbench_stop")
        if self.window:
            self.window.close()
        if self.server:
            self.server.stop()
        if self.worker:
            self.worker.join(timeout=9)
            if self.worker.is_alive():
                raise RuntimeError('工作台线程未在期限内退出')

    def close(self):
        self.closed = True
        self.close_service()
