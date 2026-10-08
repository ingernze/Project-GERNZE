"""Isolated real Tk acceptance for the second-style V11 sleep, without audio or API."""
import json,time,traceback,hashlib
from PIL import ImageTk,ImageGrab
import win32api,win32process

def schedule(pet):
    import app
    checks=[];samples=[];errors=[];events=[];done=False;jobs=[];started=time.monotonic();last=[None];seen={};phase_times={}
    action=None;origin=None
    pet.voice.emit=lambda event:events.append(event) or False
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def finish():
        nonlocal done
        if done:return
        done=True
        for job in jobs:
            try:pet.root.after_cancel(job)
            except Exception:pass
        pet.quit()
        checks.append({'check':'quit_releases_frames_and_timers','passed':not action.active and action.job is None and not action.frames and not action.photos})
        report={'passed':all(c['passed'] for c in checks) and not errors,'checks':checks,'samples':samples,'callback_errors':errors,'voice_events':events,'elapsed_s':round(time.monotonic()-started,2),'isolated':True,'cloud_api_used':False,'audio_played':False}
        app.OUTPUT.mkdir(parents=True,exist_ok=True);(app.OUTPUT/'sleep_v11_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    def guard(fn):
        def wrapped():
            try:fn()
            except Exception:checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return wrapped
    def later(ms,fn):jobs.append(pet.root.after(ms,guard(fn)))
    def callback(kind,error,tb):errors.append(str(error));finish()
    pet.root.report_callback_exception=callback
    def sample():
        samples.append({'elapsed_s':round(time.monotonic()-started,2),'working_set_mib':round(win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['WorkingSetSize']/1048576,2),'active':action.active,'phase':action.phase})
        if not done:later(500,sample)
    def poll(predicate,then,timeout=10):
        deadline=time.monotonic()+timeout
        def tick():
            if predicate():then();return
            if time.monotonic()>deadline:raise AssertionError('Timed out waiting for sleep phase')
            later(10,tick)
        tick()
    def observe(phase,then,wake=False):
        seen[phase]=[];phase_times[phase]=time.monotonic();deadline=time.monotonic()+12;requested=False;canvas_checked=False
        expected=list(range(len(action.phases[phase])));intended=sum(ms for _,ms in action.phases[phase])
        def tick():
            nonlocal requested,canvas_checked
            if action.phase!=phase:
                check(phase+'_all_frames_in_order',seen[phase]==expected)
                elapsed=(time.monotonic()-phase_times[phase])*1000
                check(phase+'_actual_duration_in_range',intended-80<=elapsed<=intended+1000)
                then();return
            if not seen[phase] or seen[phase][-1]!=action.step_index:seen[phase].append(action.step_index)
            check_canvas=action.photos[pet.scale][action.index]
            if not canvas_checked:
                check(phase+'_uses_logical_canvas',check_canvas.width()==128*pet.scale and check_canvas.height()==128*pet.scale);canvas_checked=True
            if wake and action.step_index==5 and not requested:
                requested=True;check('wake_accepted_mid_breath',action.wake());check('wake_waits_for_cycle_boundary',action.phase=='loop' and action.step_index==5)
                ImageTk.getimage(check_canvas).save(app.OUTPUT/'sleep_loop_render.png')
            if time.monotonic()>deadline:raise AssertionError('Sleep phase timeout')
            later(10,tick)
        tick()
    def begin():
        nonlocal action,origin
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        check('no_account_or_browser',not pet.key_present and not pet.quota_enabled and pet.workbench.server is None)
        check('style2_selected',pet.set_style('style2'))
        check('rest_selected',pet.set_style2_motion('rest'))
        action=pet.manual_action;pet.show();pet.set_scale(2)
        pet.root.geometry('+300+200');pet.root.update_idletasks()
        check('automatic_actions_remain_suspended',pet.autonomous.suspended)
        panel=pet.open_action_controls();pet.root.update_idletasks()
        ImageGrab.grab(bbox=(panel.winfo_x(),panel.winfo_y(),panel.winfo_x()+panel.winfo_width(),panel.winfo_y()+panel.winfo_height())).save(app.OUTPUT/'sleep_controls.png');panel.withdraw()
        origin=(pet.root.winfo_x(),pet.root.winfo_y())
        check('sleep_starts',pet.start_manual_action('sleep'))
        check('entry_once',action.phase=='enter')
        check('no_idle_or_blink_timer_during_sleep',pet.frame_job is None and not pet.idle_blink.active)
        check('native_original_frames_retained',all(im.size==(1254,1254) for im in action.frames))
        check('expected_duration_not_averaged',[sum(ms for _,ms in action.phases[k]) for k in ('enter','loop','exit')]==[3360,2880,3120])
        check('shared_window_origin',origin==(pet.root.winfo_x(),pet.root.winfo_y()))
        job=action.job;check('duplicate_trigger_ignored',not pet.start_manual_action('sleep') and action.job==job)
        sample();later(55000,lambda:check('watchdog',False));observe('enter',loop)
    def loop():
        check('entry_enters_loop',action.phase=='loop')
        pet.set_scale(5);check('scale5_keeps_action_and_origin',action.active and action.phase=='loop' and origin==(pet.root.winfo_x(),pet.root.winfo_y()))
        photo=action.photos[5][action.index];check('scale5_is_640_not_6270',photo.width()==640 and photo.height()==640)
        pet.set_scale(2);observe('loop',wake,True)
    def wake():
        check('wake_starts_at_seam',action.phase=='exit' and action.step_index==0)
        observe('exit',returned)
    def returned():
        check('wake_returns_to_idle',not action.active and pet.frame_job is not None)
        check('completion_frees_native_frames_and_display_cache',not action.frames and not action.photos)
        check('wake_voice_emitted_once',events.count('wake')==1)
        check('engine_not_loaded',pet.voice_module._backend is None)
        check('headpat_stays_unavailable',not pet.start_manual_action('headpat'))
        pet.set_style2_motion('foot_sway');check('sleep_from_foot_returns_v7_first',pet.start_manual_action('sleep') and pet.style2_motion=='rest')
        check('early_wake_request',action.wake());poll(lambda:action.phase=='exit',early_exit)
    def early_exit():
        check('early_wake_skips_loop_without_jump',action.phase=='exit' and action.step_index==0)
        poll(lambda:not action.active,interruptions)
    def interruptions():
        check('repeat_sleep_starts',pet.start_manual_action('sleep'))
        pet.hide();check('hide_cancels_action_and_cache',not action.active and action.job is None and not action.frames and not action.photos and pet.frame_job is None)
        pet.show();check('show_returns_idle',pet.frame_job is not None and not action.active)
        check('restart_after_hide',pet.start_manual_action('sleep'))
        pet.manual_action.stop();check('stop_returns_idle',not action.active and not action.frames and action.job is None)
        check('final_callback_errors_empty',not errors);finish()
    later(300,begin)
