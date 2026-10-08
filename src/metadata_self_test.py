"""Isolated real packaged viewer lifecycle acceptance, no real Codex data."""
import json
import traceback
import win32gui
import win32con


def schedule(pet):
    import app
    from codex_activity import CodexActivityWindow
    from tray_popup import TrayPopup
    checks=[]
    proc=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value: raise AssertionError(name)
    def guard(fn):
        def run():
            try: fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        return run
    def begin():
        nonlocal proc
        check('credentials_skipped_quota_disabled',not pet.key_present and not pet.quota_enabled)
        check('no_observer_at_ordinary_start',pet.codex_activity.process is None)
        fake=app.STATE_ROOT/'fake_sessions';fake.mkdir(parents=True,exist_ok=True)
        (fake/'rollout-not-json.jsonl').write_text('fixture only',encoding='utf-8')
        pet.codex_activity=CodexActivityWindow(app.ROOT,app.log,sessions=fake)
        menu=TrayPopup(pet,100,100)
        check('manual_entry_in_developer_section',any(cmd=='codex-activity:open' and box[1]>392 for box,cmd in menu.items))
        menu.close()
        pet.open_codex_activity();proc=pet.codex_activity.process
        pet.open_codex_activity()
        check('fast_repeated_open_same_process',pet.codex_activity.process is proc)
        pet.root.after(1000,guard(opened))
    def opened():
        windows=pet.codex_activity.windows()
        check('packaged_native_window_visible',len(windows)==1 and proc.poll() is None)
        check('viewer_title_is_metadata', '只读元数据' in win32gui.GetWindowText(windows[0]))
        pet.hide()
        pet.root.after(300,guard(hidden))
    def hidden():
        check('pet_hide_minimizes_owned_viewer',win32gui.IsIconic(pet.codex_activity.windows()[0]))
        pet.show();pet.open_codex_activity()
        check('restore_same_process',pet.codex_activity.process is proc)
        check('restored_window_not_minimized',not win32gui.IsIconic(pet.codex_activity.windows()[0]))
        pet.codex_activity.close()
        check('close_owned_child_process',proc.poll() is not None)
        pet.open_codex_activity()
        pet.root.after(900,guard(reopened))
    def reopened():
        nonlocal proc
        proc=pet.codex_activity.process
        check('closed_viewer_can_reopen',len(pet.codex_activity.windows())==1 and proc.poll() is None)
        pet.quit()
        check('pet_exit_closes_viewer',proc.poll() is not None)
        write()
    def write():
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'metadata_results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    def finish():
        pet.quit();write()
    pet.root.after(300,guard(begin))
