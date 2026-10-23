"""Explicit host integration, with no module import until the user opens it."""
from pathlib import Path


class ModuleHooks:
    def __init__(self, root, data_dir, *, factory=None):
        self.root, self.data_dir = root, Path(data_dir)
        self.factory = factory
        self.controller = None
        self.quiet_before_hide = None
        self.closed = False

    def ensure(self):
        if self.closed:
            raise RuntimeError("桌宠模块已退出")
        if self.controller is None:
            if self.factory is None:
                from libao_modules.ui import ModuleController
                self.factory = ModuleController
            self.controller = self.factory(self.root, self.data_dir)
        return self.controller

    def open(self):
        self.ensure().open()

    def hide(self):
        if self.controller:
            if self.quiet_before_hide is None:
                self.quiet_before_hide = self.controller.reminders.quiet
            self.controller.set_quiet_mode(True)
            self.controller.hide_tools()

    def show(self):
        if self.controller and self.quiet_before_hide is not None:
            quiet, self.quiet_before_hide = self.quiet_before_hide, None
            self.controller.set_quiet_mode(quiet)

    def clock_change(self):
        if self.controller and not self.closed:
            self.controller.on_resume_or_clock_change()

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        if self.controller:
            self.controller.shutdown()
