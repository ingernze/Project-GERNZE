"""Three real workbench reopen cycles and authenticated native voice routes."""
import http.client,json,time,traceback
import win32gui,win32con
from PIL import ImageGrab

def schedule(pet):
    import app
    checks=[];rounds=[];started=time.monotonic();cycle=[0];done=[False]
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def call(s,command):
        c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3)
        try:
            c.request('POST','/api/call',json.dumps({'command':command,'params':{}}),{'Content-Type':'application/json','Authorization':'Bearer '+s.token,'Origin':s.origin})
            r=c.getresponse();value=json.loads(r.read());check(command+'_http_200',r.status==200);return value['result']
        finally:c.close()
    def finish():
        if done[0]:return
        done[0]=True
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'voice_entry_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks,'rounds':rounds},ensure_ascii=False,indent=2),encoding='utf8')
        pet.quit()
    def guarded(fn):
        def wrap():
            try:fn()
            except Exception:checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()});finish()
        return wrap
    def open_round():
        pet.autonomous.suspended=True;pet._cancel_reading()
        pet._enqueue_command('workbench:open');pet.root.after(150,guarded(wait_window))
    def wait_window():
        if time.monotonic()-started>100:raise TimeoutError('three-cycle acceptance')
        s=pet.workbench.server;w=pet.workbench.window
        if not w or not w.ready.is_set():pet.root.after(100,guarded(wait_window));return
        check('round_'+str(cycle[0]+1)+'_native_window_exists',not w.error and bool(w.hwnd) and win32gui.IsWindow(w.hwnd))
        # Title is set after actual authenticated frontend bootstrap and navigation.
        if win32gui.GetWindowText(w.hwnd)!='六级学习 · 莉宝':pet.root.after(100,guarded(wait_window));return
        check('round_'+str(cycle[0]+1)+'_frontend_loaded',True)
        check('desktop_voice_available',call(s,'voice.available')['available'])
        check('learning_api_connected','progress' in call(s,'state.summary'))
        c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3)
        try:
            c.request('GET','/modules.js');r=c.getresponse();body=r.read().decode('utf8')
            check('packaged_voice_entry_current',r.status==200 and "['voice','声音'" in body and '模型与播放运行时待接入' not in body)
        finally:c.close()
        before=w.launch_count;hwnd=w.hwnd
        pet.workbench.open();pet.workbench.open()
        check('rapid_reopen_reuses_existing_window',w.hwnd==hwnd and w.launch_count==before)
        rounds.append({'round':cycle[0]+1,'page':'六级学习 · 莉宝','http_connected':True,'single_window':True})
        if cycle[0]==0:
            call(s,'voice.fixed');pet.root.after(250,guarded(check_fixed))
        else:close_round()
    def check_fixed():
        check('fixed_window_opened_through_workbench',pet.voice_controls is not None and len(pet.voice_controls.voice_rows)==21)
        check('no_engine_loaded_for_fixed_window',pet.voice_module._backend is None)
        call(pet.workbench.server,'voice.text');pet.root.after(250,guarded(check_text))
    def check_text():
        check('text_window_opened_through_workbench',pet.voice_text_window is not None and len(pet.voice_text_window.combos)==3)
        check('model_runtime_remains_lazy',pet.voice_module._backend is None)
        call(pet.workbench.server,'voice.api');pet.root.after(250,guarded(check_api))
    def check_api():
        check('api_settings_opened_through_workbench',pet.voice_api_window is not None)
        check('api_open_does_not_start_inference',pet.voice_module._backend._process is None)
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        w=pet.voice_text_window;w.lift();w.update_idletasks()
        ImageGrab.grab(bbox=(w.winfo_rootx(),w.winfo_rooty(),w.winfo_rootx()+w.winfo_width(),w.winfo_rooty()+w.winfo_height()),all_screens=True).save(app.OUTPUT/'voice_text.png')
        pet.voice_api_window.close();pet.voice_text_window.close();pet.voice_controls.destroy();pet.voice_controls=None
        close_round()
    def close_round():
        # Native titlebar close, as the user does; the owned process releases server.
        w=pet.workbench.window
        win32gui.PostMessage(w.hwnd,win32con.WM_CLOSE,0,0)
        pet.root.after(200,guarded(wait_closed))
    def wait_closed():
        if time.monotonic()-started>100:raise TimeoutError('native close timeout')
        if pet.workbench.worker.is_alive():pet.root.after(100,guarded(wait_closed));return
        check('round_'+str(cycle[0]+1)+'_server_reclaimed',pet.workbench.server.closing)
        cycle[0]+=1
        if cycle[0]==3:finish()
        else:pet.root.after(250,guarded(open_round))
    pet.root.after(250,guarded(open_round))
