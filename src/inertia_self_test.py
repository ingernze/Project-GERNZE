"""Windows inertia acceptance through existing Tk mouse bindings, isolated data."""
import json
import math
import time
import traceback
import win32api
import win32con
import win32gui
import win32process
from walk_trial import position_window


def schedule(pet):
    import app
    checks=[];trace=[];done=False;watchdog=None;started=time.monotonic();cpu_started=time.process_time()
    coast=pet.coast
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return call
    def after(ms,fn):pet.root.after(ms,guard(fn))
    def emit(kind,x,y,label=False):
        widget=pet.label if label else pet.root
        widget.event_generate(kind,x=x-widget.winfo_rootx(),y=y-widget.winfo_rooty(),rootx=x,rooty=y,when='now')
        pet.root.update_idletasks()
    def reset(edge=False):
        pet._reset_idle();pet.set_scale(2);pet.show()
        bounds=pet._coast_bounds()
        x=bounds.right-20 if edge else max(bounds.left,bounds.left+(bounds.right-bounds.left)//2-100)
        y=bounds.top+(bounds.bottom-bounds.top)//2
        position_window(pet.root,x,y);pet.root.update_idletasks()
        return x,y
    def flick(callback,dx=20,dy=0,wait_ms=20,pause_ms=0,edge=False):
        origin=reset(edge)
        pointer=(origin[0]+128,origin[1]+100)
        emit('<ButtonPress-1>',*pointer,label=True)
        check('press_captures_no_idle_coast_task_'+str(len(checks)),pet.root.grab_current() is pet.root and coast.pending is None)
        def step(i=1):
            x,y=pointer[0]+dx*i,pointer[1]+dy*i
            emit('<B1-Motion>',x,y)
            if i<6:after(wait_ms,lambda:step(i+1))
            else:after(pause_ms,lambda:release(x,y))
        def release(x,y):
            emit('<ButtonRelease-1>',x,y)
            callback(origin,(pet.root.winfo_x(),pet.root.winfo_y()))
        after(wait_ms,step)
    def begin():
        nonlocal watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(25000,guard(lambda:check('watchdog_not_expired',False)))
        check('no_account_browser',not pet.key_present and not pet.quota_enabled and pet.workbench.server is None)
        check('no_coast_task_initially',coast.pending is None and not coast.motion.frame.active)
        flick(fast_released)
    def fast_released(origin,released):
        check('fast_release_starts_real_coast',coast.motion.frame.active and coast.pending is not None)
        check('release_ends_mouse_capture',pet.drag_start is None and pet.root.grab_current() is None)
        check('coast_blocks_random_reading_idle',pet.autonomous.job is None and pet.reading_start_job is None and pet.frame_job is None)
        velocity=coast.motion.frame.vx
        trace.append({'stage':'release','t':time.monotonic(),'xy':released,'velocity':velocity})
        pet._schedule_next_frame();pet._schedule_reading()
        check('scheduling_cannot_race_coast',pet.frame_job is None and pet.reading_start_job is None)
        after(180,lambda:fast_moved(origin,released,velocity))
    def fast_moved(origin,released,velocity):
        xy=(pet.root.winfo_x(),pet.root.winfo_y());trace.append({'stage':'coasting','t':time.monotonic(),'xy':xy,'velocity':coast.motion.frame.vx})
        check('window_moves_beyond_release',xy[0]>released[0]+10 and abs(xy[1]-released[1])<=1)
        check('velocity_decays',0<coast.motion.frame.vx<velocity)
        after(1100,lambda:stopped(released))
    def stopped(released):
        check('coast_stops_cancels_only_chain',not coast.motion.frame.active and coast.pending is None)
        check('stop_keeps_final_position_and_restores_idle',pet.root.winfo_x()>released[0] and pet.frame_index==0 and pet.frame_job is not None)
        check('stop_saves_final_coordinates',abs(pet.settings['x']-pet.root.winfo_x())<=1 and abs(pet.settings['y']-pet.root.winfo_y())<=1)
        flick(slow_released,dx=2,wait_ms=100)
    def slow_released(origin,released):
        check('slow_drag_does_not_launch',not coast.motion.frame.active and coast.pending is None)
        flick(paused_released,pause_ms=130)
    def paused_released(origin,released):
        check('pause_before_release_erases_throw',not coast.motion.frame.active and coast.pending is None)
        flick(diagonal_released,dx=20,dy=12)
    def diagonal_released(origin,released):
        check('diagonal_launch_has_both_axes',coast.motion.frame.vx>0 and coast.motion.frame.vy>0)
        after(100,lambda:regrab(released))
    def regrab(released):
        xy=(pet.root.winfo_x(),pet.root.winfo_y())
        check('diagonal_actual_window_moves_both_axes',xy[0]>released[0] and xy[1]>released[1])
        emit('<ButtonPress-1>',xy[0]+128,xy[1]+100,label=True)
        check('regrab_cancels_previous_chain',coast.pending is None and not coast.motion.frame.active and pet.root.grab_current() is pet.root)
        emit('<ButtonRelease-1>',xy[0]+128,xy[1]+100)
        check('regrab_is_not_accidental_headpat',not pet.manual_action.active)
        after(100,lambda:regrab_stays(xy))
    def regrab_stays(xy):
        check('stale_coast_cannot_move_regrabbed_window',(pet.root.winfo_x(),pet.root.winfo_y())==xy)
        flick(edge_released,dx=20,dy=12,edge=True)
    def edge_released(origin,released):
        b=pet._coast_bounds()
        check('edge_release_clamps_full_window',pet.root.winfo_x()==round(b.right) and coast.motion.frame.vx==0)
        after(140,lambda:edge_slides(released))
    def edge_slides(released):
        b=pet._coast_bounds()
        check('edge_preserves_along_wall_motion',pet.root.winfo_x()==round(b.right) and pet.root.winfo_y()>released[1])
        flick(hide_released)
    def hide_released(origin,released):
        check('hide_test_starts_coast',coast.pending is not None)
        pet.hide();xy=(pet.root.winfo_x(),pet.root.winfo_y())
        check('hide_cancels_coast_and_all_animation',coast.pending is None and not coast.motion.frame.active and pet.grab_sway.job is None and pet.autonomous.job is None and pet.frame_job is None)
        after(150,lambda:hidden_stays(xy))
    def hidden_stays(xy):
        check('hidden_position_stays_and_coast_does_not_restart',(pet.root.winfo_x(),pet.root.winfo_y())==xy and coast.pending is None)
        pet.show();flick(scale_released)
    def scale_released(origin,released):
        pet.set_scale(3)
        check('scale_change_cancels_coast',coast.pending is None and not coast.motion.frame.active)
        check('scale_change_resumes_idle_and_read_wait',pet.frame_job is not None and pet.reading_start_job is not None)
        pet._schedule_next_frame();pet._schedule_reading()
        flick(action_released)
    def action_released(origin,released):
        pet.start_reading()
        check('new_action_cancels_coast',coast.pending is None and not coast.motion.frame.active and pet.reading_phase=='enter')
        flick(layout_released)
    def layout_released(origin,released):
        pet._desktop_environment_changed()
        check('display_change_cancels_position_motion',coast.pending is None and not coast.motion.frame.active)
        flick(exit_released)
    def exit_released(origin,released):
        check('exit_test_has_pending_coast',coast.pending is not None)
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        elapsed=time.monotonic()-started;cpu=time.process_time()-cpu_started
        mem=win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['WorkingSetSize']/1048576
        monitors=[list(win32api.GetMonitorInfo(m[0])['Work']) for m in win32api.EnumDisplayMonitors()]
        try:
            pet.quit()
            check('exit_closes_coast_capture_tray_bridge',coast.closed and coast.pending is None and not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        result={'checks':checks,'passed':all(c['passed'] for c in checks),'elapsed_s':round(elapsed,3),'mean_cpu_percent_one_core_including_checks':round(cpu/elapsed*100,4),'working_set_mb':round(mem,3),'position_trace':trace,'monitors_work':monitors,'negative_monitor_real_test':'not performed; negative-coordinate math unit tests separate','input':'Tk existing mouse bindings, physical pointer untouched','hand_feel_acceptance':'pending user review'}
        (app.OUTPUT/'inertia_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    after(100,begin)
