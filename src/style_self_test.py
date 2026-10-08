"""Isolated live Tk checks for native rest and foot-sway style2 art."""
import json,traceback,time
from PIL import ImageGrab

def schedule(pet):
    import app
    checks=[];done=False;watchdog=None;seen=[];old_job=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return call
    def capture(name):
        pet.root.update_idletasks();x,y=pet.root.winfo_x(),pet.root.winfo_y();size=128*pet.scale
        ImageGrab.grab(bbox=(x,y,x+size,y+size)).save(app.OUTPUT/name)
    def begin():
        nonlocal watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(24000,guard(lambda:check('watchdog',False)))
        check('isolated_no_accounts',not pet.key_present and not pet.quota_enabled)
        check('original_at_start',pet.character_style=='original' and len(pet.reading_frames)>0)
        check('switch_style2',pet.set_style('style2'))
        check('rest_native_canvas',len(pet.frames)==16 and pet.frames[0][0].size==(1254,1254))
        check('rest_2seconds',sum(ms for im,ms in pet.frames)==2000 and pet.manifest['loop'])
        check('no_cross_style_actions',not pet.reading_frames and pet.grab_sway.resource['renderer']=='native_grab' and not pet.start_manual_action('headpat') and not pet.start_manual_action('sleep'))
        check('manual_preview_only',pet.autonomous.suspended)
        panel=pet.open_style_controls();check('selector_single_window',pet.open_style_controls() is panel)
        capture('style2_rest.png')
        pet.root.after(350,guard(rest_progress))
    def rest_progress():
        check('rest_animation_advances',pet.frame_index>0 and pet.frame_job is not None)
        for scale in (1,2,3,4,5):
            pet.set_scale(scale);pet.root.update_idletasks()
            check('display_scale_'+str(scale),pet.photos[scale][0].width()==128*scale)
            bounds=pet._coast_bounds();x,y=pet.root.winfo_x(),pet.root.winfo_y()
            check('scale_inside_screen_'+str(scale),bounds.left<=x<=bounds.right and bounds.top<=y<=bounds.bottom)
            if scale in (4,5):capture('style2_rest_'+str(scale)+'x.png')
        pet.set_scale(2)
        check('switch_foot',pet.set_style2_motion('foot_sway'))
        check('foot_finite_steps_14poses',len(pet.frames)==18*pet._sway_cycles+9 and len({id(im) for im,ms in pet.frames})==14)
        check('foot_duration_with_transitions',sum(ms for im,ms in pet.frames)==1760+2500*pet._sway_cycles)
        check('fixed_source_anchor',pet.manifest['source_foot_anchor']==[668,1227])
        capture('style2_foot.png')
        seen.append(pet.frame_index)
        for wait in (500,1100,1700,2300):pet.root.after(wait,guard(lambda:seen.append(pet.frame_index)))
        pet.root.after(2700,guard(foot_progress))
    def foot_progress():
        check('foot_moves_and_loops',len(set(seen))>=4 and pet.frame_index<len(pet.frames) and pet.frame_job is not None)
        panel=pet.open_walk_controls()
        check('all_unmatched_walks_disabled',all(b.cget('state')=='disabled' for b in panel.buttons.values()))
        check('no_old_walk_fallback',not pet.start_walk('up') and pet.character_style=='style2')
        old=pet.frames[0][0]
        check('bad_motion_rejected',not pet.set_style2_motion('nonexistent'))
        check('bad_motion_retains_images',pet.frames[0][0] is old)
        check('rest_switch',pet.set_style2_motion('rest'));pet._cancel_frame();pet._schedule_next_frame();check('rest_restored',len(pet.frames)==16)
        jobs=pet.root.tk.call('after','info');check('single_animation_job',pet.frame_job in jobs)
        pet.hide();check('hide_cancels_timer',pet.frame_job is None and pet.autonomous.job is None)
        pet.show();check('show_resumes_timer',pet.frame_job is not None)
        check('switch_original',pet.set_style('original'))
        check('original_walk_buttons_restored',all(b.cget('state')=='normal' for b in panel.buttons.values()))
        check('original_reading_and_grab_restore',len(pet.reading_frames)>0 and pet.grab_sway.resource is not None)
        check('original_walk_usable',pet.start_walk('left',moving=False,cycles=1))
        check('switch_during_walk',pet.set_style('style2') and not pet.walk_trial.active and pet.walk_trial.job is None)
        before=pet.frames[0][0]
        check('invalid_style_rejected',not pet.set_style('nonexistent'))
        check('invalid_style_retains_images',pet.frames[0][0] is before)
        check('restore_original',pet.set_style('original'))
        check('original_headpat_usable',pet.start_manual_action('headpat'))
        check('cancel_headpat_on_style_switch',pet.set_style('style2') and not pet.manual_action.active and pet.manual_action.job is None)
        check('final_original',pet.set_style('original'))
        check('style_persistence',json.loads(app.SETTINGS.read_text(encoding='utf-8'))['character_style']=='original')
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:
            pet.quit();check('exit_cleanup',not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'style_results.json').write_text(json.dumps({'checks':checks,'passed':all(c['passed'] for c in checks),'visual_acceptance':'pending user'},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(300,guard(begin))
