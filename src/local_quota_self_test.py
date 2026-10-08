"""Packaged Windows acceptance checks; isolated storage and synthetic quota."""
import json
import time
import sys
import traceback
from unittest.mock import patch
from PIL import ImageGrab
from hebao_quota.local_snapshot import LocalHistory, HistoricalWindow

def schedule(pet):
    import app
    checks=[]
    fixture=LocalHistory(time.time(),(
        HistoricalWindow(36,300,int(time.time()+18000)),
        HistoricalWindow(6,10080,int(time.time()+604800))),1)
    patches=[]
    deadline=time.monotonic()+15
    def check(name,condition):
        checks.append({"check":name,"passed":bool(condition)})
        if not condition: raise AssertionError(name)
    def guard(fn):
        def wrapped():
            try: fn()
            except Exception:
                checks.append({"check":"unexpected_error","passed":False,"error":traceback.format_exc()})
                finish()
        return wrapped
    def fake_read(**_):
        time.sleep(.12)
        return fixture
    def native_ui_checks():
        import ctypes
        import tkinter as tk
        from tkinter import ttk
        import win32api
        from decimal import Decimal
        from quota_card import CardState
        from hebao_quota.models import Balance, Snapshot
        from tray_popup import TrayPopup
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        before={k:str(v) for k,v in ttk.Style(pet.root).configure('TButton').items()}
        geometry={}
        def capture(window,name):
            window.deiconify();window.lift();window.focus_force();pet.root.update()
            # Let the compositor paint this self-test window before capturing it.
            time.sleep(.15);pet.root.update_idletasks()
            x,y,w,h=window.winfo_rootx(),window.winfo_rooty(),window.winfo_width(),window.winfo_height()
            ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(app.OUTPUT/(name+'.png'))
            geometry[name]={'x':x,'y':y,'width':w,'height':h}
        pet.modules.open();controller=pet.modules.controller;tool=controller.window
        pet.modules.open()
        check('packaged_tools_use_new_ui_and_reuse_window',controller.window is tool and hasattr(tool,'pages'))
        check('tools_do_not_enable_reminders',not controller.reminders.enabled and controller.reminders.token is None)
        capture(tool.window,'starry_tools_empty')
        tool.load_sample();tool.notebook.select(1);capture(tool.window,'starry_tools_project')
        tool.notebook.select(2);capture(tool.window,'starry_tools_reminders')
        tool.notebook.select(0);tool.window.geometry('740x520');pet.root.update()
        tool.pages[0].canvas.yview_moveto(1);capture(tool.window,'starry_tools_narrow')
        check('narrow_tools_scroll_and_fit',tool.pages[0].body.winfo_height()>tool.pages[0].canvas.winfo_height() and tool.pages[0].body.winfo_width()<=tool.pages[0].canvas.winfo_width())
        tool.close();check('tool_close_releases_window',controller.window is None)
        pet.open_quota_card();card=pet.quota_card
        snapshot=Snapshot('deepseek','offline-fictional','离线虚构账户',time.time(),balances=(Balance('CNY',Decimal('18.60'),Decimal('16.00'),Decimal('2.60')),),available=True)
        card.render(CardState(key_present=True,enabled=True,snapshot=snapshot,demo=True))
        capture(card,'starry_deepseek_demo')
        check('card_displays_explicit_offline_demo','离线示例' in card.status.cget('text'))
        card.show_balance_details();details=card._balance_dialog
        capture(details,'starry_currency_demo');details.destroy()
        pet._close_quota_card();check('detail_panel_close_stops_requests',not pet._panel_visible())
        monitor=win32api.MonitorFromPoint((pet.root.winfo_rootx(),pet.root.winfo_rooty()),2)
        work=win32api.GetMonitorInfo(monitor)['Work']
        popup=TrayPopup(pet,work[2]-10,work[3]-10)
        capture(popup,'starry_tray')
        check('tray_has_all_original_commands',{'workbench:open','modules:open','quota:open','walk:open','actions:open','size:1','size:2','size:3','exit'} <= {command for _,command in popup.items})
        check('tray_inside_monitor_work_area',work[0]<=popup.winfo_rootx() and work[1]<=popup.winfo_rooty() and popup.winfo_rootx()+popup.winfo_width()<=work[2] and popup.winfo_rooty()+popup.winfo_height()<=work[3])
        geometry['dpi']=ctypes.windll.user32.GetDpiForWindow(popup.winfo_id())
        geometry['tray_scale']=popup.s
        popup.close()
        check('ui_does_not_modify_default_widget_theme',{k:str(v) for k,v in ttk.Style(pet.root).configure('TButton').items()}==before)
        (app.OUTPUT/'starry_ui_geometry.json').write_text(json.dumps(geometry,ensure_ascii=False,indent=2),encoding='utf-8')
    def begin():
        check("credentials_and_network_disabled",not pet.key_present and not pet.quota_enabled)
        pet._cancel_reading()
        native_ui_checks()
        patches.append(patch.object(sys.modules[pet.__class__.__module__],"read_local_history",fake_read))
        patches[-1].start()
        pet.open_quota_overview()
        check("both_sources_share_one_overview", "codex_value" in pet.quota_overview._labels and "deepseek_value" in pet.quota_overview._labels)
        check("opening_does_not_scan",pet._local_worker is None)
        pet._local_enabled=True
        check("manual_read_started",pet._read_local_history())
        check("concurrent_read_rejected",not pet._read_local_history())
        pet.root.after(350,guard(read_done))
    def read_done():
        if pet._local_busy and time.monotonic()<deadline:
            pet.root.after(50,guard(read_done))
            return
        check("result_delivered_on_ui_thread",not pet._local_busy and pet._local_history==fixture)
        check("current_account_stays_unknown","未知" in pet.quota_overview._labels["codex_value"].cget("text"))
        check("history_marked_nonrealtime","非实时" in pet.quota_overview._labels["codex_updated"].cget("text"))
        pet.quota_overview._labels["codex_source"].configure(text="Codex 本地历史快照 · 离线模拟")
        pet.quota_overview.update_idletasks()
        x,y=pet.quota_overview.winfo_rootx(),pet.quota_overview.winfo_rooty()
        w,h=pet.quota_overview.winfo_width(),pet.quota_overview.winfo_height()
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(app.OUTPUT/"local_quota_preview.png")
        generation=pet._local_generation
        pet._local_results.put((generation,fixture,""))
        pet._toggle_local_history()
        pet._drain_quota()
        check("disable_discards_old_result",not pet._local_enabled and pet._local_history is None)
        check("disabled_read_rejected",not pet._read_local_history())
        pet._toggle_local_history()
        pet._read_local_history()
        pet.hide()
        pet.root.after(250,guard(hidden))
    def hidden():
        check("hidden_cancels_local_read",not pet._local_busy and pet._local_cancel.is_set())
        check("hidden_closes_overview",pet.quota_overview.state()=="withdrawn")
        check("hidden_animation_timers_canceled",all(getattr(pet,n) is None for n in ("frame_job","reading_job","reading_start_job","reading_end_job")))
        pet._drain_quota()
        check("late_hidden_result_discarded",pet._local_history is None)
        pet.show()
        pet.open_quota_overview()
        check("reopen_keeps_current_unknown","未知" in pet.quota_overview._labels["codex_value"].cget("text"))
        pet.root.after(100,guard(finish))
    def finish():
        for patcher in patches: patcher.stop()
        try:
            pet.quit()
            check("reader_thread_released",pet._local_worker is None or not pet._local_worker.is_alive())
            check("exit_releases_tray",not pet.tray.is_alive())
            check("exit_releases_notification_window",pet.bridge.released)
        except Exception:
            checks.append({"check":"exit_error","passed":False,"error":traceback.format_exc()})
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/"local_quota_results.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding="utf-8")
    pet.root.after(250,guard(begin))



