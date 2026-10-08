"""Native Tk acceptance for optional blink and interruption cleanup."""
import json,traceback,time

def schedule(pet):
    import app
    checks=[];seen=[];starts=[];done=False
    def check(name,passed):
        checks.append({'check':name,'passed':bool(passed)})
        if not passed:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return call
    def force():
        pet._cancel_frame();pet.frame_index=0
        pet.idle_blink.lottery.due=0
        pet.idle_blink.lottery.rng=type('R',(),{'uniform':lambda s,a,b:2,'random':lambda s:0})()
        pet.idle_blink.on_cycle_boundary()
        pet.label.configure(image=pet.photos[pet.scale][0]);pet._schedule_next_frame()
    def begin():
        check('no_cloud_accounts',not pet.key_present and not pet.quota_enabled)
        pet.show();check('style2',pet.set_style('style2'))
        check('ordinary_rest_16_steps_eyes_open',len(pet.frames)==16 and not pet.idle_blink.active)
        check('normal_2seconds',sum(ms for im,ms in pet.frames)==2000)
        pet._cancel_frame()
        original=pet._next_frame
        def tick():
            before=pet.idle_blink.active
            original()
            if pet.idle_blink.active and not before:starts.append(time.monotonic())
            seen.append({'active':pet.idle_blink.active,'index':pet.frame_index,'eye':pet.manifest['frames'][pet.frame_index].get('eye_state','original_open')})
        pet._next_frame=tick
        force();starts.append(time.monotonic());check('single_blink_20_steps',pet.idle_blink.active and len(pet.frames)==20)
        pet.root.after(6500,guard(after_cycle))
    def after_cycle():
        check('next_blink_arrives_within_3_to_5_seconds',len(starts)>=2 and 3<=starts[1]-starts[0]<=5)
        check('closed_and_half_states_seen',{'half_close','closed','half_open','near_open'}<=set(x['eye'] for x in seen))
        check('blink_returns_to_original_16_steps',not pet.idle_blink.active and len(pet.frames)==16 and pet.manifest['motion']=='rest')
        check('normal_animation_keeps_running',pet.frame_job is not None)
        check('completion_does_not_add_another_wait',pet.idle_blink.lottery.due<time.monotonic()+2.5)
        force();pet.set_scale(4)
        check('scale_change_cancels_blink',not pet.idle_blink.active and len(pet.frames)==16 and pet.photos[4][0].width()==512)
        pet.set_scale(2);force();pet.hide()
        check('hide_cancels_blink_and_timer',not pet.idle_blink.active and len(pet.frames)==16 and pet.frame_job is None)
        pet.show();check('show_resumes_normal',pet.frame_job is not None and not pet.idle_blink.active)
        force();check('foot_switch',pet.set_style2_motion('foot_sway'))
        check('foot_not_blinking',not pet.idle_blink.active and not pet.idle_blink.eligible() and len(pet.frames)==18)
        check('return_rest',pet.set_style2_motion('rest'));force()
        check('original_switch',pet.set_style('original'))
        check('original_not_blinking',not pet.idle_blink.active and not pet.idle_blink.eligible() and len(pet.reading_frames)>0)
        check('style2_again',pet.set_style('style2'))
        check('style2_resources_reusable',pet.idle_blink.eligible() and len(pet.frames)==16)
        force();pet._reset_idle()
        check('reset_cancels_blink',not pet.idle_blink.active and len(pet.frames)==16)
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        try:pet.quit();check('exit_cleanup',not pet.tray.is_alive() and pet.bridge.released)
        except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'blink_results.json').write_text(json.dumps({'passed':all(c['passed'] for c in checks),'checks':checks,'observed_frames':seen,'blink_start_intervals':[b-a for a,b in zip(starts,starts[1:])]},ensure_ascii=False,indent=2),encoding='utf8')
    pet.root.after(250,guard(begin))
