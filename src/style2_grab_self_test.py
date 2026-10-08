"""Isolated real Windows/Tk host checks; no physical mouse or account reads."""
import json,time,traceback
from PIL import ImageGrab
from walk_trial import position_window

def schedule(pet):
    import app
    checks=[];done=False;watchdog=None;motion=None;event=None;index=0;samples=[];last_pointer=None
    def check(name,value):
        checks.append(dict(check=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append(dict(check='unexpected_error',passed=False,error=traceback.format_exc()));finish()
        return call
    def emit(seq,x,y):
        widget=pet.root if seq!='<ButtonPress-1>' else pet.label
        widget.event_generate(seq,x=x-widget.winfo_rootx(),y=y-widget.winfo_rooty(),rootx=x,rooty=y,state=256 if seq=='<Motion>' else 0,when='now')
        pet.root.update_idletasks()
    def capture(name):
        pet.root.update_idletasks();x,y=pet.root.winfo_x(),pet.root.winfo_y();size=128*pet.scale
        ImageGrab.grab(bbox=(x,y,x+size,y+size),all_screens=True).save(app.OUTPUT/(name+'.png'))
    def anchored(pointer):
        return (pet.root.winfo_x()+pet.drag_start[0],pet.root.winfo_y()+pet.drag_start[1])==pointer
    def begin():
        nonlocal watchdog,motion,last_pointer
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(25000,guard(lambda:check('watchdog',False)))
        check('isolated_accounts_disabled',not pet.key_present and not pet.quota_enabled)
        if pet.character_style!='style2':check('style2_switch',pet.set_style('style2'))
        pet.set_style2_motion('rest');motion=pet.grab_sway
        check('23_native_poses_loaded',len(motion.images)==23 and motion.resource['renderer']=='native_grab')
        check('no_idle_drag_timer',not motion.active and motion.job is None)
        for scale in (1,2,3,4,5):
            pet.set_scale(scale);position_window(pet.root,500,200);pet.root.update_idletasks()
            x,y=500+70*scale,200+20*scale
            emit('<ButtonPress-1>',x,y)
            check('capture_on_press_'+str(scale),pet.root.grab_current() is pet.root)
            emit('<Motion>',x+2,y+2)
            check('small_motion_stays_click_'+str(scale),not motion.active)
            pointer=(x+380,y+50);emit('<Motion>',*pointer)
            check('fast_jump_capture_and_anchor_'+str(scale),motion.active and pet.root.grab_current() is pet.root and anchored(pointer))
            for entry in motion.resource['poses']:
                motion.motion.velocity=1 if entry['pose'].endswith('_RETURN') else -1 if entry['normalized_swing_proxy']<0 else 1
                motion.pose=None;motion.display(entry['normalized_swing_proxy']*35);pet.root.update_idletasks()
                check('native_anchor_'+str(scale)+'_'+entry['pose'],motion.pose==entry['pose'] and anchored(pointer) and motion.photos[scale][motion.pose].width()==128*scale)
            pointer=(x-250,y+60);emit('<Motion>',*pointer)
            check('fast_reverse_anchor_'+str(scale),anchored(pointer))
            emit('<ButtonRelease-1>',*pointer)
            check('release_cleans_capture_and_timer_'+str(scale),pet.drag_start is None and pet.root.grab_current() is None and not motion.active and motion.job is None)
            check('release_restores_idle_'+str(scale),str(pet.label.cget('image'))==str(pet.photos[scale][0]))
            pet._cancel_coast()
        pet.set_scale(4);position_window(pet.root,650,250);pet.root.update_idletasks()
        last_pointer=(930,330);emit('<ButtonPress-1>',*last_pointer)
        pet.root.after(33,guard(move))
    def move():
        nonlocal index,last_pointer
        index+=1;last_pointer=(930+index*16,330)
        emit('<Motion>',*last_pointer);samples.append(motion.motion.angle)
        check('pointer_anchor_during_motion_'+str(index),anchored(last_pointer))
        if index<10:pet.root.after(33,guard(move));return
        check('right_drag_lags_left',motion.motion.angle<-6 and motion.pose.startswith('L_'))
        capture('风格二_向右拖动身体滞后')
        wait_for_quiet(time.monotonic()+6)
    def wait_for_quiet(deadline):
        samples.append(motion.motion.angle)
        check('stationary_pointer_anchor',anchored(last_pointer))
        if motion.job is None:
            check('rebound_then_settle',max(samples)>1 and motion.motion.quiet() and motion.pose=='CENTER')
            capture('风格二_停稳悬挂')
            emit('<ButtonRelease-1>',*last_pointer);pet._cancel_coast()
            emit('<ButtonPress-1>',900,330);emit('<Motion>',950,350);pet.hide()
            check('hide_releases_everything',pet.root.grab_current() is None and not motion.active and motion.job is None)
            pet.show();check('show_restores_idle',not motion.active and motion.job is None)
            emit('<ButtonPress-1>',900,330);emit('<Motion>',950,350);pet.set_scale(2)
            check('scale_change_cancels_drag',pet.root.grab_current() is None and not motion.active and motion.job is None)
            check('original_switch_restores_pixel_grab',pet.set_style('original') and len(pet.grab_sway.images)==3)
            check('style2_switch_reloads_native_grab',pet.set_style('style2') and len(pet.grab_sway.images)==23)
            finish();return
        if time.monotonic()>deadline:raise AssertionError('spring did not settle')
        pet.root.after(35,guard(lambda:wait_for_quiet(deadline)))
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:pet.quit()
        except Exception:checks.append(dict(check='quit',passed=False,error=traceback.format_exc()))
        (app.OUTPUT/'style2_grab_results.json').write_text(json.dumps(dict(passed=all(c['passed'] for c in checks),checks=checks,input='generated real Tk bindings; physical mouse acceptance pending user',art_status='trial pending user',account_reads=False),ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(150,guard(begin))
