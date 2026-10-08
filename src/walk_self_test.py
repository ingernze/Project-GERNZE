"""Windows walking acceptance: isolated storage, no credentials or network quota."""
import hashlib
import json
import time
import traceback
from pathlib import Path

import tkinter as tk
import win32api
import win32con
import win32gui
from PIL import Image, ImageGrab, ImageTk
from tray_popup import TrayPopup
from walk_trial import bounded_position


def schedule(pet):
    import app
    checks, queue = [], [(d, m) for m in (False, True) for d in ('right', 'left', 'up', 'down')]
    observations = []
    panel = None
    completed = False
    watchdog = None
    def check(name, value):
        checks.append({'check': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    def guard(fn):
        def call():
            try:
                fn()
            except Exception:
                checks.append({'check': 'unexpected_error', 'passed': False,
                               'error': traceback.format_exc()})
                finish()
        return call
    def place(x, y):
        pet.root.update_idletasks()
        hwnd = win32gui.GetAncestor(pet.root.winfo_id(), win32con.GA_ROOT)
        win32gui.SetWindowPos(hwnd, 0, x, y, 0, 0,
                             win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        pet.root.update_idletasks()
    def begin():
        nonlocal panel, watchdog
        app.OUTPUT.mkdir(parents=True, exist_ok=True)
        check('credentials_and_quota_disabled', not pet.key_present and not pet.quota_enabled)
        check('no_workbench_opened_by_walk_test', pet.workbench.server is None)
        pet._cancel_reading()
        menu = TrayPopup(pet, pet.root.winfo_screenwidth()-10, pet.root.winfo_screenheight()-10)
        index = next(i for i, (_, cmd) in enumerate(menu.items) if cmd == 'walk:open')
        menu.activate(index)
        pet.root.after(100, guard(opened))
        watchdog = pet.root.after(60000, guard(lambda: check('watchdog_did_not_expire', False)))
    def opened():
        nonlocal panel
        panel = pet.walk_controls
        check('tray_menu_opens_four_direction_controls', panel is not None and panel.winfo_exists())
        check('four_manual_direction_buttons', set(panel.buttons) == {'up','down','left','right'})
        panel.update_idletasks()
        x, y = panel.winfo_rootx(), panel.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+panel.winfo_width(),y+panel.winfo_height()),
                       all_screens=True).save(app.OUTPUT/'fourway_controls.png')
        start_next()
    def start_next():
        if not queue:
            interrupts()
            return
        direction, moving = queue.pop(0)
        pet.root.update_idletasks()
        work = win32api.GetMonitorInfo(win32api.MonitorFromPoint(
            (pet.root.winfo_x()+128, pet.root.winfo_y()+128), 2))['Work']
        size = 128*pet.scale
        origin = ((work[0]+work[2]-size)//2, (work[1]+work[3]-size)//2)
        place(*origin)
        panel.mode.set('moving' if moving else 'in_place')
        panel.buttons[direction].invoke()
        walk = pet.walk_trial
        check(direction+('_moving' if moving else '_in_place')+'_starts', walk.active and walk.direction==direction)
        check(direction+'_eight_frames', len(walk.frames)==8)
        check(direction+'_suppresses_idle_and_reading', pet.frame_job is None and pet.reading_start_job is None)
        observed = set()
        started = time.monotonic()
        def observe():
            pet.root.update_idletasks()
            if walk.active:
                observed.add(walk.index)
                if not moving and walk.index == 0 and not (app.OUTPUT/(direction+'_render.png')).exists():
                    photo = walk.photos[pet.scale][0]
                    ImageTk.getimage(photo).save(app.OUTPUT/(direction+'_render.png'))
                pet.root.after(25, guard(observe))
                return
            elapsed = time.monotonic()-started
            pos = (pet.root.winfo_x(), pet.root.winfo_y())
            suffix = direction+('_moving' if moving else '_in_place')
            check(suffix+'_all_eight_frames_seen', observed==set(range(8)))
            check(suffix+'_three_cycles_return_idle', 3.0<=elapsed<=4.5 and pet.frame_job is not None and walk.job is None)
            if moving:
                expected = bounded_position(origin,direction,walk.speed*pet.scale*walk.total_ms/1000,
                                            work,(size,size))
                check(suffix+'_position_and_direction', all(abs(pos[i]-expected[i])<=2 for i in (0,1)))
            else:
                check(suffix+'_position_unchanged', pos==origin)
            observations.append({'direction':direction,'moving':moving,'seconds':round(elapsed,3),
                                 'frames_seen':sorted(observed),'origin':origin,'finish':pos})
            pet._cancel_reading()
            pet.root.after(50, guard(start_next))
        pet.root.after(25, guard(observe))
    def interrupts():
        panel.update_idletasks()
        x,y=panel.winfo_rootx(),panel.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+panel.winfo_width(),y+panel.winfo_height()),
                       all_screens=True).save(app.OUTPUT/'fourway_controls.png')
        panel.mode.set('in_place')
        panel.buttons['left'].invoke()
        left_photo = ImageTk.getimage(pet.walk_trial.photos[2][0])
        raw = Image.open(pet.walk_trial.asset_dir/'left/F01.png').convert('RGBA')
        translated = Image.new('RGBA', (128,128));translated.paste(raw,(0,1))
        check('left_uses_one_fixed_anchor_translation', left_photo.tobytes()==translated.resize((256,256),Image.Resampling.NEAREST).tobytes())
        pet.set_scale(3)
        check('scale_change_keeps_walk',pet.walk_trial.active and pet.walk_trial.photos[3][0].width()==384)
        pet.set_scale(2)
        panel.buttons['up'].invoke()
        check('direction_switch_cancels_previous_timer',len([j for j in pet.root.tk.splitlist(pet.root.tk.call('after','info')) if j==pet.walk_trial.job])==1 and pet.walk_trial.direction=='up')
        pet.hide()
        check('hide_stops_walk_and_all_action_timers',not pet.walk_trial.active and pet.walk_trial.job is None and
              all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')))
        check('hide_withdraws_manual_panel',panel.state()=='withdrawn')
        pet.show()
        pet.open_walk_controls()
        check('reopen_reuses_manual_panel',pet.walk_controls is panel)
        pet.start_walk('down')
        pet.start_reading()
        check('reading_replaces_walk',not pet.walk_trial.active and pet.walk_trial.job is None and pet.reading_index==0)
        pet.start_walk('left')
        event=type('E',(),{'x_root':pet.root.winfo_x()+60,'y_root':pet.root.winfo_y()+60})()
        pet._drag_begin(event);event.x_root+=20;event.y_root+=10;pet._drag_move(event)
        check('drag_cancels_walk',not pet.walk_trial.active and pet.walk_trial.job is None)
        pet._drag_end(event)
        pet.start_walk('up')
        panel.close()
        check('closing_panel_stops_walk',not pet.walk_trial.active and pet.walk_trial.job is None)
        old_position=(pet.root.winfo_x(),pet.root.winfo_y())
        place(-400,200)
        pet.set_scale(3);pet.root.update_idletasks()
        check('scale_change_preserves_negative_window_coordinates',pet.root.winfo_x()==-400 and pet.root.winfo_y()==200)
        event=type('E',(),{'x_root':-350,'y_root':250})()
        pet._drag_begin(event);event.x_root-=20;pet._drag_move(event);pet.root.update_idletasks()
        check('drag_uses_absolute_negative_coordinates',pet.root.winfo_x()==-420)
        pet._drag_end(event);pet.set_scale(2);place(*old_position)
        actual=pet.walk_trial.asset_dir
        fixture=app.STATE_ROOT/'missing_walk'
        fixture.mkdir(exist_ok=True)
        (fixture/'manifest.json').write_text(json.dumps({'renderer':'pixel','action':'walk','directions':{}}))
        pet.walk_trial.asset_dir=fixture
        check('missing_action_returns_idle_without_crash',not pet.start_walk('up') and not pet.walk_trial.active and pet.frame_job is not None)
        pet.walk_trial.asset_dir=actual
        for d in ('up','down','left','right'):
            work=(0,0,900,700);size=(256,256)
            edge=bounded_position((400,200),d,10000,work,size)
            check(d+'_workarea_boundary',0<=edge[0]<=644 and 0<=edge[1]<=444)
        negative=bounded_position((-900,-400),'left',1000,(-1920,-1080,0,0),(256,256))
        check('negative_monitor_coordinates_supported',negative==(-1900,-400))
        asset=json.loads((actual/'manifest.json').read_text(encoding='utf-8'))
        hashes=[hashlib.sha256((actual/e['file']).read_bytes()).hexdigest()==e['sha256']
                for action in asset['directions'].values() for e in action['frames']]
        check('all_32_original_frame_hashes_match',len(hashes)==32 and all(hashes))
        check('manual_regression_suspends_automatic_selector',asset['manual_only'] is False and pet.autonomous.suspended and pet.autonomous.job is None and pet.reading_start_job is not None)
        pet.root.update_idletasks()
        work=win32api.GetMonitorInfo(win32api.MonitorFromPoint(
            (pet.root.winfo_x()+128,pet.root.winfo_y()+128),2))['Work']
        size=(256,256)
        centers=((work[0]+work[2]-256)//2,(work[1]+work[3]-256)//2)
        positions={'left':(work[0]+1,centers[1]),'right':(work[2]-257,centers[1]),
                   'up':(centers[0],work[1]+1),'down':(centers[0],work[3]-257)}
        for d in ('up','down','left','right'):
            place(*positions[d]);pet.start_walk(d)
            w=pet.walk_trial
            pet.root.after_cancel(w.job);w.job=None
            w.started-=0.5
            w.step();pet.root.update_idletasks()
            pos=(pet.root.winfo_x(),pet.root.winfo_y())
            expected=bounded_position(positions[d],d,24*2*0.5,work,size)
            check(d+'_actual_window_respects_workarea',pos==expected)
            w.stop()
        place(*centers);pet.start_walk('right')
        finish()
    def finish():
        nonlocal completed
        if completed:return
        completed=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:
            pet.quit()
            check('exit_stops_walk_timer',pet.walk_trial.job is None and not pet.walk_trial.active)
            check('exit_releases_tray',not pet.tray.is_alive())
            check('exit_releases_message_bridge',pet.bridge.released)
        except Exception:
            checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        result={'checks':checks,'observations':observations,'passed':all(c['passed'] for c in checks),
                'user_visual_acceptance':'pending','automatic_walking':'suspended_only_in_this_manual_regression',
                'five_minute_performance_test':'not_run_this_step'}
        (app.OUTPUT/'walk_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(150,guard(begin))
