"""Actual Windows actions acceptance. No account reads or physical pointer movement."""
import hashlib
import ctypes
import json
import time
import traceback
from pathlib import Path
from PIL import ImageGrab,ImageTk
from tray_popup import TrayPopup

def schedule(pet):
    import app
    checks=[];done=False;watchdog=None;frames_saved=set();started=time.monotonic()
    action=pet.manual_action
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            if done:return
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        return call
    def capture():
        key=(action.name,action.phase,action.step_index)
        if action.active and key not in frames_saved:
            frames_saved.add(key)
            ImageTk.getimage(action.photos[pet.scale][action.index]).save(
                app.OUTPUT/f'{action.name}_{action.phase}_{action.step_index:02}.png')
    def observe_phase(phase,callback,loop_wake=False):
        seen=[];deadline=time.monotonic()+8
        expected=list(range(len(action.phases[phase])))
        def observe():
            if action.phase!=phase:
                check(phase+'_ordered_full_sequence',seen==expected)
                callback();return
            capture()
            if not seen or seen[-1]!=action.step_index:seen.append(action.step_index)
            if loop_wake and action.step_index==1 and not action.finish_requested:
                event=type('E',(),{'x_root':pet.root.winfo_x()+70,'y_root':pet.root.winfo_y()+70})()
                pet._drag_begin(event);pet._drag_end(event)
                check('click_does_not_wake_sleep',action.phase=='loop' and not action.finish_requested)
                check('manual_wake_accepted',action.wake())
                check('wake_does_not_jump_mid_loop',action.phase=='loop' and action.step_index==1)
            if time.monotonic()>deadline:raise AssertionError('phase timeout '+phase)
            pet.root.after(10,guard(observe))
        observe()
    def wait(predicate,callback,timeout=6):
        deadline=time.monotonic()+timeout
        def poll():
            if predicate():callback();return
            if time.monotonic()>deadline:raise AssertionError('wait timeout')
            pet.root.after(10,guard(poll))
        poll()
    def begin():
        nonlocal watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(55000,guard(lambda:check('watchdog',False)))
        check('test_has_no_account_reads',not pet.key_present and not pet.quota_enabled)
        check('test_did_not_open_browser',pet.workbench.server is None)
        check('actions_not_auto_started',not action.active and action.job is None)
        menu=TrayPopup(pet,pet.root.winfo_screenwidth()-10,pet.root.winfo_screenheight()-10)
        check('tray_exposes_manual_controls',any(cmd=='actions:open' for _,cmd in menu.items))
        menu.close()
        panel=pet.open_action_controls()
        panel.update()
        ctypes.windll.dwmapi.DwmFlush()
        x,y,w,h=panel.winfo_x(),panel.winfo_y(),panel.winfo_width(),panel.winfo_height()
        ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(app.OUTPUT/'manual_controls_windows.png')
        panel.withdraw()  # Prevent incidental physical clicks from replacing the acceptance action.
        origin=(pet.root.winfo_x(),pet.root.winfo_y())
        check('sleep_started',pet.start_manual_action('sleep'))
        check('sleep_stops_blink_and_reading_wait',pet.frame_job is None and pet.reading_start_job is None)
        job=action.job
        check('duplicate_sleep_is_ignored',not pet.start_manual_action('sleep') and job==action.job)
        check('sleep_manifest_durations',all(sum(ms for _,ms in action.phases[k])==v for k,v in [('enter',2400),('loop',4200),('exit',2420)]))
        check('start_does_not_reposition_pet',origin==(pet.root.winfo_x(),pet.root.winfo_y()))
        observe_phase('enter',loop)
    def loop():
        check('entry_reaches_sleep_loop',action.phase=='loop' and action.step_index==0)
        pet.set_scale(3)
        check('scaling_preserves_sleep_pose',str(pet.label.cget('image'))==str(action.photos[3][action.index]))
        pet.set_scale(2)
        observe_phase('loop',exit_phase,True)
    def exit_phase():
        check('manual_wake_enters_exit_at_matching_seam',action.phase=='exit' and action.step_index==0)
        observe_phase('exit',sleep_finished)
    def sleep_finished():
        check('wake_restores_idle',not action.active and action.job is None and pet.frame_job is not None)
        check('wake_restores_reading_wait',pet.reading_start_job is not None)
        check('headpat_starts',pet.start_manual_action('headpat'))
        check('headpat_skips_zero_initial_endpoint',action.phase=='play' and action.step_index==1)
        check('headpat_duration_1160',sum(ms for _,ms in action.phases['play'])==1160)
        job=action.job
        check('duplicate_headpat_ignored',not pet.start_manual_action('headpat') and action.job==job)
        pet.set_scale(1)
        check('headpat_scaling_keeps_pose',str(pet.label.cget('image'))==str(action.photos[1][action.index]))
        pet.set_scale(2)
        seen=[];deadline=time.monotonic()+3
        def nod():
            if not action.active:
                check('headpat_all_positive_frames_seen',seen==list(range(1,8)))
                check('headpat_single_play_returns_idle',action.job is None and pet.frame_job is not None)
                interactions();return
            check_name=action.name
            if check_name!='headpat':raise AssertionError('unexpected external action '+str(check_name))
            capture()
            if not seen or seen[-1]!=action.step_index:seen.append(action.step_index)
            if time.monotonic()>deadline:raise AssertionError('headpat timeout')
            pet.root.after(10,guard(nod))
        nod()
    def interactions():
        pet.start_manual_action('sleep');job=action.job
        check('early_wake_request_accepted',action.wake())
        check('early_wake_waits_for_entry',action.phase=='enter' and action.job==job)
        wait(lambda:action.phase=='exit',early_exit)
    def early_exit():
        check('early_wake_skips_sleep_loop',action.phase=='exit')
        wait(lambda:not action.active,other_actions)
    def other_actions():
        pet.start_manual_action('headpat')
        check('reading_cancels_headpat',pet.start_reading() and not action.active and action.job is None)
        check('sleep_cancels_reading',pet.start_manual_action('sleep') and pet.reading_index is None and pet.reading_end_job is None)
        check('walk_cancels_sleep',pet.start_walk('left',moving=False) and not action.active and action.job is None)
        check('headpat_cancels_walk',pet.start_manual_action('headpat') and not pet.walk_trial.active)
        event=type('E',(),{'x_root':pet.root.winfo_x()+80,'y_root':pet.root.winfo_y()+80})()
        pet._drag_begin(event);event.x_root+=12;pet._drag_move(event);pet._drag_end(event)
        check('drag_cancels_action',not action.active and action.job is None)
        pet.start_manual_action('sleep');pet.hide()
        check('hidden_has_no_action_or_other_animation_timer',not action.active and action.job is None and pet.frame_job is None and pet.reading_job is None and pet.reading_start_job is None)
        check('hidden_controls_withdrawn',pet.action_controls.state()=='withdrawn')
        pet.root.after(200,guard(hidden_stays))
    def hidden_stays():
        check('hidden_action_does_not_restart',not action.active and action.job is None)
        pet.show()
        check('show_restores_idle_not_sleep',not action.active and pet.frame_job is not None)
        pet.open_action_controls();pet.start_manual_action('sleep')
        pet.action_controls.close()
        check('closing_control_panel_cancels_timer',not action.active and action.job is None)
        old=action.asset_dir
        action.asset_dir=app.OUTPUT/'missing_assets'
        check('missing_resource_falls_back',not pet.start_manual_action('sleep') and not action.active and pet.frame_job is not None)
        action.asset_dir=old
        pet.start_manual_action('headpat')
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:
            try:pet.root.after_cancel(watchdog)
            except Exception:pass
        try:
            pet.quit()
            checks.extend([{'check':'quit_clears_action_timer','passed':not action.active and action.job is None},
                           {'check':'quit_stops_tray_thread','passed':not pet.tray.is_alive()},
                           {'check':'quit_closes_workbench','passed':pet.workbench.server is None}])
        except Exception:
            checks.append({'check':'quit_error','passed':False,'error':traceback.format_exc()})
        result={'checks':checks,'elapsed_seconds':round(time.monotonic()-started,3),
                'art_status':'integrated_manual_trial_visual_review_pending',
                'real_account_reads':False,'auto_sleep':False,'headpat_gesture':False}
        (app.OUTPUT/'manual_actions_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(200,guard(begin))
