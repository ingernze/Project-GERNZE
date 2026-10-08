
"""Native Tk/action checks in isolated state, fake audio except one bounded driver smoke."""
import json,time,traceback,http.client
from types import SimpleNamespace
from scene_voice import WaveBackend,volume_wav
import wave,array,hashlib

def schedule(pet):
    import app
    checks=[];done=False
    class Audio:
        def __init__(self):self.calls=[];self.stops=0
        def play(self,path):self.calls.append(path.name)
        def stop(self):self.stops+=1
    audio=Audio();tick=[10.]
    pet.voice.backend=audio;pet.voice.clock=lambda:tick[0]
    def check(name,ok):
        checks.append({'check':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    def guard(fn):
        def run():
            if done:return
            try:fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return run
    def bump():tick[0]+=1
    def request(server,command,auth=True,params=None):
        con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        headers={'Content-Type':'application/json','Origin':server.origin}
        if auth:headers['Authorization']='Bearer '+server.token
        try:
            con.request('POST','/api/call',json.dumps({'command':command,'params':params or {}}),headers);resp=con.getresponse();body=resp.read();return resp.status
        finally:con.close()
    def begin():
        pet.autonomous.suspended=True;pet._cancel_reading()
        check('all_21_approved_clips_packaged',len(pet.voice.clips)==21)
        check('17_clips_have_valid_action_triggers',len({c for ids in pet.voice.events.values() for c in ids})==17)
        check('undefined_workbench_time_rules_held_back',len(pet.voice.held_back)==4 and pet.voice.events['workbench']==['WB_OPEN_01'])
        check('startup_muting_preserved',pet.muted and not pet.voice.emit('workbench'))
        check('legacy_settings_default_to_30_percent',pet.settings['voice_volume_percent']==30)
        source=pet.voice.clips['WB_OPEN_01']['path'];before_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        attenuated=volume_wav(source,app.STATE_ROOT/'voice_cache',30)
        with wave.open(str(source),'rb') as original,wave.open(str(attenuated),'rb') as quieter:
            original_samples=array.array('h',original.readframes(original.getnframes()));quieter_samples=array.array('h',quieter.readframes(quieter.getnframes()))
            check('volume_30_is_three_tenths_each_sample',all(abs(v*.3-q)<=.5 for v,q in zip(original_samples,quieter_samples)))
            check('volume_keeps_audio_format_and_duration',original.getparams()==quieter.getparams())
        check('volume_keeps_original_wav_hash',before_hash==hashlib.sha256(source.read_bytes()).hexdigest())
        backend=WaveBackend(volume=lambda:30,cache_dir=app.STATE_ROOT/'voice_cache');started=time.perf_counter();backend.play(source);elapsed=time.perf_counter()-started;backend.stop()
        check('native_WAV_async_returns_under_half_second',elapsed<.5)
        pet.toggle_mute();check('unmute_does_not_replay',not pet.muted and not audio.calls)
        pet.start_reading();check('reading_enter_plays_once',len(audio.calls)==1 and pet.voice.owner=='reading')
        before=len(audio.calls);pet._display_reading_step();check('redrawing_reading_frame_never_plays',len(audio.calls)==before)
        enter=sum(ms for index,ms in pet.reading_resource['phases']['enter'])
        pet.root.after(enter+80,guard(reading))
    def reading():
        check('reading_reaches_hold',pet.reading_phase=='reading')
        bump();before=len(audio.calls);pet.glance_from_reading();check('click_glance_plays_once',len(audio.calls)==before+1)
        pet.glance_from_reading();check('busy_glance_no_duplicate',len(audio.calls)==before+1)
        pet._reset_idle();bump();pet.start_manual_action('sleep');check('sleep_enter_plays',pet.voice.current=='HAT_SLEEP_02')
        before=len(audio.calls)
        for _ in range(3):pet.manual_action._play_phase('loop')
        check('sleep_loop_does_not_repeat_audio',len(audio.calls)==before)
        bump();pet.manual_action._play_phase('exit');check('wake_phase_plays_once',len(audio.calls)==before+1 and pet.voice.current.startswith('WAKE_01_'))
        pet._reset_idle();bump();pet.voice.preview('WB_OPEN_01');pet.toggle_mute();check('mute_stops_current_clip',pet.voice.current is None)
        pet.toggle_mute();check('unmute_never_replays_old_clip',pet.voice.current is None)
        bump();pet.voice.preview('WB_OPEN_01');pet.hide();check('hide_stops_clip',pet.voice.current is None)
        before=len(audio.calls);pet.voice.emit('drag');check('hidden_action_silent',len(audio.calls)==before)
        pet.show();check('show_never_replays_old_clip',len(audio.calls)==before)
        pet.autonomous.suspended=True;pet._cancel_reading();bump()
        start=(pet.root.winfo_x()+40,pet.root.winfo_y()+40);pet.coast.clock=lambda:tick[0]
        e=lambda x,y:SimpleNamespace(x_root=x,y_root=y,x=40,y=40)
        pet._drag_begin(e(*start));tick[0]+=.03;pet._drag_move(e(start[0]+12,start[1]+2));before=len(audio.calls)
        tick[0]+=.03;pet._drag_move(e(start[0]+24,start[1]+2));check('drag_motion_does_not_repeat_voice',len(audio.calls)==before)
        tick[0]+=.03;pet._drag_end(e(start[0]+36,start[1]+2));check('coasting_branch_plays_slide',pet.coast.motion.frame.active and pet.voice.owner=='slide')
        pet._cancel_coast();check('catching_or_canceling_slide_stops_voice',pet.voice.current is None)
        pet.set_voice_volume(100);check('volume_100_saved',json.loads(app.SETTINGS.read_text(encoding='utf-8'))['voice_volume_percent']==100)
        pet.voice.preview('WB_OPEN_01');pet.set_voice_volume(30);check('changing_volume_stops_without_replay',pet.voice.current is None and pet.settings['voice_volume_percent']==30)
        panel=pet.open_voice_controls();check('developer_voice_window_available',panel.winfo_exists())
        panel.destroy();pet.voice_controls=None
        s=pet.workbench.open(launch_browser=False)
        check('voice_endpoint_requires_capability',request(s,'voice.workbench_open',auth=False)==403)
        check('voice_endpoint_rejects_arbitrary_files',request(s,'voice.workbench_open',params={'file':'C:/arbitrary.wav'})==400)
        bump();check('voice_endpoint_accepts_finite_event',request(s,'voice.workbench_open')==200);pet._consume_commands()
        check('authenticated_event_reaches_Tk_and_plays_welcome',pet.voice.current=='WB_OPEN_01')
        check('workbench_stop_authenticated',request(s,'voice.workbench_stop')==200);pet._consume_commands();check('workbench_stop_does_not_leave_sound',pet.voice.current is None)
        bump();pet.voice.emit('workbench');pet.set_style('style2');check('style_switch_stops_voice',pet.voice.current is None)
        bump();pet.voice.preview('WB_OPEN_01');pet.set_scale(3);check('resizing_stops_voice',pet.voice.current is None)
        pet.root.after(50,guard(finish))
    def finish():
        nonlocal done
        if done:return
        done=True;pet.voice.close();check('voice_controller_closed',pet.voice.closed and pet.voice.current is None)
        (app.OUTPUT/'voice_results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
        pet.quit()
    pet.root.after(80,guard(begin));pet.root.after(30000,guard(lambda:(_ for _ in ()).throw(RuntimeError('voice test timeout'))))
