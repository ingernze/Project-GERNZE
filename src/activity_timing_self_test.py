"""Isolated Tk + HTTP acceptance with accelerated sleep; production values unchanged."""
import json
import time
import threading
import traceback
from pathlib import Path

def schedule(pet):
    import app
    from activity_timing import DEFAULTS
    checks=[];errors=[];events=[];ended=False;watchdog=None;started=time.monotonic();server=None
    pet.voice.emit=lambda event:events.append(event)
    pet.root.report_callback_exception=lambda kind,error,tb:errors.append(''.join(traceback.format_exception(kind,error,tb)))
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def wrapped():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return wrapped
    def wait(predicate,next_step,timeout=12):
        deadline=time.monotonic()+timeout
        def step():
            if ended:return
            if predicate():next_step();return
            if time.monotonic()>deadline:raise AssertionError('timed out '+next_step.__name__)
            pet.root.after(20,guard(step))
        step()
    def http(command,params,next_step):
        reply=[]
        def request():
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=7)
            try:
                conn.request('POST','/api/call',json.dumps({'command':command,'params':params}),
                    {'Content-Type':'application/json','Authorization':'Bearer '+server.token,'Origin':server.origin})
                response=conn.getresponse();reply.append((response.status,json.loads(response.read())))
            except Exception:reply.append((0,{'error':traceback.format_exc()}))
            finally:conn.close()
        threading.Thread(target=request,daemon=True).start()
        wait(lambda:bool(reply),lambda:next_step(*reply[0]),timeout=8)
    def begin():
        nonlocal watchdog,server
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(42000,guard(lambda:check('watchdog',False)))
        check('no_account_reads',not pet.key_present and not pet.quota_enabled)
        check('defaults',pet.settings['activity_timing']==DEFAULTS)
        check('style2_available',pet.set_style('style2'))
        check('original_selector_stays_suspended',pet.autonomous.suspended)
        server=pet.workbench.open(launch_browser=False)
        http('behavior.get',{},got)
    def got(status,body):
        check('authenticated_get',status==200 and body['result']['available'])
        check('both_art_resources_available',body['result']['sleep_available'] and body['result']['blink_available'])
        http('behavior.set',{'settings':{**DEFAULTS,'sleep_min_s':0}},invalid)
    def invalid(status,body):
        check('invalid_change_rejected',status==400 and pet.settings['activity_timing']==DEFAULTS)
        http('behavior.set',{'settings':{**DEFAULTS,'blink_min_s':6,'blink_max_s':8,'sleep_min_s':1,'sleep_max_s':1}},saved)
    def saved(status,body):
        check('http_save_received_on_tk_thread',status==200 and body['result']['persisted'])
        check('blink_live_settings',pet.idle_blink.lottery.interval==(6,8))
        check('restart_reads_saved_settings',app.load_settings()['activity_timing']==pet.settings['activity_timing'])
        auto=pet.autonomous.sleep;auto.suspended=False;auto.due=time.monotonic()+.15
        pet._schedule_reading();job=auto.job;auto.schedule()
        check('one_sleep_timer',job is not None and job==auto.job)
        wait(lambda:pet.manual_action.active,entered)
    def entered():
        check('automatic_sleep_entry',pet.manual_action.automatic and pet.manual_action.phase=='enter')
        check('duration_not_counted_in_entry',pet.autonomous.sleep.wake_job is None)
        check('blink_not_active_while_sleeping',not pet.idle_blink.active)
        wait(lambda:pet.manual_action.phase=='loop',holding)
    def holding():
        check('duration_timer_after_sitting',pet.autonomous.sleep.wake_job is not None)
        wake=pet.autonomous.sleep.wake_job;pet.autonomous.sleep.sleep_holding()
        check('no_duplicate_wake_timer',wake==pet.autonomous.sleep.wake_job)
        prefs={**pet.settings['activity_timing'],'sleep_enabled':False,'sleep_min_s':30,'sleep_max_s':600}
        http('behavior.set',{'settings':prefs},lambda status,body:disabled(status,body,wake))
    def disabled(status,body,wake):
        check('disable_future_sleep_saved',status==200 and body['result']['persisted'])
        check('disable_keeps_current_wake',pet.autonomous.sleep.wake_job==wake)
        wait(lambda:pet.manual_action.finish_requested,waking)
    def waking():
        check('timer_requests_natural_wake',pet.manual_action.phase=='loop' and pet.autonomous.sleep.wake_job is None)
        wait(lambda:not pet.manual_action.active,finished)
    def finished():
        check('returns_to_idle',pet.frame_job is not None and not pet.manual_action.frames)
        check('no_auto_sleep_after_disabled',pet.autonomous.sleep.job is None)
        check('sleep_wake_voice_once',events.count('sleep')==1 and events.count('wake')==1)
        check('manual_sleep_starts',pet.start_manual_action('sleep'))
        check('manual_sleep_no_duration',pet.autonomous.sleep.wake_job is None)
        pet.manual_action.stop()
        prefs={**DEFAULTS,'sleep_enabled':True}
        http('behavior.set',{'settings':prefs},resumed)
    def resumed(status,body):
        check('restore_defaults_saved',status==200 and pet.settings['activity_timing']==DEFAULTS)
        auto=pet.autonomous.sleep;check('saving_resumes_idle_schedule',auto.job is not None)
        pet.hide();check('hide_removes_all_timers',auto.job is None and auto.wake_job is None and auto.due is None)
        pet.show();check('show_resumes_timer',auto.job is not None)
        pet.set_style2_motion('foot_sway');check('foot_preview_not_interrupted',auto.job is None)
        pet.set_style2_motion('rest')
        wait(lambda:pet.style2_motion=='rest',restored)
    def restored():
        check('return_to_rest_reschedules',pet.autonomous.sleep.job is not None)
        check('callbacks_without_errors',not errors)
        finish()
    def finish():
        nonlocal ended
        if ended:return
        ended=True
        if watchdog is not None:
            try:pet.root.after_cancel(watchdog)
            except Exception:pass
        auto=pet.autonomous.sleep
        try:
            pet.quit();check('quit_releases_sleep_timers',auto.job is None and auto.wake_job is None)
        except Exception:checks.append({'check':'quit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'activity_timing_results.json').write_text(json.dumps({'passed':all(c['passed'] for c in checks) and not errors,'checks':checks,'callback_errors':errors,'elapsed_s':round(time.monotonic()-started,2),'isolated':True,'cloud_api_used':False,'audio_played':False,'test_duration_s':1,'production_default_duration_s':[30,600]},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(100,guard(begin))
