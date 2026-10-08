"""Real local TTS through native desktop queue; no cloud keys or audible playback."""
import json,time,traceback,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def schedule(pet):
    import app
    checks=[];samples=[];ticks=[0];done=False;stage=[0];start=time.monotonic()
    module=pet.voice_module
    fixture=[None];requests=[]
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
        try:module.close();check('owned_engine_closed',module._backend is None or module._backend._process is None)
        except Exception:checks.append({'check':'close_error','passed':False,'error':traceback.format_exc()})
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'voice_module_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks,'samples':samples,'ui_ticks':ticks[0],'elapsed':time.monotonic()-start},ensure_ascii=False,indent=2),encoding='utf8')
        if fixture[0] is not None:
            fixture[0].shutdown();fixture[0].server_close()
        pet.quit()
    def begin():
        try:
            pet.autonomous.suspended=True;pet._cancel_reading()
            check('startup_does_not_load_gpu_or_api',module._backend is None)
            check('default_volume_30',pet.settings['voice_volume_percent']==30)
            check('default_gpt_and_sovits_second',module.selection()=={'gpt_id':'voice_2','sovits_id':'voice_2','reference_id':'denia_06'})
            check('fixed_21_separate_from_generated',len(module.fixed_scenes())==21)
            pet.muted=False;pet.visible=True
            check('fixed_preview_uses_existing_channel',module.play_fixed('WB_OPEN_01') and len(audio.calls)==1 and module._backend is None)
            pet.voice.stop()
            module.set_selection(gpt_id='voice_1',sovits_id='voice_1',reference_id='denia_06')
            t=time.perf_counter();module.speak_text('欢迎回来，我们慢慢来。')
            check('synthesis_submission_does_not_block_ui',time.perf_counter()-t<.5)
            stage[0]=1;pet.root.after(50,poll)
        except Exception:
            checks.append({'check':'begin_error','passed':False,'error':traceback.format_exc()});finish()
    def poll():
        if done:return
        ticks[0]+=1
        try:
            if time.monotonic()-start>150:raise TimeoutError('native TTS acceptance deadline')
            if module.status['state']=='error':raise RuntimeError(str(module.status))
            if stage[0] in (1,2,3) and module.status['state']=='played':
                check({1:'first_model_played',2:'second_model_played',3:'feature_api_reply_then_local_tts_played'}[stage[0]],len(audio.calls)==stage[0]+1)
                samples.append(module.last_result)
                check('ui_continues_during_tts',ticks[0]>5)
                health=module._backend.health()
                check('runtime_independent_of_training_folder',not health.get('original_module_paths') and not health.get('original_native_library_paths') and not health.get('rejected_original_reads'))
                if stage[0]==1:
                    module.set_selection(gpt_id='voice_2',sovits_id='voice_2',reference_id='denia_02')
                    module.speak_text('晚上好，我们继续工作吧。');stage[0]=2
                elif stage[0]==2:
                    class Handler(BaseHTTPRequestHandler):
                        def log_message(self,*args):pass
                        def do_POST(self):
                            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                            requests.append({'path':self.path,'auth_ok':self.headers.get('Authorization')=='Bearer isolated-voice-test-token','model':body['model'],'message':body['messages'][0]['content']})
                            data=json.dumps({'choices':[{'message':{'content':'好，我们慢慢来。'}}]},ensure_ascii=False).encode('utf8')
                            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                    server=fixture[0]=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                    threading.Thread(target=server.serve_forever,daemon=True).start()
                    store=type(module._backend.feature_apis)(app.STATE_ROOT/'fixture_features.json')
                    store.key=lambda feature:'isolated-voice-test-token' if feature=='voice_dialogue' else ''
                    store.configure('voice_dialogue',enabled=True,endpoint='http://127.0.0.1:'+str(server.server_port)+'/v1/chat/completions',model='voice-test-model')
                    module._backend.feature_apis=store
                    module.dialogue([{'role':'user','content':'今天先做一件事。'}]);stage[0]=3
                else:
                    check('API_uses_feature_specific_contract',len(requests)==1 and requests[0]['auth_ok'] and requests[0]['path']=='/v1/chat/completions' and requests[0]['model']=='voice-test-model')
                    check('API_reply_returned_to_desktop',module.last_result['text']=='好，我们慢慢来。')
                    module.speak_text('这句已经取消，不应该播放。');pet.hide();stage[0]=4
            elif stage[0]==4 and module.status['state']=='cancelled':
                check('hide_discards_late_audio',len(audio.calls)==4)
                if module._cleanup and module._cleanup.is_alive():pet.root.after(50,poll);return
                check('hide_releases_owned_engine',module._backend._process is None)
                check('two_weight_pairs_and_references_used',samples[0]['selection']['gpt_id']=='voice_1' and samples[1]['selection']['gpt_id']=='voice_2' and samples[1]['selection']['reference_id']=='denia_02')
                finish();return
            pet.root.after(50,poll)
        except Exception:
            checks.append({'check':'poll_error','passed':False,'error':traceback.format_exc()});finish()
    pet.root.after(150,begin)
