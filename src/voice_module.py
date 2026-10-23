"""Desktop voice bridge. No widgets, Torch imports, startup network or autoplay."""
from pathlib import Path
import copy,importlib.util,json,os,queue,threading,uuid
from concurrent.futures import CancelledError


def locate_home(root):
    from optional_modules import OptionalModules
    modules=OptionalModules(root,Path(root))
    if modules.managed:return modules.voice_home()
    override=os.environ.get('HECATE_VOICE_MODULE_DIR')
    if override:return Path(override).resolve()
    for parent in (Path(root).resolve(),*Path(root).resolve().parents):
        home=parent/'voice_engine'
        if (home/'catalog.json').is_file():return home
        migrated=parent/'启动版'/'可选模块'/'voice_engine'
        if (migrated/'catalog.json').is_file():return migrated
    raise FileNotFoundError('独立语音模块尚未安装')


class VoiceModuleController:
    FEATURE='voice_dialogue'
    def __init__(self,pet,root,state,*,home=None,factory=None):
        self.pet=pet;self.root=Path(root);self.state=Path(state)
        self.home=Path(home).resolve() if home else None;self.factory=factory
        self._backend=None;self._worker=None;self._cleanup=None;self._cleanup_pending=False
        self._results=queue.SimpleQueue();self._cancel=threading.Event()
        self._generation=0;self._busy=False;self._closed=False
        self._selection=None;self._catalog=None
        self.status={'state':'idle','message':'语音后端待命；按需启动。'}
        self.last_result=None;self.on_change=None
    @property
    def busy(self):return self._busy or self._cleanup_pending
    def _update_status(self,status):
        self.status=status
        self.refresh_status()
    def refresh_status(self):
        self._assert_ui()
        if self.on_change is not None:self.on_change()
    def _assert_ui(self):
        if threading.get_ident()!=self.pet.ui_thread:raise RuntimeError('Voice bridge must run on the UI thread')
    def _load(self):
        if self._closed:raise RuntimeError('语音模块已关闭')
        if self._catalog is not None:return
        self.home=self.home or locate_home(self.root)
        catalog=json.loads((self.home/'catalog.json').read_text(encoding='utf-8-sig'))
        if not all(catalog.get(key) for key in ('gpt_options','sovits_options','references')):
            raise ValueError('语音引擎已安装；请先按模块内说明导入 GPT、SoVITS 权重和参考音频。')
        selected=dict(catalog['defaults'])
        self._catalog=catalog
        saved=self.state/'voice_module_settings.json'
        try:
            candidate=json.loads(saved.read_text(encoding='utf-8-sig'))
            self._validate(candidate);selected=candidate
        except (OSError,ValueError,KeyError,TypeError):pass
        self._selection=selected
    def _validate(self,selection):
        if not isinstance(selection,dict) or set(selection)!={'gpt_id','sovits_id','reference_id'}:raise ValueError('需要分别选择 GPT、SoVITS 和参考音频')
        for key,group in [('gpt_id','gpt_options'),('sovits_id','sovits_options'),('reference_id','references')]:
            if selection[key] not in [item['id'] for item in self._catalog[group]]:raise ValueError('未知语音选项：'+key)
        gpt=next(x for x in self._catalog['gpt_options'] if x['id']==selection['gpt_id'])
        sovits=next(x for x in self._catalog['sovits_options'] if x['id']==selection['sovits_id'])
        if gpt.get('version')!=sovits.get('version'):raise ValueError('GPT 和 SoVITS 的版本不兼容')
    def choices(self):
        self._assert_ui();self._load()
        return copy.deepcopy({key:self._catalog[key] for key in ['gpt_options','sovits_options','references']})
    def selection(self):
        self._assert_ui();self._load();return dict(self._selection)
    def set_selection(self,*,gpt_id,sovits_id,reference_id):
        self._assert_ui();self._load()
        selected=dict(gpt_id=gpt_id,sovits_id=sovits_id,reference_id=reference_id);self._validate(selected)
        self.state.mkdir(parents=True,exist_ok=True)
        target=self.state/'voice_module_settings.json';pending=target.with_name(uuid.uuid4().hex+'.tmp')
        try:
            pending.write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf8');pending.replace(target)
        finally:pending.unlink(missing_ok=True)
        self._selection=selected;return self.selection()
    def fixed_scenes(self):
        self._assert_ui()
        return [{'id':c['id'],'text':c.get('text',''),'scene':c.get('scene',''),'model_label':'第一套' if c.get('model_code')=='A' else '第二套','preview_only':c['id'] in self.pet.voice.held_back} for c in self.pet.voice.clips.values()]
    def play_fixed(self,identifier):
        self._assert_ui()
        if self._closed:return False
        self.cancel();return self.pet.voice.preview(identifier)
    def _get_backend(self):
        self._load()
        if self._backend is None:
            if self.factory:self._backend=self.factory(self.home)
            else:
                spec=importlib.util.spec_from_file_location('_hecate_independent_voice',self.home/'voice_backend.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                self._backend=module.VoiceBackend(self.home)
        return self._backend
    def api_config(self):
        self._assert_ui();return self._get_backend().feature_apis.get(self.FEATURE)
    def configure_api(self,*,enabled,endpoint,model,key=None):
        self._assert_ui();apis=self._get_backend().feature_apis
        apis.configure(self.FEATURE,enabled=enabled,endpoint=endpoint,model=model)
        if key is not None:apis.save_key(self.FEATURE,key)
        return self.api_config()
    def delete_api_key(self):
        self._assert_ui();self.cancel();self._get_backend().feature_apis.delete_key(self.FEATURE)
    def _available(self,play):
        if self._closed or self.pet.closing:raise RuntimeError('语音模块已关闭')
        if self.busy:raise RuntimeError('上一条语音正在处理或取消，请稍后再试')
        if play and (not self.pet.voice.enabled() or self.pet.voice.volume()==0):raise RuntimeError('请先显示莉宝、取消静音并调高音量')
    def speak_text(self,text,*,play=True):
        self._assert_ui()
        if not isinstance(text,str) or not text.strip() or len(text)>500:raise ValueError('请输入 1 至 500 字的文本')
        return self._begin(text,None,play)
    def dialogue(self,messages,*,play=True):
        self._assert_ui()
        if not isinstance(messages,list) or not messages or len(messages)>50:raise ValueError('需要有效的对话内容')
        for item in messages:
            if not isinstance(item,dict) or item.get('role') not in ('user','assistant','system') or not isinstance(item.get('content'),str):raise ValueError('对话格式不正确')
        if len(json.dumps(messages,ensure_ascii=False).encode('utf8'))>64000:raise ValueError('对话内容过长')
        self._available(play)
        if not self.api_config()['enabled']:raise RuntimeError('声音对话的专用 API 尚未启用')
        return self._begin(None,copy.deepcopy(messages),play)
    def _begin(self,text,messages,play):
        self._available(play);backend=self._get_backend();selected=dict(self._selection)
        expected=backend._generation
        self._generation+=1;generation=self._generation
        cancel=self._cancel=threading.Event();self._busy=True;self.last_result=None
        self._update_status({'state':'generating','message':'正在生成语音。'})
        def work():
            result=None;error=None
            try:
                reply=text if messages is None else backend.feature_apis.chat(self.FEATURE,messages)
                if cancel.is_set():raise CancelledError()
                if not isinstance(reply,str) or not reply.strip() or len(reply)>500:raise ValueError('语音回复需要为 1 至 500 字')
                result=dict(backend.synthesize(reply,_expected_generation=expected,**selected),text=reply)
                if cancel.is_set():raise CancelledError()
            except CancelledError:error='cancelled'
            except Exception as exc:error=type(exc).__name__
            self._results.put((generation,result,error,play))
            if not self._closed:
                try:self.pet._enqueue_command('voice_module:drain')
                except Exception:pass
        self._worker=threading.Thread(target=work,name='HecateDesktopVoice',daemon=True);self._worker.start()
        return generation
    def drain(self):
        self._assert_ui()
        while True:
            try:generation,result,error,play=self._results.get_nowait()
            except queue.Empty:break
            self._busy=False
            if self._closed:continue
            if generation!=self._generation or error=='cancelled':
                self._update_status({'state':'cancelled','message':'已取消；不会播放迟到的结果。'});continue
            if error:
                self._update_status({'state':'error','message':'语音未完成，请检查独立后端日志。','error_type':error});continue
            self.last_result=result
            played=play and self.pet.voice.play_generated(result['path'],output_root=self.home/'state/outputs',sha256=result['sha256'],identifier='generated:'+str(generation))
            self._update_status({'state':'played' if played else 'ready','message':'已播放生成语音。' if played else '语音已生成；当前未播放。','played':bool(played)})
    def cancel(self):
        self._assert_ui();self._generation+=1;self._cancel.set();self.last_result=None
        self.pet.voice.stop('voice_module')
        if self._busy:self._update_status({'state':'cancelling','message':'正在取消；不会播放迟到的结果。'})
        elif not self._closed:self._update_status({'state':'stopped','message':'已停止。'})
        if self._backend is not None and not self._cleanup_pending:
            self._cleanup_pending=True;self.refresh_status()
            def cleanup():
                try:self._backend.cancel()
                finally:
                    self._cleanup_pending=False
                    if not self._closed:
                        try:self.pet._enqueue_command('voice_module:refresh')
                        except Exception:pass
            self._cleanup=threading.Thread(target=cleanup,name='HecateVoiceCancel',daemon=True);self._cleanup.start()
    def close_background(self):
        self._assert_ui()
        if self._closed:return self._cleanup
        self._closed=True;self._generation+=1;self._cancel.set()
        self._update_status({'state':'closed','message':'语音模块已关闭。'})
        if self._backend is not None:
            backend=self._backend
            self._cleanup=threading.Thread(target=backend.close,name='HecateModuleRelease',daemon=True)
            self._cleanup.start()
        return self._cleanup
    def close(self):
        self._assert_ui()
        if self._closed:return
        self._closed=True;self._generation+=1;self._cancel.set()
        if self._backend is not None:self._backend.close()
        self._update_status({'state':'closed','message':'语音模块已关闭。'})
