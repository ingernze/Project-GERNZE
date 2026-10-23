"""UI-independent voice backend: approved clips, local TTS and feature-scoped APIs."""
from __future__ import annotations
import array,hashlib,io,json,os,re,secrets,subprocess,threading,time,uuid,wave
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,CancelledError
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.parse import urlsplit

HOME=Path(__file__).resolve().parent
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
HTTP=build_opener(ProxyHandler({}),NoRedirect())

def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def atomic_json(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,p)
def asset(home,entry):
    p=(home/entry['path']).resolve()
    if home.resolve() not in p.parents:raise ValueError('Asset escapes voice directory')
    if not p.is_file():raise FileNotFoundError('Voice asset missing')
    return p

def pcm_file(path,cache,volume):
    if type(volume) is not int or not 0<=volume<=100:raise ValueError('Volume must be 0 to 100')
    if volume==100:return Path(path)
    data=Path(path).read_bytes();name=hashlib.sha256(data).hexdigest()+'-'+str(volume)+'.wav'
    p=Path(cache)/name
    if p.exists():return p
    with wave.open(io.BytesIO(data),'rb') as w:
        params=w.getparams()
        if w.getsampwidth()!=2 or w.getcomptype()!='NONE':raise ValueError('PCM16 WAV required')
        samples=array.array('h',w.readframes(w.getnframes()))
    scaled=array.array('h',(round(s*volume/100) for s in samples));p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(uuid.uuid4().hex+'.tmp')
    with wave.open(str(temp),'wb') as w:w.setparams(params);w.writeframes(scaled.tobytes())
    os.replace(temp,p);return p

