"""Native text-entry acceptance, two actual models; no cloud requests or audible test playback."""
import json,time,traceback,hashlib,wave,os
from PIL import Image
import ctypes,win32gui,win32ui

def schedule(pet):
    import app
    checks=[];samples=[];stage=[0];ticks=[0];done=False;started=time.monotonic();window=[None]
    module=pet.voice_module
    class Audio:
        def __init__(self):self.calls=[]
        def play(self,path):self.calls.append(str(path))
        def stop(self):pass
    audio=Audio();pet.voice.backend=audio
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    def finish():
        nonlocal done
        if done:return
        done=True
        try:module.on_change=None;module.close()
        except Exception:checks.append({'check':'close_error','passed':False,'error':traceback.format_exc()})
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'voice_text_results.json').write_text(json.dumps({'passed':all(c['passed'] for c in checks),'checks':checks,'samples':samples,'ui_ticks':ticks[0]},ensure_ascii=False,indent=2),encoding='utf8')
        pet.quit()
    def capture(name):
        if os.environ.get('HECATE_TEST_QUIET_UI')=='1':return
        panel=window[0];panel.update_idletasks()
        hwnd=win32gui.GetParent(panel.winfo_id());left,top,right,bottom=win32gui.GetWindowRect(hwnd)
        width,height=right-left,bottom-top;handle=win32gui.GetWindowDC(hwnd)
        dc=win32ui.CreateDCFromHandle(handle);memory=dc.CreateCompatibleDC();bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(dc,width,height)
        memory.SelectObject(bitmap)
        try:
            ctypes.windll.user32.PrintWindow(hwnd,memory.GetSafeHdc(),2)
            image=Image.frombuffer('RGB',(width,height),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
            app.OUTPUT.mkdir(parents=True,exist_ok=True);image.save(app.OUTPUT/(name+'.png'))
        finally:
            memory.DeleteDC();dc.DeleteDC();win32gui.ReleaseDC(hwnd,handle);win32gui.DeleteObject(bitmap.GetHandle())
    def begin():
        try:
            pet.autonomous.suspended=True;pet._cancel_reading()
            hub=pet.open_voice_modules()
            check('developer_voice_entry_reuses_one_window',hub is pet.open_voice_modules())
            check('opening_voice_hub_does_not_load_engine',module._backend is None)
            from tray_popup import TrayPopup
            popup=TrayPopup(pet,80,80)
            entry=[box for box,cmd in popup.items if cmd=='voice_modules:open']
            check('voice_entry_is_in_developer_section',len(entry)==1 and entry[0][1]==588 and not any(cmd=='voice_module:open' for box,cmd in popup.items))
            popup.close()
            hub.fixed_button.invoke();fixed=pet.voice_controls
            check('fixed_library_opens_all_21_recordings',len(fixed.voice_rows)==21)
            check('fixed_describes_17_triggers_4_preview_only',sum(r['state']=='已接入触发' for r in fixed.voice_rows)==17 and sum(r['state']=='仅供手动试听' for r in fixed.voice_rows)==4)
            welcome=next(i for i,r in enumerate(fixed.voice_rows) if r['id']=='WB_OPEN_01')
            fixed.voice_list.selection_set(welcome);fixed.refresh_selection()
            check('welcome_trigger_explains_process_and_watch_cue','同一进程不重播' in fixed.trigger_detail.get() and '2.1秒' in fixed.trigger_detail.get())
            check('opening_fixed_library_keeps_model_unloaded',module._backend is None)
            hub.text_button.invoke();window[0]=pet.voice_text_window;panel=window[0]
            check('hub_text_button_opens_actual_synthesis_form',panel is not None)

            check('open_reuses_one_text_window',panel is pet.open_voice_text())
            check('opening_and_query_choices_do_not_load_engine',module._backend is None)
            check('three_independent_selectors',len(panel.combos)==3)
            check('default_selection_second_pair',module.selection()['gpt_id']=='voice_2' and module.selection()['sovits_id']=='voice_2')
            check('style_uses_existing_starroom',panel.cget('bg')=='#161d31')
            panel.text.delete('1.0','end');panel.text.insert('1.0','欢迎回来，我们慢慢来。');panel.update_idletasks()
            panel.generate();check('muted_click_does_not_load_engine',module._backend is None and '取消静音' in panel.status.get())
            panel.mute.invoke();check('mute_toggle_updates_window',not pet.muted and panel.mute.cget('text')=='静音')
            panel.text.delete('1.0','end');panel.generate();check('empty_text_inline_error',module._backend is None and '500' in panel.status.get())
            panel.text.insert('1.0','a'*501);panel.generate();check('oversized_text_inline_error',module._backend is None and '500' in panel.status.get())
            panel.text.delete('1.0','end');panel.text.insert('1.0','欢迎回来，我们慢慢来。')
            panel.combos['gpt_id'].current(0);panel.combos['sovits_id'].current(0);panel.combos['reference_id'].current(1);panel.save_selection()
            check('selection_saved_separately',json.loads((app.STATE_ROOT/'voice_module_settings.json').read_text(encoding='utf8'))==module.selection())
            panel.update_idletasks();pet.root.after(250,lambda:capture('voice_text_ready'))
            panel.play.invoke();check('button_submits_without_blocking',module.busy)
            panel.generate();check('repeated_click_does_not_queue',module._generation==1)
            check('generation_progress_visible_and_running',panel._progress_running and bool(panel.progress.winfo_manager()))
            check('generating_disables_button_and_selectors',panel.play.instate(['disabled']) and all(c.instate(['disabled']) for c in panel.combos.values()))
            if os.environ.get('HECATE_TEST_QUIET_UI')=='1':
                pet.root.withdraw();hub.withdraw();fixed.withdraw();panel.withdraw()
            stage[0]=1;pet.root.after(50,poll)
        except Exception:
            checks.append({'check':'begin_error','passed':False,'error':traceback.format_exc()});finish()
    def poll():
        if done:return
        ticks[0]+=1
        try:
            if time.monotonic()-started>150:raise TimeoutError('text-entry acceptance timed out')
            if module.status['state']=='error':raise RuntimeError(str(module.status))
            panel=window[0]
            if stage[0] in (1,2) and module.status['state']=='played':
                check('first_pair_button_generates_and_plays' if stage[0]==1 else 'second_pair_keyboard_generates_and_plays',len(audio.calls)==stage[0])
                samples.append(module.last_result)
                check('generation_finished_has_no_generation_poll',not panel._progress_running)
                check('button_reenabled_on_result',not panel.play.instate(['disabled']))
                check('finished_generation_hides_progress',not panel._progress_running and not panel.progress.winfo_manager())
                check('responsive_during_generation',ticks[0]>5)
                if stage[0]==1:
                    panel.combos['gpt_id'].current(1);panel.combos['sovits_id'].current(1);panel.combos['reference_id'].current(0)
                    panel.save_selection();panel._shortcut(None);stage[0]=2
                else:
                    capture('voice_text_played')
                    panel.geometry('580x460');stage[0]=4;pet.root.after(200,poll);return
            elif stage[0]==4:
                panel.update_idletasks()
                checks.append({'check':'minimum_size_geometry','passed':True,'window_height':panel.winfo_height(),'status_bottom':panel.status_label.winfo_rooty()+panel.status_label.winfo_height()-panel.winfo_rooty()})
                check('minimum_size_keeps_input_usable',panel.text.winfo_height()>=60)
                check('minimum_size_keeps_status_visible',panel.status_label.winfo_rooty()+panel.status_label.winfo_height()<=panel.winfo_rooty()+panel.winfo_height())
                capture('voice_text_minimum')
                panel.generate();panel.close();check('close_detaches_window_and_cancels',pet.voice_text_window is None and module.on_change is None and not panel._progress_running);stage[0]=3
            elif stage[0]==3 and module.status['state']=='cancelled' and not module.busy:
                check('closed_window_never_plays_late_audio',len(audio.calls)==2)
                check('cancel_releases_owned_engine',module._backend._process is None)
                window[0]=pet.open_voice_text();panel=window[0]
                check('reopen_restores_saved_second_pair',panel.combos['gpt_id'].current()==1 and panel.combos['sovits_id'].current()==1)
                pet.hide();check('hide_withdraws_text_window',panel.state()=='withdrawn')
                pet.open_voice_text();check('reopen_restores_hidden_window',panel.state()=='normal')
                check('fixed_library_remains_21',len(module.fixed_scenes())==21)
                finish();return
            pet.root.after(50,poll)
        except Exception:
            checks.append({'check':'poll_error','passed':False,'error':traceback.format_exc()});finish()
    pet.root.after(150,begin)
