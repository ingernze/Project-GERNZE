"""Windows two-stage automatic action checks with isolated accelerated timings."""
import copy
import json
import time
import traceback
import win32api
from walk_trial import position_window


def schedule(pet):
    import app
    auto=pet.autonomous;checks=[];done=False;watchdog=None;original=copy.deepcopy(auto.config)
    started=time.monotonic();observed=set();frames=set();origin=None;reading_due=None;sleep_due=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return call
    def wait(predicate,callback,timeout=12):
        deadline=time.monotonic()+timeout
        def observe():
            if predicate():callback();return
            if time.monotonic()>deadline:raise AssertionError('timed out '+callback.__name__)
            pet.root.after(10,guard(observe))
        observe()
    def weights(one,two,three):auto.config['selector']['contexts']['idle']['level_weights']={'1':one,'2':two,'3':three}
    def begin():
        nonlocal watchdog,origin,reading_due,sleep_due
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(35000,guard(lambda:check('watchdog_not_expired',False)))
        check('account_reads_disabled',not pet.key_present and not pet.quota_enabled)
        check('no_browser_or_extra_developer_window',pet.workbench.server is None and pet.walk_controls is None and pet.action_controls is None)
        check('probabilities_explicitly_pending',auto.config['selector']['probability_status']=='temporary_preview_pending_user_decision')
        check('busy_probabilities_not_finalized',auto.config['selector']['contexts']['busy']=={'enabled':False,'level_weights':None})
        check('production_wait_20_to_45_seconds',auto.config['selector']['idle_wait_ms']==[20000,45000])
        check('production_sleep_8_to_15_minutes',auto.config['random_sleep']['wait_ms']==[480000,900000])
        check('production_sleep_2_to_4_minutes',auto.config['random_sleep']['duration_ms']==[120000,240000])
        check('exactly_one_selector_timer',auto.job is not None and pet.reading_start_job is None)
        job=auto.job;auto.schedule();check('repeat_schedule_does_not_duplicate_timer',auto.job==job)
        pet._reset_idle();root=pet.root;root.update_idletasks()
        work=win32api.GetMonitorInfo(win32api.MonitorFromPoint((root.winfo_x()+128,root.winfo_y()+128),2))['Work']
        origin=((work[0]+work[2]-256)//2,(work[1]+work[3]-256)//2)
        position_window(root,*origin);root.update_idletasks()
        auto.config['selector']['idle_wait_ms']=[100,100];auto.config['random_walk']['cycles']=[1,1]
        weights(1,0,0);pet.reading_wait=[100,100]
        pet._schedule_next_frame();pet._schedule_reading();reading_due=pet.reading_due_at;sleep_due=auto.sleep_due_at
        observe_walks()
    def observe_walks():
        if pet.walk_trial.active:
            observed.add(pet.walk_trial.started);frames.add(pet.walk_trial.index)
            check_once('walk_preserves_reading_eligibility_deadline',pet.reading_due_at==reading_due)
            check_once('busy_walk_has_no_selector_or_reading_timer',auto.job is None and pet.frame_job is None and pet.reading_start_job is None)
            check_once('walk_is_automatic_and_uses_cycle_override',pet.walk_trial.automatic and pet.walk_trial.cycles==1)
        if len(observed)>=2 and not pet.walk_trial.active:
            check('all_eight_walk_frames_observed',frames==set(range(8)))
            check('actual_window_moved',abs(pet.root.winfo_x()-origin[0])+abs(pet.root.winfo_y()-origin[1])>20)
            check('eligible_reading_does_not_bypass_level_draw',pet.reading_index is None)
            weights(0,1,0)
            wait(lambda:pet.reading_index is not None,reading_started);return
        if time.monotonic()-started>5:raise AssertionError('two walking cycles not observed')
        pet.root.after(10,guard(observe_walks))
    def check_once(name,value):
        if not any(c['check']==name for c in checks):check(name,value)
        elif not value:check(name+'_regression',False)
    def reading_started():
        check('level_two_starts_reading',pet.reading_index is not None and not pet.walk_trial.active)
        check('reading_blocks_random_draws',auto.job is None)
        check('sleep_cooldown_survives_other_actions',auto.sleep_due_at==sleep_due)
        weights(0,0,1);auto.config['random_sleep']['duration_ms']=[120,120];auto.sleep_due_at=time.monotonic()-0.01
        pet._finish_reading()
        wait(lambda:pet.manual_action.active and pet.manual_action.name=='sleep',sleep_entered)
    def sleep_entered():
        check('level_three_starts_sleep',pet.manual_action.automatic and pet.manual_action.phase=='enter')
        check('sleep_entry_blocks_selector',auto.job is None and pet.reading_start_job is None)
        check('duration_not_counted_during_sleep_entry',auto.wake_job is None)
        wait(lambda:pet.manual_action.phase=='loop',sleep_holding)
    def sleep_holding():
        check('duration_starts_after_sitting_down',auto.wake_job is not None)
        job=auto.wake_job;auto.sleep_holding();check('loop_does_not_duplicate_wake',auto.wake_job==job)
        wait(lambda:pet.manual_action.finish_requested,wake_requested)
    def wake_requested():
        check('wake_preserves_loop_seam',pet.manual_action.phase=='loop' and auto.wake_job is None)
        auto.config['selector']['idle_wait_ms']=[20000,45000]
        wait(lambda:not pet.manual_action.active,sleep_finished)
    def sleep_finished():
        check('sleep_returns_through_exit_to_idle',pet.frame_job is not None and auto.job is not None and auto.wake_job is None)
        check('no_independent_reading_timer_bypasses_levels',pet.reading_start_job is None)
        event=type('E',(),{'x_root':pet.root.winfo_x()+80,'y_root':pet.root.winfo_y()+80})()
        pet._drag_begin(event);check('press_cancels_selector',auto.job is None)
        pet._drag_end(event)
        check('head_click_pauses_selector_for_headpat',pet.manual_action.name=='headpat' and auto.job is None)
        wait(lambda:not pet.manual_action.active,headpat_finished)
    def headpat_finished():
        check('headpat_completion_reschedules_selector',auto.job is not None)
        pet.start_reading();check('manual_reading_blocks_selector',auto.job is None)
        pet.start_manual_action('sleep');check('developer_sleep_stays_manual',not pet.manual_action.automatic and auto.wake_job is None)
        pet.start_manual_action('headpat');check('headpat_blocks_selector',auto.job is None)
        pet.hide()
        check('hide_clears_all_action_jobs',auto.job is None and auto.wake_job is None and auto.sleep_due_at is None and pet.grab_sway.job is None and not pet.walk_trial.active and not pet.manual_action.active and all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')))
        pet.root.after(300,guard(hidden_stays))
    def hidden_stays():
        check('hidden_does_not_restart_jobs',auto.job is None and auto.wake_job is None)
        pet.show();check('show_resumes_selector',auto.job is not None and pet.reading_start_job is None)
        pet.start_manual_action('sleep',automatic=True);wait(lambda:auto.wake_job is not None,cancel_sleep)
    def cancel_sleep():
        pet.hide();check('hide_cancels_auto_wake',auto.wake_job is None)
        pet.show();pet._reset_idle();auto.config['selector']['enabled']=False
        pet._schedule_next_frame();pet._schedule_reading()
        check('configuration_disables_all_random_actions',auto.job is None and pet.reading_start_job is None and pet.frame_job is not None)
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:
            try:pet.root.after_cancel(watchdog)
            except Exception:pass
        auto.config=original
        try:
            pet.quit();check('exit_clears_selector_and_grab_jobs',auto.job is None and auto.wake_job is None and pet.grab_sway.job is None)
            check('exit_releases_tray_and_bridge',not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'quit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'random_actions_results.json').write_text(json.dumps({'checks':checks,'passed':all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,3),'test_timing':'accelerated isolated timings; production parameters unchanged','real_account_reads':False,'five_minute_performance':'not_run'},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(100,guard(begin))