class FeatureAPIStore:
    """One config and Windows credential target per feature; no global key fallback."""
    def __init__(self,path=None):self.path=Path(path or HOME/'state/features.json');self._lock=threading.RLock()
    def target(self,feature):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',feature):raise ValueError('Invalid feature identifier')
        return 'Hecate/ModuleAPI/'+feature
    def get(self,feature):
        self.target(feature)
        with self._lock:
            data=read_json(self.path) if self.path.exists() else {}
            return dict(data.get(feature,{'enabled':False,'endpoint':'','model':''}))
    def configure(self,feature,*,enabled,endpoint,model):
        self.target(feature);parts=urlsplit(endpoint)
        if type(enabled) is not bool:raise ValueError('Enabled must be boolean')
        if parts.username or parts.password or parts.query or parts.fragment:raise ValueError('Do not place credentials in the URL')
        if endpoint and (parts.scheme!='https' and not (parts.scheme=='http' and parts.hostname in ('127.0.0.1','localhost','::1'))):raise ValueError('HTTPS required except loopback')
        if enabled and (not endpoint or not str(model).strip()):raise ValueError('Endpoint and model required')
        with self._lock:
            data=read_json(self.path) if self.path.exists() else {}
            data[feature]={'enabled':enabled,'endpoint':endpoint,'model':str(model).strip()};atomic_json(self.path,data)
    def save_key(self,feature,key):
        import win32cred
        if not isinstance(key,str) or not key.strip():raise ValueError('API key required')
        win32cred.CredWrite({'Type':win32cred.CRED_TYPE_GENERIC,'TargetName':self.target(feature),'UserName':feature,'CredentialBlob':key.strip().encode('utf-16le'),'Persist':win32cred.CRED_PERSIST_LOCAL_MACHINE},0)
    def key(self,feature):
        import win32cred
        target=self.target(feature)
        try:value=win32cred.CredRead(target,win32cred.CRED_TYPE_GENERIC,0)['CredentialBlob']
        except Exception as e:
            if getattr(e,'winerror',None)==1168:return ''
            raise RuntimeError('Windows credential store unavailable') from None
        return value.decode('utf-16le') if isinstance(value,bytes) else value
    def delete_key(self,feature):
        import win32cred
        try:win32cred.CredDelete(self.target(feature),win32cred.CRED_TYPE_GENERIC,0)
        except Exception as e:
            if getattr(e,'winerror',None)!=1168:raise
    def chat(self,feature,messages,timeout=90):
        config=self.get(feature)
        if not config['enabled']:raise RuntimeError('This feature API is disabled')
        key=self.key(feature)
        if not key:raise RuntimeError('This feature has no API credential')
        if not isinstance(messages,list) or not messages or len(messages)>50:raise ValueError('Messages required')
        for m in messages:
            if not isinstance(m,dict) or m.get('role') not in ('system','user','assistant') or not isinstance(m.get('content'),str):raise ValueError('Invalid message')
        body=json.dumps({'model':config['model'],'messages':messages,'stream':False},ensure_ascii=False).encode('utf8')
        if len(body)>65536:raise ValueError('Conversation too long')
        request=Request(config['endpoint'],data=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        try:
            with HTTP.open(request,timeout=timeout) as response:
                raw=response.read(1048577)
            if len(raw)>1048576:raise RuntimeError('Reply too large')
            content=json.loads(raw)['choices'][0]['message']['content']
            if not isinstance(content,str) or not content.strip():raise RuntimeError('Empty reply')
            return content
        except Exception:raise RuntimeError('Feature API request failed; check that feature settings') from None

class VoiceBackend:
    def __init__(self,home=HOME):
        self.home=Path(home).resolve();self.catalog=read_json(self.home/'catalog.json')
        self.state=self.home/'state';self.state.mkdir(exist_ok=True)
        self.feature_apis=FeatureAPIStore(self.state/'features.json')
        self._process_lock=threading.RLock();self._work_lock=threading.Lock();self._submit_lock=threading.Lock()
        self._process=None;self._log=None;self._endpoint=None;self._token=None;self._ready=None
        self._playing=False;self._generation=0;self._closed=False;self._timer=None;self._future=None
        self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='HecateVoice')
        self._fixed=read_json(self.home/'fixed_scenes/manifest.json')['records']
    def selections(self):
        return {k:json.loads(json.dumps(self.catalog[k])) for k in ('gpt_options','sovits_options','references','defaults')}
    def fixed_scenes(self):
        return [{'id':r['id'],'scene':r['scene'],'text':r['text'],'model_label':'第一套' if r.get('model_code')=='A' else '第二套'} for r in self._fixed]
    def fixed_path(self,identity):
        record=next((r for r in self._fixed if r['id']==identity),None)
        if record is None:raise ValueError('Unknown fixed scene')
        p=self.home/'fixed_scenes'/'audio'/(identity+'.wav')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Fixed scene checksum differs')
        return p
    def play_file(self,path,volume=30):
        import winsound
        self.stop_playback()
        if volume==0:return False
        p=pcm_file(path,self.state/'playback_cache',volume)
        winsound.PlaySound(str(p),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT);self._playing=True;return True
    def play_fixed(self,identity,volume=30):return self.play_file(self.fixed_path(identity),volume)
    def stop_playback(self):
        import winsound
        winsound.PlaySound(None,0);self._playing=False
    def _request(self,path,body=None,timeout=5):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf8')
        request=Request(self._endpoint+path,data=data,headers={'Authorization':'Bearer '+self._token,'Content-Type':'application/json'})
        with HTTP.open(request,timeout=timeout) as response:
            result=response.read(40*1024*1024+1)
        if len(result)>40*1024*1024:raise RuntimeError('Audio too large')
        return result
    def start(self,generation=None):
        with self._process_lock:
            if self._closed:raise RuntimeError('Voice backend closed')
            if generation is not None and generation!=self._generation:raise CancelledError()
            if self._timer:self._timer.cancel();self._timer=None
            if self._process is not None and self._process.poll() is None and self._endpoint:return
            self._stop_engine_locked()
            self._token=secrets.token_urlsafe(32);identity=uuid.uuid4().hex
            self._ready=self.state/(identity+'.json');log=self.state/(identity+'.log')
            self._log=log.open('wb')
            env=os.environ.copy();env.update(HECATE_VOICE_TOKEN=self._token,HECATE_VOICE_READY=identity,PYTHONDONTWRITEBYTECODE='1')
            self._process=subprocess.Popen([str(self.home/'runtime/python.exe'),'-B','-X','utf8',str(self.home/'engine_worker.py')],cwd=str(self.home),env=env,stdin=subprocess.DEVNULL,stdout=self._log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process=self._process
        deadline=time.monotonic()+120
        while not self._ready.exists():
            if generation is not None and generation!=self._generation:raise CancelledError()
            if process.poll() is not None:
                self.stop_engine();raise RuntimeError('Local voice startup failed; see worker log '+str(log))
            if time.monotonic()>deadline:
                self.stop_engine();raise TimeoutError('Local voice startup timed out')
            time.sleep(.15)
        with self._process_lock:
            if generation is not None and generation!=self._generation:raise CancelledError()
            info=read_json(self._ready)
            if info.get('pid')!=process.pid:raise RuntimeError('Readiness file is from another worker')
            self._endpoint='http://127.0.0.1:'+str(info['port'])
        health=json.loads(self._request('/health'))
        if health.get('original_module_paths') or health.get('original_native_library_paths') or health.get('rejected_original_reads'):self.stop_engine();raise RuntimeError('Training directory dependency detected')
    def health(self):
        if not self._endpoint:return {'ready':False}
        return json.loads(self._request('/health'))
    def _stop_engine_locked(self):
        if self._timer:self._timer.cancel();self._timer=None
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:self._process.kill();self._process.wait(timeout=5)
        if self._log:self._log.close()
        if self._ready:self._ready.unlink(missing_ok=True)
        self._process=None;self._endpoint=None;self._token=None;self._log=None
    def stop_engine(self):
        with self._process_lock:self._stop_engine_locked()
    def _arm_idle_stop(self):
        with self._process_lock:
            if self._closed:return
            if self._timer:self._timer.cancel()
            self._timer=threading.Timer(120,self.stop_engine);self._timer.daemon=True;self._timer.start()
    def synthesize(self,text,*,gpt_id=None,sovits_id=None,reference_id=None,speed=1,seed=20261006,temperature=1,top_p=1,_expected_generation=None):
        if not isinstance(text,str) or not text.strip() or len(text)>500:raise ValueError('Please provide 1 to 500 characters')
        body={'text':text,'speed':speed,'seed':seed,'temperature':temperature,'top_p':top_p}
        for name,value in [('gpt_id',gpt_id),('sovits_id',sovits_id),('reference_id',reference_id)]:
            value=value or self.catalog['defaults'][name]
            group={'gpt_id':'gpt_options','sovits_id':'sovits_options','reference_id':'references'}[name]
            if value not in [x['id'] for x in self.catalog[group]]:raise ValueError('Unknown '+name)
            body[name]=value
        with self._work_lock:
            generation=self._generation
            if _expected_generation is not None and _expected_generation!=generation:raise CancelledError()
            try:
                self.start(generation)
                data=self._request('/tts',body,timeout=180)
                if generation!=self._generation:raise CancelledError()
                with wave.open(io.BytesIO(data),'rb') as w:
                    if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=32000 or w.getnframes()<1:raise RuntimeError('Invalid synthesis WAV')
                    seconds=w.getnframes()/w.getframerate()
                p=self.state/'outputs'/(uuid.uuid4().hex+'.wav');p.parent.mkdir(exist_ok=True);p.write_bytes(data)
                if generation!=self._generation:p.unlink(missing_ok=True);raise CancelledError()
                return {'path':str(p),'seconds':seconds,'selection':{k:body[k] for k in ('gpt_id','sovits_id','reference_id')},'sha256':hashlib.sha256(data).hexdigest()}
            except Exception:
                self.stop_engine()
                if generation!=self._generation:raise CancelledError() from None
                raise
            finally:self._arm_idle_stop()
    def submit(self,text,**selection):
        with self._submit_lock:
            if self._closed:raise RuntimeError('Voice backend closed')
            if self._future is not None and not self._future.done():raise RuntimeError('Voice synthesis busy; cancel or wait for current job')
            self._future=self._executor.submit(self.synthesize,text,_expected_generation=self._generation,**selection);return self._future
    def cancel(self):
        with self._process_lock:self._generation+=1;self._stop_engine_locked()
        if self._future:self._future.cancel()
    def reply_and_speak(self,messages,**selection):
        # This key belongs exclusively to voice_dialogue. TTS never borrows it.
        generation=self._generation
        text=self.feature_apis.chat('voice_dialogue',messages)
        if generation!=self._generation:raise CancelledError()
        if len(text)>500:raise ValueError('Voice reply too long; reduce dialogue output')
        return dict(self.synthesize(text,_expected_generation=generation,**selection),text=text)
    def close(self):
        if self._playing:self.stop_playback()
        self._closed=True;self.cancel();self._executor.shutdown(wait=False,cancel_futures=True)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
