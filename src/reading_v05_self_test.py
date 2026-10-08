"""Reading v05 base + v07 click Windows acceptance, isolated data and no account access."""
import hashlib
import json
import time
import traceback
from pathlib import Path
from PIL import ImageTk
from tray_popup import TrayPopup


def schedule(pet):
    import app
    checks=[];captured=set();done=False;watchdog=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def call():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        return call
    def phase_trace(phase,callback):
        expected=[index for index,_ in pet.reading_resource['phases'][phase]]
        seen=[]
        deadline=time.monotonic()+3
        def observe():
            if pet.reading_phase==phase:
                index=pet.reading_index
                if not seen or seen[-1]!=index:seen.append(index)
                if index not in captured:
                    captured.add(index)
                    ImageTk.getimage(pet.reading_photos[pet.scale][index]).save(
                        app.OUTPUT/f'reading_frame_{index:02}.png')
                if time.monotonic()>deadline:raise AssertionError('phase timeout '+phase)
                pet.root.after(10,guard(observe))
                return
            check(phase+'_all_manifest_frames_seen',seen==expected)
            callback()
        observe()
    def begin():
        nonlocal watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(20000,guard(lambda:check('watchdog_not_expired',False)))
        check('account_reads_disabled',not pet.key_present and not pet.quota_enabled)
        check('eleven_base_and_v07_frames_loaded',len(pet.reading_frames)==11 and pet.reading_resource['version']=='reading_v05_click_v07')
        check('production_minute_ranges_preserved',pet.reading_wait==[120000,300000] and pet.reading_duration==[120000,240000])
        check('random_wait_scheduled',pet.reading_start_job is not None)
        check('no_browser_opened_by_test',pet.workbench.server is None)
        resource=pet.reading_resource
        check('endpoints_match_current_idle',all(pet.reading_frames[i][0].tobytes()==pet.frames[0][0].tobytes() for i in (0,7)))
        raw=resource['manifest']
        check('only_click_glance_no_looped_expression',resource['phases']['glance']==[(8,180),(9,450),(10,700),(9,120),(8,200)])
        check('start_reading_returns_success',pet.start_reading())
        check('entry_suppresses_idle_and_random_wait',pet.frame_job is None and pet.reading_start_job is None)
        check('hold_timer_starts_after_entry',pet.reading_end_job is None)
        phase_trace('enter',holding)
    def holding():
        check('entry_enters_low_head_reading',pet.reading_phase=='reading' and pet.reading_index==pet.reading_resource['hold_index'])
        check('reading_hold_has_no_frame_polling',pet.reading_job is None and pet.reading_end_job is not None)
        timer=pet.reading_end_job
        pet.root.after(1100,guard(lambda:no_click(timer)))
    def no_click(timer):
        check('holding_does_not_automatically_glance',pet.reading_phase=='reading' and pet.reading_job is None)
        check('holding_keeps_original_deadline',pet.reading_end_job==timer)
        x,y=pet.root.winfo_x()+40,pet.root.winfo_y()+40
        event=type('E',(),{'x_root':x,'y_root':y})()
        pet._drag_begin(event);pet._drag_end(event)
        check('real_click_starts_glance',pet.reading_phase=='glance' and pet.reading_job is not None)
        job=pet.reading_job
        pet.glance_from_reading()
        check('repeat_click_does_not_duplicate_glance',pet.reading_job==job)
        pet.set_scale(3)
        check('scale_keeps_current_reading_pose',str(pet.label.cget('image'))==str(pet.reading_photos[3][pet.reading_index]))
        pet.set_scale(2)
        phase_trace('glance',lambda:returned(timer))
    def returned(timer):
        check('glance_returns_to_book',pet.reading_phase=='reading' and pet.reading_job is None)
        check('click_does_not_extend_reading_minutes',pet.reading_end_job==timer)
        menu=TrayPopup(pet,pet.root.winfo_screenwidth()-10,pet.root.winfo_screenheight()-10)
        idx=next(i for i,(_,cmd) in enumerate(menu.items) if cmd=='reading:finish')
        menu.activate(idx)
        pet.root.after(60,guard(manual_exit))
    def manual_exit():
        check('tray_manual_end_starts_put_away',pet.reading_phase=='exit' and pet.reading_end_job is None)
        # The first exit frame has 140ms, still visible after command delivery.
        phase_trace('exit',exited)
    def exited():
        check('put_away_returns_to_idle',pet.reading_index is None and pet.reading_phase is None and pet.frame_job is not None)
        check('put_away_reschedules_random_wait',pet.reading_start_job is not None)
        pet.start_reading()
        first=pet.reading_job
        pet.start_reading()
        check('restart_replaces_entry_timer',pet.reading_job!=first and pet.reading_phase=='enter')
        pet.hide()
        check('hide_cancels_all_reading_timers',all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')) and pet.reading_phase is None)
        pet.show()
        pet.start_reading()
        pet._finish_reading()
        check('early_manual_end_waits_for_entry',pet.reading_phase=='enter' and pet.reading_finish_requested)
        pet.root.after(1650,guard(after_early_end))
    def after_early_end():
        check('early_end_eventually_returns_idle',pet.reading_index is None and pet.frame_job is not None)
        pet.start_reading()
        pet.root.after(800,guard(drag))
    def drag():
        check('reading_ready_before_drag',pet.reading_phase=='reading')
        x,y=pet.root.winfo_x()+40,pet.root.winfo_y()+40
        event=type('E',(),{'x_root':x,'y_root':y})()
        pet._drag_begin(event);event.x_root+=20;pet._drag_move(event)
        check('drag_cancels_reading',pet.reading_phase is None and pet.reading_index is None and pet.reading_end_job is None)
        pet._drag_end(event)
        check('drag_release_resumes_idle_and_wait',pet.frame_job is not None and pet.reading_start_job is not None)
        pet.start_reading();pet.start_walk('left',moving=False)
        check('walking_replaces_reading',pet.reading_index is None and pet.reading_job is None and pet.walk_trial.active)
        pet.start_reading()
        check('reading_replaces_walking',not pet.walk_trial.active and pet.walk_trial.job is None)
        pet._reset_idle()
        pet.reading_wait=[50,50];pet.reading_duration=[80,80]
        pet._schedule_reading()
        pet.root.after(65,guard(random_started))
    def random_started():
        check('random_callback_starts_entry',pet.reading_phase=='enter')
        pet.reading_wait=[120000,300000]
        pet.test_reading_deadline=time.monotonic()+3
        pet.root.after(200,guard(duration_ended))
    def duration_ended():
        if pet.reading_phase is not None and time.monotonic()<pet.test_reading_deadline:
            pet.root.after(25,guard(duration_ended))
            return
        check('hold_duration_closes_book_then_idle',pet.reading_phase is None and pet.frame_job is not None and pet.reading_start_job is not None)
        pet.reading_duration=[120000,240000]
        saved=pet.reading_frames
        pet.reading_frames=[]
        check('missing_reading_falls_back_without_crash',not pet.start_reading() and pet.reading_index is None and pet.frame_job is not None)
        pet.reading_frames=saved
        frames=pet.reading_resource['manifest']['frames']
        check('all_base_and_v07_original_bytes_preserved',all(
            hashlib.sha256((app.READING_DIR/e['file']).read_bytes()).hexdigest()==e['sha256'] for e in frames))
        a=pet.reading_frames[9][0];b=pet.reading_frames[10][0]
        changed=[(i%128,i//128) for i,(x,y) in enumerate(zip(a.getdata(),b.getdata())) if x!=y]
        check('v07_smile_changes_only_115_face_pixels',len(changed)==115 and all(y<76 for x,y in changed))
        check('v07_alpha_changes_only_inside_expression',all(x[3]==y[3] for i,(x,y) in enumerate(zip(a.getdata(),b.getdata())) if (i%128,i//128) not in changed))
        pet.start_reading()
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:
            pet.quit()
            check('exit_cancels_reading_and_walk_jobs',all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')) and pet.walk_trial.job is None)
            check('exit_releases_native_tray',not pet.tray.is_alive())
            check('exit_releases_native_bridge',pet.bridge.released)
        except Exception:
            checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'reading_v07_results.json').write_text(json.dumps({
            'resource_version':pet.reading_resource['version'],'checks':checks,'passed':all(c['passed'] for c in checks),
            'user_visual_acceptance':'pending','five_minute_performance':'not_run'},ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(100,guard(begin))
