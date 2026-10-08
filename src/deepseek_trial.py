"""Independent Windows trial of the Hecate DeepSeek API balance card."""
from __future__ import annotations

import math
import queue
import threading
import sys
import os
import hashlib

from PIL import ImageGrab

import app
import credential_store
from workbench_host import WorkbenchHost
from codex_activity import CodexActivityWindow
from hebao_quota.providers import DeepSeekProvider
from hebao_quota.service import QuotaService
from quota_card import CardState, QuotaCard
from local_quota_card import OverviewState, QuotaOverview
from hebao_quota.local_snapshot import read_local_history

if any(flag in sys.argv for flag in ("--scene-settings-self-test", "--voice-entry-self-test", "--voice-text-self-test", "--voice-module-self-test", "--blink-self-test", "--voice-self-test", "--metadata-self-test", "--walk-self-test","--reading-self-test","--actions-self-test","--random-actions-self-test", "--style2-grab-self-test", "--grab-self-test", "--head-click-self-test", "--inertia-self-test", "--benchmark","--sync-self-test","--local-quota-self-test","--style-self-test", "--offline-self-test")):
    if not os.environ.get("HECATE_STATE_DIR"):
        raise RuntimeError("Acceptance tests require an isolated HECATE_STATE_DIR")
    import tray_win32
    suffix=hashlib.sha256(os.environ["HECATE_STATE_DIR"].encode()).hexdigest()[:12]
    app.MUTEX_NAME="Local\\HecateWalkTest_"+suffix
    tray_win32.TRAY_CLASS=app.TRAY_CLASS="HecateWalkTestTray_"+suffix



