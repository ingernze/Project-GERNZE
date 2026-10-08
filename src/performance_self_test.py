"""Opt-in frozen EXE baseline: >=300s static + >=300s hidden, no account access."""
import csv
import json
import os
import subprocess
import sys
import time
import traceback
import win32api
import win32con
import win32gui
import win32process


def schedule(pet):
    import app
    from tray_win32 import SHOW,HIDE,EXIT,CALLBACK
    jobs=set();checks=[];phases=[];rows=[];latencies=[];done=False;duplicate=None
    phase=None;phase_start=0;cpu_start=0;last_time=0;last_cpu=0
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def later(ms,fn):
        holder=[None]
        def run():
            jobs.discard(holder[0])
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        holder[0]=pet.root.after(ms,run);jobs.add(holder[0]);return holder[0]
    def memory():
        return win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['WorkingSetSize']/1048576
    def animation_jobs_clear():
        return all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')) and all(x.job is None for x in (pet.manual_action,pet.walk_trial,pet.grab_sway,pet.autonomous)) and pet.autonomous.wake_job is None and pet.coast.pending is None and not pet.coast.motion.frame.active
    def sample():
        nonlocal last_time,last_cpu
        now=time.monotonic();cpu=time.process_time()
        extra=set(pet.root.tk.call('after','info'))-jobs
        rows.append({'phase':phase,'phase_elapsed_s':round(now-phase_start,3),'cpu_percent_one_core':round(100*(cpu-last_cpu)/max(.001,now-last_time),4),'working_set_mb':round(memory(),3),'animation_jobs_clear':animation_jobs_clear(),'unexpected_after_jobs':len(extra)})
        last_time=now;last_cpu=cpu
        if phase is not None:later(5000,sample)
    def start_phase(name):
        nonlocal phase,phase_start,cpu_start,last_time,last_cpu
        for j in list(jobs):pet.root.after_cancel(j)
        jobs.clear()
        phase=name;phase_start=time.monotonic();cpu_start=time.process_time();last_time=phase_start;last_cpu=cpu_start
        app.log('benchmark_phase_started',phase=name,duration_s=300)
        later(5000,sample)
        later(300100,end_phase)
    def end_phase():
        nonlocal phase
        now=time.monotonic();cpu=time.process_time();name=phase
        data=[r for r in rows if r['phase']==name]
        duration=now-phase_start
        phases.append({'phase':name,'duration_s':round(duration,3),'cpu_seconds':round(cpu-cpu_start,6),'mean_cpu_percent_one_core':round(100*(cpu-cpu_start)/duration,4),'peak_sample_cpu_percent_one_core':max((r['cpu_percent_one_core'] for r in data),default=0),'mean_working_set_mb':round(sum(r['working_set_mb'] for r in data)/max(1,len(data)),3),'peak_working_set_mb':max((r['working_set_mb'] for r in data),default=0),'sample_count':len(data),'all_animation_jobs_clear':all(r['animation_jobs_clear'] for r in data),'max_unexpected_after_jobs':max((r['unexpected_after_jobs'] for r in data),default=0)})
        check(name+'_at_least_five_minutes',duration>=300)
        check(name+'_no_animation_or_other_after_jobs',animation_jobs_clear() and all(r['animation_jobs_clear'] and r['unexpected_after_jobs']==0 for r in data))
        for j in list(jobs):pet.root.after_cancel(j)
        jobs.clear();phase=None
        if name=='static_visible':command(HIDE,False,lambda:start_phase('hidden_tray'))
        else:command(SHOW,True,after_hidden)
    def command(cmd,visible,callback):
        started=time.monotonic();win32gui.PostMessage(pet.tray.hwnd,win32con.WM_COMMAND,cmd,0)
        def observe():
            if pet.visible==visible:
                elapsed=1000*(time.monotonic()-started);latencies.append({'command':cmd,'milliseconds':round(elapsed,3)})
                check('tray_command_response_'+str(len(latencies)),elapsed<1000)
                callback()
            elif time.monotonic()-started>3:check('tray_command_timeout',False)
            else:later(1,observe)
        later(1,observe)
    def begin():
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        check('frozen_exe',getattr(sys,'frozen',False))
        check('credentials_network_browser_disabled',not pet.key_present and not pet.quota_enabled and pet.workbench.server is None)
        pet.show();pet._reset_idle();pet.root.update_idletasks()
        check('static_timers_clear',animation_jobs_clear())
        start_phase('static_visible')
    def after_hidden():
        # Test the native transparent window region without injecting mouse input.
        pet.root.update_idletasks();x,y=pet.root.winfo_x(),pet.root.winfo_y()
        own=win32gui.GetAncestor(pet.root.winfo_id(),win32con.GA_ROOT)
        opaque=[(xx,yy) for yy in range(45,70) for xx in range(45,80) if pet.frames[0][0].getpixel((xx,yy))[3]>250][0]
        hit=win32gui.WindowFromPoint((x+opaque[0]*pet.scale,y+opaque[1]*pet.scale))
        check('opaque_character_hit_test',win32gui.GetAncestor(hit,win32con.GA_ROOT)==own)
        corner=win32gui.WindowFromPoint((x+1,y+1))
        check('transparent_corner_click_through',win32gui.GetAncestor(corner,win32con.GA_ROOT)!=own)
        command(HIDE,False,repeat_launch)
    def repeat_launch():
        nonlocal duplicate
        duplicate=subprocess.Popen([sys.executable,'--benchmark'],env=os.environ.copy())
        started=time.monotonic()
        def observe():
            if duplicate.poll() is not None and pet.visible:
                check('repeat_launch_exits_and_restores_existing',duplicate.returncode==0)
                show_menu()
            elif time.monotonic()-started>10:check('repeat_launch_timeout',False)
            else:later(25,observe)
        later(25,observe)
    def show_menu():
        win32gui.PostMessage(pet.tray.hwnd,CALLBACK,0,win32con.WM_RBUTTONUP)
        later(100,menu_opened)
    def menu_opened():
        check('native_tray_right_click_opens_popup',pet.tray_popup is not None and pet.tray_popup.winfo_exists())
        pet.tray_popup.close()
        # Observe actual tray EXIT dispatch and cleanup through the overridden quit.
        original=pet.quit
        def checked_quit():
            for j in list(jobs):pet.root.after_cancel(j)
            jobs.clear()
            original()
            check('tray_exit_cleanup',not pet.tray.is_alive() and pet.bridge.released and animation_jobs_clear() and pet.modules.closed)
            finish(already_quit=True)
        pet.quit=checked_quit
        win32gui.PostMessage(pet.tray.hwnd,win32con.WM_COMMAND,EXIT,0)
        later(3000,lambda:check('tray_exit_timeout',False))
    def finish(already_quit=False):
        nonlocal done
        if done:return
        done=True
        for j in list(jobs):
            try:pet.root.after_cancel(j)
            except Exception:pass
        jobs.clear()
        if not already_quit:
            try:pet.quit()
            except Exception:pass
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        result={'passed':all(c['passed'] for c in checks),'exe':sys.executable,'phases':phases,'tray_latencies':latencies,'checks':checks,'sampling':'5 seconds, benchmark flag only; sampling overhead included','scope':'No credentials read; quota disabled, workbench not opened; static/hidden baseline, not random-animation workload','physical_mouse':'untouched'}
        (app.OUTPUT/'performance_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        if rows:
            with (app.OUTPUT/'performance.csv').open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        print(json.dumps(result,ensure_ascii=False))
    later(250,begin)
