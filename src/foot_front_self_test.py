"""Real Tk finite motion and interruption acceptance; isolated and silent."""
import json,time,traceback
def schedule(pet):
    import app
    from foot_sway import sequence
    checks=[];rows=[];done=False;started=0
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def finish(error=None):
        nonlocal done
        if done:return
        done=True
        if error:checks.append({'check':'unexpected_error','passed':False,'error':error})
        pet.quit();app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'foot_front_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks,'observed':rows,'silent':True},ensure_ascii=False,indent=2),encoding='utf8')
    def guard(fn):
        def wrapped():
            try:fn()
            except Exception:finish(traceback.format_exc())
        return wrapped
    def interrupted():
        check('sway_restarts',pet.set_style2_motion('foot_sway',cycles=3))
        pet.frame_index=8
        check('rest_request_is_deferred',pet.set_style2_motion('rest') and pet.style2_motion=='foot_sway')
        pet.set_scale(4)
        check('resizing_keeps_current_motion',pet.style2_motion=='foot_sway' and pet.photos[4][0].width()==512)
        pet.hide()
        check('hide_restores_static_and_stops_sway',pet._sway_exit_target is None and pet.style2_motion=='rest' and pet.frame_job is None)
        pet.show();pet.set_scale(2)
        check('show_rearms_idle_frames',pet.frame_job is not None)
        pet.set_style2_motion('foot_sway',cycles=1)
        check('sleep_loads_from_sway',pet.start_manual_action('sleep'))
        check('sleep_has_exclusive_timer',pet.manual_action.active and pet.frame_job is None and pet.style2_motion=='rest')
        pet.manual_action.stop()
        pet._schedule_next_frame();pet._schedule_reading()
        pet.set_style2_motion('foot_sway',cycles=1);pet._reset_idle()
        check('drag_reset_restores_idle',pet.style2_motion=='rest' and pet._sway_exit_target is None)
        pet.set_style2_motion('foot_sway',cycles=1);pet.set_style('original')
        check('skin_change_cancels_sway',not pet._sway_entry and pet._sway_exit_target is None and pet.character_style=='original')
        pet.set_style('style2');auto=pet.autonomous.sway;auto.suspended=False
        auto.schedule();job=auto.job
        check('auto_arms_exactly_one_timer',job is not None)
        auto.schedule();check('no_duplicate_auto_timer',auto.job==job)
        auto.cancel_idle();auto._run(time.monotonic())
        check('automatic_timer_starts_sway',pet.style2_motion=='foot_sway' and 1<=pet._sway_cycles<=3)
        check('sleep_never_arms_during_sway',not pet.autonomous.sleep.available())
        pet.hide();check('hide_cancels_auto_timer',auto.job is None)
        finish()
    def early_exit():
        check('early_exit_starts_three_cycles',pet.set_style2_motion('foot_sway',cycles=3))
        begin=time.monotonic()
        def request():
            pet.set_style2_motion('rest')
            check('exit_requested_during_loop_is_deferred',pet.style2_motion=='foot_sway')
            poll()
        seen=[]
        def poll():
            seen.append((pet.style2_motion,pet.manifest['frames'][pet.frame_index]['file']))
            if pet.style2_motion=='rest':
                check('early_exit_after_one_cycle',time.monotonic()-begin<6)
                files=[f for motion,f in seen if motion=='foot_sway']
                check('early_exit_plays_landing_and_transition',all(f in files for f in ('F10.png','B04.png','T02.png','T01.png','B01.png')))
                interrupted();return
            if time.monotonic()-begin>7:raise AssertionError('early exit did not finish')
            pet.root.after(25,guard(poll))
        pet.root.after(1000,guard(request))
    def sample():
        elapsed=time.monotonic()-started
        rows.append({'elapsed_s':round(elapsed,3),'motion':pet.style2_motion,'file':pet.manifest['frames'][pet.frame_index]['file']})
        if pet.style2_motion=='rest':
            files=[x['file'] for x in rows if x['motion']=='foot_sway']
            compressed=[f for i,f in enumerate(files) if i==0 or files[i-1]!=f]
            expected=['B01.png','T01.png','T02.png','B04.png']+[f['file'] for f in sequence(pet.style_asset_paths['idle']/'foot_sway',3)[0]['frames']][4:]
            check('entry_three_loops_landing_exit_in_order',compressed==expected)
            check('natural_return_to_original_standing',pet.manifest['frames'][0]['file']=='F00.png' and pet._sway_exit_target is None)
            check('completion_keeps_one_idle_animation',pet.frame_job is not None)
            check('source_keeps_approved_sharpness',all(im.size==(1254,1254) for im,ms in pet.frames))
            early_exit();return
        if pet.idle_blink.active:raise AssertionError('blink inside sway')
        if elapsed>16:raise AssertionError('finite action did not complete')
        pet.root.after(25,guard(sample))
    def begin():
        nonlocal started
        pet.voice.emit=lambda event:False
        check('fresh_install_defaults_to_illustration',pet.character_style=='style2')
        check('style2_loads',pet.set_style('style2'));pet.show()
        check('foot_loads',pet.set_style2_motion('foot_sway',cycles=3))
        check('starts_with_accepted_standing_transition',pet.manifest['frames'][0]['file']=='B01.png')
        check('duration_three_cycles',sum(ms for im,ms in pet.frames)==9260)
        check('repeated_frames_share_display_photos',len({id(p) for p in pet.photos[pet.scale]})==14)
        started=time.monotonic();sample()
    pet.root.after(200,guard(begin))