class DeepSeekTrialPet(app.HecatePet):
    def __init__(self):
        self.quota_overview = None
        self._local_history = None
        self._local_read = False
        self._local_busy = False
        self._local_error = ""
        self._local_results = queue.SimpleQueue()
        self._local_generation = 0
        self._local_cancel = threading.Event()
        self._local_worker = None
        self.workbench = None
        self.codex_activity = None
        self.quota_service = None
        self.quota_card = None
        self.quota_snapshot = None
        self.quota_error = ""
        self.quota_notice = ""
        self._quota_cooldown_job = None
        self.key_present = False
        self.credential_error = False
        super().__init__()
        self._local_enabled = bool(self.settings.get("codex_local_enabled", True))
        self.workbench = WorkbenchHost(app.STATE_ROOT, app.ROOT, app.log,
            voice_notify=lambda event:self._enqueue_command('voice:'+event),
            behavior_call=self.activity_settings_call, modules=self.optional_modules,
            module_notify=lambda:self._enqueue_command('packages:open'))
        self.codex_activity = CodexActivityWindow(app.ROOT, app.log)
        self.quota_enabled = False if any(flag in sys.argv for flag in ("--scene-settings-self-test", "--voice-entry-self-test", "--voice-text-self-test", "--voice-module-self-test", "--blink-self-test", "--voice-self-test", "--metadata-self-test", "--style-self-test", "--offline-self-test", "--sync-self-test", "--local-quota-self-test", "--walk-self-test", "--reading-self-test", "--actions-self-test", "--random-actions-self-test", "--style2-grab-self-test", "--grab-self-test", "--head-click-self-test", "--inertia-self-test", "--benchmark")) else bool(self.settings.get("deepseek_enabled", False))
        self._read_key_state()
        self.quota_service = QuotaService(
            {"deepseek": DeepSeekProvider(credential_store.get_key)},
            wake_ui=self._wake_quota_ui,
            interval_s=900,
            manual_cooldown_s=300,
            auto_refresh={"deepseek": True, "codex": False},
        )
        if not self.key_present:
            self.quota_enabled = False
            if not self.credential_error and self.settings.get("deepseek_enabled", False):
                self.settings["deepseek_enabled"] = False
                app.save_settings(self.settings)
        # A hidden balance panel does not make automatic requests.
        self._configure_quota()
        app.log("deepseek_trial_ready", enabled=self.quota_enabled,
                key_present=self.key_present)
        if "--offline-self-test" in sys.argv:
            if self.quota_enabled or self.key_present:
                raise RuntimeError("Offline screenshot requires no saved key and plugin disabled")
            self.root.after(300, self.open_quota_card)
            self.root.after(850, self._capture_offline_card)
            self.root.after(1150, self.hide)
            self.root.after(1500, self.show)
            self.root.after(1950, self.quit)

        if '--scene-settings-self-test' in sys.argv:
            from scene_settings_self_test import schedule
            schedule(self)
        elif '--voice-entry-self-test' in sys.argv:
            from voice_entry_self_test import schedule
            schedule(self)
        elif '--voice-text-self-test' in sys.argv:
            from voice_text_self_test import schedule
            schedule(self)
        elif '--voice-module-self-test' in sys.argv:
            from voice_module_self_test import schedule
            schedule(self)
        elif '--blink-self-test' in sys.argv:
            from blink_self_test import schedule
            schedule(self)
        elif '--voice-self-test' in sys.argv:
            from voice_self_test import schedule
            schedule(self)
        elif '--metadata-self-test' in sys.argv:
            from metadata_self_test import schedule
            schedule(self)
        elif '--style-self-test' in sys.argv:
            from style_self_test import schedule
            schedule(self)
        elif "--inertia-self-test" in sys.argv:
            from inertia_self_test import schedule
            schedule(self)
        elif "--head-click-self-test" in sys.argv:
            from head_click_self_test import schedule
            schedule(self)
        elif "--style2-grab-self-test" in sys.argv:
            from style2_grab_self_test import schedule
            schedule(self)
        elif "--grab-self-test" in sys.argv:
            from grab_self_test import schedule
            schedule(self)
        elif "--random-actions-self-test" in sys.argv:
            from random_actions_self_test import schedule
            schedule(self)
        elif "--actions-self-test" in sys.argv:
            from manual_actions_self_test import schedule
            schedule(self)
        elif "--walk-self-test" in sys.argv:
            from walk_self_test import schedule
            schedule(self)
        elif "--reading-self-test" in sys.argv:
            from reading_v05_self_test import schedule
            schedule(self)
        elif "--local-quota-self-test" in sys.argv:
            from local_quota_self_test import schedule
            schedule(self)
        elif "--sync-self-test" in sys.argv:
            from sync_self_test import schedule
            schedule(self)
        elif '--show-voice-text' in sys.argv:
            self.root.after_idle(self.open_voice_text)
        elif '--show-style-controls' in sys.argv:
            self.root.after_idle(self.open_style_controls)
        elif "--show-action-controls" in sys.argv:
            self.root.after_idle(self.open_action_controls)
        elif "--show-reading" in sys.argv:
            self.root.after_idle(self.start_reading)
        elif "--show-walk-controls" in sys.argv:
            self.root.after_idle(self.open_walk_controls)
        elif "--show-codex-activity" in sys.argv:
            self.root.after_idle(self.open_codex_activity)
        elif "--show-quota-overview" in sys.argv:
            self.root.after_idle(self.open_quota_overview)
        elif "--style-self-test" not in sys.argv and "--offline-self-test" not in sys.argv and "--benchmark" not in sys.argv and "--pet-only" not in sys.argv:
            self.root.after_idle(self.open_workbench)

    def open_codex_activity(self):
        if self.closing:
            return
        try:
            self.codex_activity.open()
        except (OSError, RuntimeError) as exc:
            app.log("codex_activity_open_failed", error=str(exc))
            from tkinter import messagebox
            messagebox.showerror("Codex 活动观察", str(exc), parent=self.root)

    def open_quota_overview(self):
        if self.closing:
            return
        if not self.visible:
            self.show()
        if self.quota_overview is None or not self.quota_overview.winfo_exists():
            self.quota_overview = QuotaOverview(self.root,
                on_deepseek=self.open_quota_card, on_read=self._read_local_history,
                on_toggle=self._toggle_local_history, on_close=self._close_quota_overview)
        else:
            self.quota_overview.deiconify()
            self.quota_overview.lift()
        self._update_card()

    def _cancel_local_read(self):
        self._local_generation += 1
        self._local_cancel.set()
        self._local_busy = False

    def _read_local_history(self):
        if (self.closing or not self.visible or not self._local_enabled or self._local_busy
                or self.quota_overview is None or not self.quota_overview.winfo_exists()
                or self.quota_overview.state() != "normal"):
            return False
        self._local_generation += 1
        generation = self._local_generation
        cancel = self._local_cancel = threading.Event()
        self._local_busy = True
        self._local_error = ""
        self._local_history = None
        self._update_card()
        def work():
            try:
                history = read_local_history(cancel=cancel)
                error = ""
            except Exception:
                history, error = None, "本地记录暂不可读"
            if not cancel.is_set():
                self._local_results.put((generation, history, error))
                self._wake_quota_ui()
        self._local_worker = threading.Thread(target=work, name="hebao-local-quota", daemon=True)
        self._local_worker.start()
        return True

    def _toggle_local_history(self):
        self._cancel_local_read()
        self._local_enabled = not self._local_enabled
        self.settings["codex_local_enabled"] = self._local_enabled
        app.save_settings(self.settings)
        self._local_history = None
        self._local_error = ""
        self._local_read = False
        self._update_card()

    def _close_quota_overview(self):
        self._cancel_local_read()
        if self.quota_overview is not None and self.quota_overview.winfo_exists():
            self.quota_overview.withdraw()
        self._update_card()

    def open_workbench(self):
        if not self.closing and self.workbench is not None:
            try:
                self.workbench.open()
            except Exception as exc:
                app.log("workbench_open_failed", error=type(exc).__name__)
                from tkinter import messagebox
                messagebox.showerror("赫宝工作台", "工作台打开失败，赫宝仍可使用。请查看本机日志。", parent=self.root)

    def _read_key_state(self):
        if any(flag in sys.argv for flag in ("--scene-settings-self-test", "--voice-entry-self-test", "--voice-text-self-test", "--voice-module-self-test", "--blink-self-test", "--voice-self-test", "--metadata-self-test", "--style-self-test", "--offline-self-test", "--sync-self-test", "--local-quota-self-test", "--walk-self-test", "--reading-self-test", "--actions-self-test", "--random-actions-self-test", "--style2-grab-self-test", "--grab-self-test", "--head-click-self-test", "--inertia-self-test", "--benchmark")):
            self.key_present = False
            self.credential_error = False
            return
        try:
            self.key_present = bool(credential_store.get_key())
            self.credential_error = False
        except Exception:
            self.key_present = False
            self.credential_error = True

    def _panel_visible(self):
        return (self.visible and self.quota_card is not None and
                self.quota_card.winfo_exists() and self.quota_card.state() == "normal")

    def _configure_quota(self):
        if self.quota_service is not None:
            self.quota_service.configure(enabled=self.quota_enabled,
                                         visible=self._panel_visible(),
                                         active="deepseek" if self.quota_enabled else None)

    def _capture_offline_card(self):
        if not self._panel_visible() or self.key_present:
            return
        self.quota_card.update_idletasks()
        x, y = self.quota_card.winfo_rootx(), self.quota_card.winfo_rooty()
        w, h = self.quota_card.winfo_width(), self.quota_card.winfo_height()
        app.OUTPUT.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x+w, y+h), all_screens=True).save(
            app.OUTPUT / "deepseek_offline_card.png")
        app.log("deepseek_offline_screenshot", key_present=False)

    def _wake_quota_ui(self):
        if not self.closing:
            self._enqueue_command("quota:drain")

    def _update_card(self):
        if self.quota_overview is not None and self.quota_overview.winfo_exists():
            self.quota_overview.render(OverviewState(
                deepseek_snapshot=self.quota_snapshot, deepseek_enabled=self.quota_enabled,
                deepseek_error=self.quota_error, local_enabled=self._local_enabled,
                local_history=self._local_history, local_busy=self._local_busy,
                local_error=self._local_error, local_read=self._local_read))
        if self._quota_cooldown_job is not None:
            self.root.after_cancel(self._quota_cooldown_job)
            self._quota_cooldown_job = None
        if self.quota_card is None or not self.quota_card.winfo_exists():
            return
        timing = self.quota_service.read_state() if self.quota_service else None
        cooldown = timing.manual_cooldown_remaining if timing else 0.0
        self.quota_card.render(CardState(
            key_present=self.key_present, credential_error=self.credential_error,
            enabled=self.quota_enabled, visible=self._panel_visible(),
            busy=timing.busy if timing else False, snapshot=self.quota_snapshot,
            error=self.quota_error, notice=self.quota_notice,
            cooldown_remaining=cooldown,
            next_refresh_remaining=timing.next_auto_remaining if timing else None,
        ))
        # One callback at cooldown expiry. No repeating idle polling.
        if cooldown > 0 and self._panel_visible():
            self._quota_cooldown_job = self.root.after(
                math.ceil(cooldown*1000)+80, self._update_card)

    def _drain_quota(self):
        if self.closing or self.quota_service is None:
            return
        while not self._local_results.empty():
            generation, history, error = self._local_results.get()
            if generation == self._local_generation and self._local_enabled:
                self._local_history = history
                self._local_error = error
                self._local_read = True
                self._local_busy = False
                app.log("codex_local_history_read", found=history is not None,
                        current_account_verified=False)
        results, _alerts = self.quota_service.drain()
        for result in results:
            if result.snapshot:
                self.quota_snapshot = result.snapshot
                self.quota_error = ""
                self.quota_notice = ""
                app.log("deepseek_balance_read", success=True,
                        balance_rows=len(result.snapshot.balances))
            else:
                self.quota_error = result.error or "余额读取失败"
                self.quota_notice = ""
                app.log("deepseek_balance_read", success=False, status=result.status)
        self._update_card()

    def _save_key(self, value: str):
        value = value.strip()
        if not value:
            self.quota_notice = "请输入 API Key"
            self._update_card()
            return
        try:
            credential_store.save_key(value)
        except Exception:
            self.quota_notice = "密钥保存失败；请检查 Windows 凭据管理器"
            self._update_card()
            return
        # Clear old-account data before invalidating or starting a new fetch.
        self.quota_snapshot = None
        self.quota_error = ""
        self.quota_notice = "密钥已保存在本机；等待新账户余额"
        self._read_key_state()
        self.quota_service.invalidate("deepseek")
        self._update_card()
        app.log("deepseek_key_changed", action="saved")

    def _delete_key(self):
        self.quota_enabled = False
        self.settings["deepseek_enabled"] = False
        app.save_settings(self.settings)
        self._configure_quota()
        try:
            credential_store.delete_key()
        except Exception:
            self.quota_notice = "删除失败：密钥可能仍保存在本机；读取已停用"
            self._read_key_state()
            self._update_card()
            return
        self.quota_service.invalidate("deepseek")
        self.quota_snapshot = None
        self.quota_error = ""
        self.quota_notice = "本机密钥已删除，余额数据已清空"
        self._read_key_state()
        self._update_card()
        app.log("deepseek_key_changed", action="deleted")

    def _toggle_enabled(self):
        if not self.quota_enabled:
            self._read_key_state()
            if not self.key_present or self.credential_error:
                self.quota_notice = "请先在本机保存 DeepSeek API Key"
                self._update_card()
                self.quota_card.open_key_manager()
                return
        self.quota_enabled = not self.quota_enabled
        self.settings["deepseek_enabled"] = self.quota_enabled
        app.save_settings(self.settings)
        self.quota_notice = ("余额读取已启用" if self.quota_enabled else
                             "余额读取已停用；密钥和上次结果保留")
        self._configure_quota()
        self._update_card()
        app.log("deepseek_plugin_state", enabled=self.quota_enabled)

    def _manual_refresh(self):
        if not self.quota_enabled:
            self.quota_notice = "请先启用自动刷新"
        elif not self._panel_visible():
            self.quota_notice = "面板隐藏时暂停读取"
        elif self.quota_service.refresh(force=True):
            self.quota_notice = "正在读取官方余额"
            self.quota_error = ""
        else:
            self.quota_notice = "正在读取或处于五分钟冷却期"
        self._update_card()

    def open_quota_card(self):
        if self.closing:
            return
        if not self.visible:
            self.show()
        if self.quota_card is not None and self.quota_card.winfo_exists():
            self.quota_card.deiconify()
            self.quota_card.lift()
        else:
            self.quota_card = QuotaCard(self.root, on_save=self._save_key,
                on_delete=self._delete_key, on_toggle=self._toggle_enabled,
                on_refresh=self._manual_refresh, on_close=self._close_quota_card)
        self._configure_quota()
        self._update_card()

    def _close_quota_card(self):
        if self.quota_card is None or not self.quota_card.winfo_exists():
            return
        self.quota_card.close_key_manager()
        self.quota_card.withdraw()
        self._configure_quota()
        self._update_card()

    def hide(self):
        if self.codex_activity is not None:
            self.codex_activity.hide()
        self._cancel_local_read()
        if self.quota_overview is not None and self.quota_overview.winfo_exists():
            self.quota_overview.withdraw()
        if self.quota_card is not None and self.quota_card.winfo_exists():
            self.quota_card.close_key_manager()
            self.quota_card.withdraw()
        if self.quota_service is not None:
            self.quota_service.configure(enabled=self.quota_enabled, visible=False,
                                         active="deepseek" if self.quota_enabled else None)
        super().hide()
        self._update_card()

    def show(self):
        super().show()
        self._configure_quota()
        self._update_card()

    def quit(self):
        package_window=getattr(self,'packages_window',None)
        if package_window is not None and package_window.busy:
            from tkinter import messagebox
            messagebox.showinfo('正在整理模块','请等当前安装或移除完成，再退出赫宝。',parent=package_window)
            return
        if self.closing:
            return
        self._cancel_local_read()
        if self._local_worker is not None:
            self._local_worker.join(timeout=0.5)
        if self.codex_activity is not None:
            self.codex_activity.close()
        if self.workbench is not None:
            self.workbench.close()
        if self._quota_cooldown_job is not None:
            self.root.after_cancel(self._quota_cooldown_job)
            self._quota_cooldown_job = None
        if self.quota_card is not None and self.quota_card.winfo_exists():
            self.quota_card.close_key_manager()
        if self.quota_service is not None:
            self.quota_service.close()
        super().quit()


if __name__ == "__main__":
    mutex = app.claim_single_instance()
    if mutex is not None:
        try:
            DeepSeekTrialPet().run()
        finally:
            app.win32api.CloseHandle(mutex)

