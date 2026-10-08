"""Windows binding acceptance for single head click, with isolated test data."""
import json
import traceback
from PIL import ImageTk


def schedule(pet):
    import app
    checks=[];finished=False;watchdog=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        return call
    def event(kind,x,y,target=None):
        target=target or pet.label
        target.event_generate(kind,x=int(x*pet.scale),y=int(y*pet.scale),
            rootx=pet.root.winfo_x()+int(x*pet.scale),rooty=pet.root.winfo_y()+int(y*pet.scale),when='now')
    def click(x=64,y=60):
        event('<ButtonPress-1>',x,y)
        event('<ButtonRelease-1>',x,y)
    def begin():
        nonlocal watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(18000,guard(lambda:check('watchdog',False)))
        check('no_account_or_browser',not pet.key_present and not pet.quota_enabled and pet.workbench.server is None)
        check('startup_scale_two',pet.scale==2)
        for scale in (1,2,3):
            pet._reset_idle();pet.set_scale(scale);pet.root.update_idletasks()
            click();check(f'head_binding_starts_at_scale_{scale}',pet.manual_action.active and pet.manual_action.name=='headpat')
            job=pet.manual_action.job;click();check(f'no_repeat_restart_at_scale_{scale}',pet.manual_action.job==job)
            check(f'capture_released_at_scale_{scale}',pet.root.grab_current() is None)
            pet._reset_idle();click(64,96);check(f'body_not_head_at_scale_{scale}',not pet.manual_action.active)
            click(0,0);check(f'transparent_corner_not_head_at_scale_{scale}',not pet.manual_action.active)
        pet.set_scale(2);click()
        pet.root.after(1350,guard(after_headpat))
    def after_headpat():
        check('headpat_finishes_and_returns_exact_idle',not pet.manual_action.active and pet.frame_index==0)
        pet._reset_idle();event('<ButtonPress-1>',64,60)
        x,y=pet.root.winfo_x(),pet.root.winfo_y()
        pet.root.event_generate('<B1-Motion>',rootx=x+128+400,rooty=y+120-100,when='now')
        check('fast_drag_keeps_capture',pet.root.grab_current() is pet.root and pet.drag_moved)
        pet.root.event_generate('<ButtonRelease-1>',rootx=x+128+400,rooty=y+120-100,when='now')
        pet.root.update_idletasks()
        check('fast_drag_moves_and_does_not_headpat',abs(pet.root.winfo_x()-pet._coast_bounds().clamp(x+400,y-100)[0])<=1 and not pet.manual_action.active)
        check('fast_drag_releases_capture',pet.root.grab_current() is None and pet.drag_start is None)
        event('<ButtonPress-1>',64,60)
        x=pet.root.winfo_x()
        pet.root.event_generate('<ButtonRelease-1>',rootx=x+128+30,rooty=pet.root.winfo_y()+120,when='now')
        pet.root.update_idletasks()
        check('release_jump_without_motion_is_drag',abs(pet.root.winfo_x()-pet._coast_bounds().clamp(x+30,pet.root.winfo_y())[0])<=1 and not pet.manual_action.active)
        pet.start_manual_action('sleep');click()
        check('sleep_not_interrupted_by_head_click',pet.manual_action.name=='sleep')
        pet._reset_idle();pet.start_walk('left',moving=False);click()
        check('walk_not_interrupted_by_head_click',pet.walk_trial.active and not pet.manual_action.active)
        pet.start_reading();pet.root.after(850,guard(reading))
    def reading():
        check('reading_holds',pet.reading_phase=='reading')
        deadline=pet.reading_end_job;click()
        check('reading_click_uses_v07_not_headpat',pet.reading_phase=='glance' and not pet.manual_action.active)
        pet.test_deadline=deadline
        pet.root.after(1800,guard(after_reading))
    def after_reading():
        check('reading_response_returns_to_book',pet.reading_phase=='reading' and pet.reading_end_job==pet.test_deadline)
        pet._reset_idle();click();pet.hide()
        check('hide_cancels_headpat_and_capture',pet.manual_action.job is None and not pet.manual_action.active and pet.root.grab_current() is None)
        check('hide_cancels_idle_reading_random',pet.frame_job is None and pet.reading_start_job is None and pet.autonomous.job is None)
        pet.show();click();finish()
    def finish():
        nonlocal finished
        if finished:return
        finished=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:
            pet.quit()
            check('exit_cleans_action_tray_bridge',pet.manual_action.job is None and not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'head_click_results.json').write_text(json.dumps({'checks':checks,'passed':all(x['passed'] for x in checks),'input_method':'Tk actual label/root bindings; physical pointer untouched','visual_acceptance':'pending'},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(100,guard(begin))
