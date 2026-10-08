"""Real packaged Tk acceptance, isolated settings, no synthesis or audible playback."""
import json,traceback,hashlib
from PIL import ImageGrab
from scene_voice import SceneVoice,fixed_voice_rows
from voice_bindings_window import open_voice_bindings_window

class SilentBackend:
    def play(self,path):pass
    def stop(self):pass

def schedule(pet):
    import sys
    for flag, name in (('--foot-front-self-test','foot_front_self_test'),
                       ('--module-adoption-self-test','module_adoption_self_test'),
                       ('--module-package-self-test','module_package_self_test'),
                       ('--long-soak-self-test','long_soak_self_test'),
                       ('--activity-timing-self-test','activity_timing_self_test'),
                       ('--sleep-v11-self-test','sleep_v11_self_test')):
        if flag in sys.argv:
            import importlib
            return importlib.import_module(name).schedule(pet)
    import app
    checks=[];done=False;watchdog=None;seen=[];w=None
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def guard(fn):
        def wrapped():
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return wrapped
    def event(key):
        from voice_bindings_window import EVENT_NAMES
        w.event_combo.current(list(EVENT_NAMES).index(key))
        w.event_combo.event_generate('<<ComboboxSelected>>')
        pet.root.update_idletasks()
    def select(ids):
        w.clip_list.selection_clear(0,'end')
        for identity in ids:w.clip_list.selection_set(w.clip_ids.index(identity))
        w.clip_list.event_generate('<<ListboxSelect>>')
    def capture(window,name):
        window.update_idletasks()
        x,y=window.winfo_rootx(),window.winfo_rooty()
        ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(app.OUTPUT/name)
    def begin():
        nonlocal w,watchdog
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        watchdog=pet.root.after(25000,guard(lambda:check('watchdog',False)))
        check('isolated_without_accounts',not pet.key_present and not pet.quota_enabled)
        pet.voice.backend=SilentBackend()
        fixed=pet.open_voice_controls();w=open_voice_bindings_window(pet)
        check('settings_single_window',open_voice_bindings_window(pet) is w)
        check('fixed_single_window',pet.open_voice_controls() is fixed)
        check('all_approved_recordings',len(w.clip_ids)==len(pet.voice.clips)==21)
        event('drag');select(['WB_OPEN_02_morning','DRAG_START_01'])
        w.save_binding_button.invoke()
        chosen=['WB_OPEN_02_morning','DRAG_START_01']
        check('custom_group_saved',set(pet.voice.events['drag'])==set(chosen))
        saved=json.loads(app.SETTINGS.read_text(encoding='utf8'))
        check('persistent_custom_group',set(saved['scene_voice_bindings']['drag'])==set(chosen))
        check('volume_unchanged',saved['voice_volume_percent']==30)
        row=next(r for r in fixed.voice_rows if r['id']=='WB_OPEN_02_morning')
        check('held_recording_shows_actual_trigger','抓取拖动' in row['trigger'])
        fresh=SceneVoice(app.ROOT/'assets/voice',backend=SilentBackend(),bindings=saved['scene_voice_bindings'])
        check('reload_same_group',fresh.events['drag']==pet.voice.events['drag'])
        event('wake_evening');old_drag=list(pet.voice.events['drag']);w.disable_binding_button.invoke()
        check('disable_one_scene',pet.voice.events['wake_evening']==[] and pet.voice.events['drag']==old_drag)
        w.restore_binding_button.invoke()
        check('restore_default',pet.voice.events['wake_evening']==pet.voice.default_events['wake_evening'] and 'wake_evening' not in pet.voice.binding_overrides)
        event('drag');select(['SLIDE_01']);event('slide');event('drag')
        check('draft_preserved_on_switch',[w.clip_ids[i] for i in w.clip_list.curselection()]==['SLIDE_01'])
        w.close();w=open_voice_bindings_window(pet);event('drag')
        check('closed_draft_not_saved',set(w.clip_ids[i] for i in w.clip_list.curselection())==set(chosen))
        event('workbench');w.restore_binding_button.invoke()
        w.attributes('-topmost',True);w.lift();w.focus_force()
        pet.root.after(250,guard(pictures))
    def pictures():
        capture(w,'触发设置_默认尺寸.png')
        w.geometry('620x600');pet.root.after(200,guard(minimum))
    def minimum():
        capture(w,'触发设置_最小尺寸.png')
        for name in ('save_binding_button','disable_binding_button','restore_binding_button'):
            button=getattr(w,name)
            check('visible_'+name,button.winfo_width()>30 and button.winfo_rootx()+button.winfo_width()<=w.winfo_rootx()+w.winfo_width())
        w.close()
        fixed=pet.open_voice_controls();fixed.attributes('-topmost',True);fixed.lift();fixed.geometry('620x600')
        pet.root.after(200,guard(animation))
    def animation():
        fixed=pet.voice_controls;capture(fixed,'固定语音_最小尺寸.png')
        check('fixed_buttons_visible',all(b.winfo_width()>30 for b in (fixed.bindings_button,fixed.play_button,fixed.mute_button)))
        fixed.destroy();pet.voice_controls=None
        check('style2_available',pet.set_style('style2'))
        check('foot_sway_available',pet.set_style2_motion('foot_sway'))
        manifest=pet.manifest
        files=[f['file'] for f in manifest['frames']]
        check('accepted_entry_first',files[0]=='B01.png' and pet.frame_index==0)
        check('finite_cycles',len(files)==18*pet._sway_cycles+9 and not manifest['loop'])
        check('accepted_exit_last',files[-1]=='B01.png')
        from foot_sway import sequence
        check('validated_native_sources',sequence(pet.style_asset_paths['idle']/'foot_sway',pet._sway_cycles)[0]['frames']==manifest['frames'])
        seen.append(pet.frame_index)
        for delay in (500,1000,1600,2200):pet.root.after(delay,guard(lambda:seen.append(pet.frame_index)))
        pet.root.after(2800,guard(complete))
    def complete():
        check('animation_advances_and_loops',len(set(seen))>=4 and pet.frame_job is not None and pet.frame_index<len(pet.frames))
        finish()
    def finish():
        nonlocal done
        if done:return
        done=True
        if watchdog is not None:pet.root.after_cancel(watchdog)
        try:pet.quit()
        except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        (app.OUTPUT/'scene_settings_results.json').write_text(json.dumps({'passed':all(c['passed'] for c in checks),'checks':checks,'audible_playback':False,'synthesis':False},ensure_ascii=False,indent=2),encoding='utf8')
    pet.root.after(400,guard(begin))
