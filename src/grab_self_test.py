"""Exercise Windows host callbacks and actual PNG display, without account reads."""
import json
import time
import traceback
from PIL import ImageGrab
import win32api
from walk_trial import position_window


def schedule(pet):
    import app
    checks=[];done=False;started=time.monotonic();motion=pet.grab_sway;watchdog=None;index=0;poses=set();samples=[]
    event=None;origin=None;pointer=None;direction=1
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return call
    def make_event(x,y):return type('E',(),{'x_root':x,'y_root':y})()
    def capture(name):
        pet.root.update_idletasks();x=pet.root.winfo_x();y=pet.root.winfo_y();size=128*pet.scale
        ImageGrab.grab(bbox=(x,y,x+size,y+size),all_screens=True).save(app.OUTPUT/(name+'.png'))
    def routing_checks():
        # Exercise real Tk widget bindings, not just direct callback calls.
        def emit(widget,sequence,x,y,state=0):
            widget.event_generate(sequence,x=x-widget.winfo_rootx(),y=y-widget.winfo_rooty(),rootx=x,rooty=y,state=state,when='now')
            pet.root.update_idletasks()
        pet._reset_idle()
        for scale in (1,2,3):
            pet.set_scale(scale);pet.root.update_idletasks()
            ox,oy=pet.root.winfo_x(),pet.root.winfo_y()
            x,y=ox+64*scale,oy+16*scale
            emit(pet.label,'<ButtonPress-1>',x,y)
            check('routing_capture_on_press_scale_'+str(scale),pet.root.grab_current() is pet.root)
            emit(pet.root,'<Motion>',x+3,y+2,256)
            check('routing_small_motion_remains_click_scale_'+str(scale),not pet.drag_moved and not motion.active)
            emit(pet.root,'<Motion>',x+600,y-240,256)
            check('routing_fast_first_jump_received_scale_'+str(scale),pet.drag_moved and motion.active and (pet.root.winfo_x(),pet.root.winfo_y())==(ox+600,oy-240))
            check('routing_capture_survives_animation_reset_scale_'+str(scale),pet.root.grab_current() is pet.root)
            emit(pet.root,'<Motion>',x-450,y+180,256)
            check('routing_fast_reverse_received_scale_'+str(scale),(pet.root.winfo_x(),pet.root.winfo_y())==(ox-450,oy+180))
            emit(pet.root,'<ButtonRelease-1>',x-500,y+200)
            check('routing_release_uses_latest_coordinate_scale_'+str(scale),(pet.root.winfo_x(),pet.root.winfo_y())==tuple(round(v) for v in pet._coast_bounds().clamp(ox-500,oy+200)))
            check('routing_outside_release_clears_capture_scale_'+str(scale),pet.drag_start is None and pet.root.grab_current() is None and motion.job is None and not motion.active)
            emit(pet.label,'<ButtonPress-1>',pet.root.winfo_x()+64*scale,pet.root.winfo_y()+16*scale)
            pet.hide()
            check('routing_hide_even_before_threshold_releases_capture_scale_'+str(scale),pet.drag_start is None and pet.root.grab_current() is None)
            pet.show()
        pet.set_scale(2);pet._reset_idle()
        # A descendant motion must bubble once to the toplevel handler.
        x,y=pet.root.winfo_x()+128,pet.root.winfo_y()+32
        emit(pet.label,'<ButtonPress-1>',x,y)
        emit(pet.label,'<Motion>',x+30,y+10,256)
        check('routing_label_motion_still_bubbles',pet.drag_moved and motion.active)
        emit(pet.label,'<ButtonRelease-1>',x+30,y+10)
        check('routing_label_release_still_bubbles',pet.drag_start is None and pet.root.grab_current() is None)

    def begin():
        nonlocal watchdog,origin,pointer,event
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(15000,guard(lambda:check('watchdog_not_expired',False)))
        check('account_reads_disabled',not pet.key_present and not pet.quota_enabled)
        check('original_three_pose_preview_not_claimed_as_24',len(motion.images)==3 and motion.resource['status']=='integrated_preview_art_not_accepted')
        check('watch_is_baked_into_supplied_png',motion.resource['watch']=='baked_in_original_png_no_separate_layer')
        check('no_idle_grab_timer',motion.job is None and not motion.active)
        routing_checks()
        pet._reset_idle();pet.root.update_idletasks()
        work=win32api.GetMonitorInfo(win32api.MonitorFromPoint((pet.root.winfo_x()+128,pet.root.winfo_y()+128),2))['Work']
        origin=((work[0]+work[2]-256)//2-140,(work[1]+work[3]-256)//2)
        position_window(pet.root,*origin);pet.root.update_idletasks()
        pointer=(origin[0]+128,origin[1]+32);event=make_event(*pointer)
        pet._drag_begin(event)
        check('click_alone_keeps_existing_pose',not motion.active)
        pet._drag_end(event)
        pet._drag_begin(event)
        move()
    def move():
        nonlocal index,event
        index+=1;event=make_event(pointer[0]+direction*index*24,pointer[1])
        pet._drag_move(event);poses.add(motion.pose);samples.append(motion.motion.angle)
        if index==10:
            capture('drag_right_lag' if direction==1 else 'drag_left_lag')
            check('drag_right_body_lags_left' if direction==1 else 'drag_left_body_lags_right',motion.motion.angle*direction<-6 and motion.pose==('left' if direction==1 else 'right'))
            check('actual_window_follows_pointer_right' if direction==1 else 'actual_window_follows_pointer_left',abs(pet.root.winfo_x()-(origin[0]+direction*240))<=1)
            check('drag_stops_other_animations_right' if direction==1 else 'drag_stops_other_animations_left',pet.frame_job is None and pet.reading_job is None and not pet.walk_trial.active and not pet.manual_action.active)
            wait_for_rebound(time.monotonic()+2);return
        pet.root.after(33,guard(move))
    def wait_for_rebound(deadline):
        poses.add(motion.pose);samples.append(motion.motion.angle)
        if motion.motion.angle*direction>2.5:
            check('right_drag_rebounds_while_button_held' if direction==1 else 'left_drag_rebounds_while_button_held',pet.drag_start is not None and motion.active and motion.pose==('right' if direction==1 else 'left'))
            capture('right_drag_rebound' if direction==1 else 'left_drag_rebound')
            wait_for_quiet(time.monotonic()+4);return
        if time.monotonic()>deadline:raise AssertionError('visible rebound missing '+str({'angle':motion.motion.angle,'active':motion.active,'job':motion.job,'samples':samples[-30:],'max':max(samples)}))
        pet.root.after(15,guard(lambda:wait_for_rebound(deadline)))
    def wait_for_quiet(deadline):
        if motion.job is None:
            check('still_hold_quiets_and_stops_timer_right' if direction==1 else 'still_hold_quiets_and_stops_timer_left',motion.active and motion.pose=='center' and motion.motion.quiet())
            pet._drag_end(event)
            check('release_returns_exact_idle_right' if direction==1 else 'release_returns_exact_idle_left',not motion.active and motion.job is None and str(pet.label.cget('image'))==str(pet.photos[pet.scale][0]))
            if direction==1:reverse();return
            after_both();return
        if time.monotonic()>deadline:raise AssertionError('grab timer never quiets')
        pet.root.after(20,guard(lambda:wait_for_quiet(deadline)))
    def reverse():
        nonlocal direction,index,origin,pointer,event
        direction=-1;index=0;origin=(pet.root.winfo_x(),pet.root.winfo_y());pointer=(origin[0]+128,origin[1]+32)
        event=make_event(*pointer);pet._drag_begin(event);pet.root.after(33,guard(move))
    def after_both():
        check('all_original_poses_rendered',poses=={'center','left','right'})
        pet.start_reading();check('reading_can_start_after_release',pet.reading_index is not None)
        start=make_event(pet.root.winfo_x()+128,pet.root.winfo_y()+32);pet._drag_begin(start)
        pet._drag_move(make_event(start.x_root+100,start.y_root))
        check('grab_cancels_reading',pet.reading_index is None and motion.active)
        pet.hide()
        check('hide_cancels_grab_and_global_capture',not motion.active and motion.job is None and pet.root.grab_current() is None)
        pet.root.after(200,guard(hidden))
    def hidden():
        check('hidden_has_no_grab_callbacks',motion.job is None)
        pet.show();check('show_returns_idle_without_grab',not motion.active and motion.job is None)
        for scale in (1,2,3):
            pet.set_scale(scale)
            start=make_event(pet.root.winfo_x()+64*scale,pet.root.winfo_y()+16*scale)
            pet._drag_begin(start);pet._drag_move(make_event(start.x_root+20,start.y_root))
            check('shared_anchor_and_canvas_at_scale_'+str(scale),motion.active and motion.resource['anchor']==[64,16] and motion.photos[scale]['center'].width()==128*scale)
            pet._drag_end(start)
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:
            try:pet.root.after_cancel(watchdog)
            except Exception:pass
        try:
            pet.quit();check('exit_clears_grab_timer',motion.job is None and not motion.active)
            check('exit_releases_tray_and_bridge',not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'quit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'grab_results.json').write_text(json.dumps({'checks':checks,'passed':all(c['passed'] for c in checks),'elapsed_seconds':round(time.monotonic()-started,3),'input':'generated Tk widget events through label and toplevel bindings plus simulated spring callbacks; no physical mouse input','real_account_reads':False,'visual_acceptance':'pending_user','art_limit':'3 candidate poses; missing authored 24-frame sequence','five_minute_performance':'not_run'},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(100,guard(begin))
