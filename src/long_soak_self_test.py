"""Isolated actual Tk soak: animation cycles, hidden release and repeated HTTP service."""
import json,time,traceback,win32api,win32process,socket
def schedule(pet):
    import app
    from activity_timing import DEFAULTS
    rows=[];checks=[];errors=[];jobs=set();done=False;started=time.monotonic();last=time.monotonic();cpu=time.process_time();cycles=0;phase='warming';warm=None
    pet.voice.emit=lambda event:False
    pet.root.report_callback_exception=lambda kind,error,tb:errors.append(''.join(traceback.format_exception(kind,error,tb)))
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def later(ms,fn):
        key=[None]
        def wrapped():
            jobs.discard(key[0])
            try:fn()
            except Exception:checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        key[0]=pet.root.after(ms,wrapped);jobs.add(key[0]);return key[0]
    def sample():
        nonlocal last,cpu
        now=time.monotonic();used=time.process_time();mem=win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
        rows.append({'elapsed_s':round(now-started,3),'phase':phase,'rss_mb':round(mem['WorkingSetSize']/1048576,3),'private_mb':round(mem['PagefileUsage']/1048576,3),'cpu_one_core':round(100*(used-cpu)/(now-last),3),'tk_after_jobs':len(pet.root.tk.call('after','info'))})
        last=now;cpu=used
        if not done:later(5000,sample)
    def begin():
        nonlocal phase
        check('isolated_no_credentials',not pet.key_present and not pet.quota_enabled)
        pet.set_style('style2');pet.show()
        prefs={**DEFAULTS,'sleep_enabled':False}
        pet.apply_activity_settings(prefs) if hasattr(pet,'apply_activity_settings') else None
        pet.autonomous.sleep.suspended=True;pet.autonomous.sleep.cancel()
        phase='active_cycles';later(5000,sample);cycle()
    def cycle():
        nonlocal cycles,warm
        if time.monotonic()-started>=360:hidden();return
        if pet.manual_action.active:pet.manual_action.stop()
        pet._reset_idle();check('sleep_cycle_'+str(cycles+1),pet.start_manual_action('sleep'))
        cycles+=1
        later(6500,lambda:pet.manual_action.wake())
        if cycles==3:warm=win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['PagefileUsage']/1048576
        later(15000,cycle)
    def hidden():
        nonlocal phase
        pet.hide();phase='hidden'
        check('hidden_frame_timer_released',pet.frame_job is None)
        check('hidden_sleep_timers_released',pet.autonomous.sleep.job is None and pet.autonomous.sleep.wake_job is None)
        later(180000,workbenches)
    def workbenches():
        nonlocal phase
        phase='workbench_cycles'
        for index in range(5):
            server=pet.workbench.open(launch_browser=False)
            check('singleton_server_'+str(index),pet.workbench.open(launch_browser=False) is server)
            port=server.server_port
            pet.workbench.close_service()
            check('thread_release_'+str(index),not pet.workbench.worker.is_alive())
            sock=socket.socket();sock.settimeout(.5)
            try:check('socket_release_'+str(index),sock.connect_ex(('127.0.0.1',port))!=0)
            finally:sock.close()
        check('no_callback_errors',not errors)
        current=win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['PagefileUsage']/1048576
        check('bounded_private_memory_after_warmup',warm is not None and current-warm<64)
        check('animation_at_least_six_minutes',cycles>=20)
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        for job in list(jobs):
            try:pet.root.after_cancel(job)
            except Exception:pass
        try:pet.quit()
        except Exception:errors.append(traceback.format_exc())
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'long_soak_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks) and not errors,'duration_s':time.monotonic()-started,'sleep_cycles':cycles,'rows':rows,'checks':checks,'errors':errors,'scope':'Actual Tk CPU/RAM soak. Silent playback; no GPU synthesis or user mouse input.'},ensure_ascii=False,indent=2),encoding='utf8')
    later(400,begin)
