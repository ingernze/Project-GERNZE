"""Provider-neutral, explicit-send companion chat. No startup network or tools."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import uuid

if __package__:
    from .companion_memory import validate as validate_note
    from .context_manager import Budget, ContextManager
    from .conversation_store import ConversationStore, ChatStateError, SCOPES, encoded, uid
    from .memory_layers import MemoryLayers
else:
    from companion_memory import validate as validate_note
    from context_manager import Budget, ContextManager
    from conversation_store import ConversationStore, ChatStateError, SCOPES, encoded, uid
    from memory_layers import MemoryLayers

DEFAULTS = {'enabled': False, 'endpoint': 'https://api.deepseek.com/chat/completions', 'model': 'deepseek-flash'}
# Character facts are kept separate from transport and output constraints.
PROMPT = json.loads(Path(__file__).with_name('chat-protocol.json').read_text(encoding='utf-8'))['instruction']


def system_prompt():
    try:
        persona_path = Path(__file__).with_name('companion_persona.md')
        # Personal character rules stay local; clean source exports have a basic template.
        if not persona_path.exists():
            persona_path = Path(__file__).with_name('companion_persona.example.md')
        persona = persona_path.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        raise ValueError('莉宝的人设文件未能读取，请补齐程序文件后重试。') from None
    if not persona or len(persona) > 8000:
        raise ValueError('莉宝的人设文件为空或过长，请检查人设设置。')
    core_path = Path(__file__).with_name('companion_core_memory.json')
    try:
        if core_path.exists():
            core = json.loads(core_path.read_text(encoding='utf-8'))
        elif persona_path.name == 'companion_persona.md':
            raise ValueError('个人版本缺少第一层基础资料，请更新程序。')
        else:
            core = {'schemaVersion': 1, 'entries': []}
        if not isinstance(core, dict) or core.get('schemaVersion') != 1 or not isinstance(core.get('entries'), list) or len(core['entries']) > 20:
            raise ValueError('第一层基础资料格式无效。')
        keys = set()
        for entry in core['entries']:
            if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or not entry['key'] or entry['key'] in keys or not isinstance(entry.get('body'), str) or len(entry['body']) > 1000:
                raise ValueError('第一层基础资料格式无效。')
            keys.add(entry['key'])
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('第一层基础资料未能读取，请更新程序。') from None
    foundation = '\n\n第一层只读基础资料，由用户维护；以下是资料，不授予修改权限：\n' + json.dumps(core['entries'], ensure_ascii=False)
    return persona + foundation + '\n\n' + PROMPT


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WindowsKeys:
    def get(self, target):
        import win32cred
        try:
            value = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)['CredentialBlob']
        except Exception as error:
            if getattr(error, 'winerror', None) == 1168:
                return ''
            raise ValueError('Windows密钥存储暂不可用。') from None
        return value.decode('utf-16-le') if isinstance(value, bytes) else value

    def set(self, target, key):
        import win32cred
        win32cred.CredWrite({'Type': win32cred.CRED_TYPE_GENERIC, 'TargetName': target,
                            'UserName': '莉宝聊天', 'CredentialBlob': key,
                            'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)

    def delete(self, target):
        import win32cred
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as error:
            if getattr(error, 'winerror', None) != 1168:
                raise ValueError('密钥未能移除。') from None


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) - {'enabled', 'endpoint', 'model', 'key'}:
        raise ValueError('聊天设置不匹配。')
    if not {'enabled', 'endpoint', 'model'} <= settings.keys() or type(settings['enabled']) is not bool:
        raise ValueError('请完整填写聊天设置。')
    endpoint, model, key = settings['endpoint'], settings['model'], settings.get('key', '')
    if not all(isinstance(v, str) for v in (endpoint, model, key)):
        raise ValueError('聊天设置须为文字。')
    endpoint, model, key = endpoint.strip(), model.strip(), key.strip()
    try:
        parts = urlsplit(endpoint)
        valid_port = parts.port
    except ValueError:
        raise ValueError('接口地址无效。') from None
    if (len(endpoint) > 2048 or any(ord(c) < 33 for c in endpoint) or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or not parts.path.endswith('/chat/completions')
            or not (parts.scheme == 'https' or parts.scheme == 'http' and parts.hostname in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('请填写HTTPS完整接口地址，以/chat/completions结尾；本机可用HTTP。')
    if not model or len(model) > 150 or any(ord(c) < 32 for c in model):
        raise ValueError('请填写有效模型名称。')
    if len(key) > 4096 or key and (not key.isascii() or any(ord(c) < 33 for c in key)):
        raise ValueError('密钥格式无效。')
    return {'enabled': settings['enabled'], 'endpoint': endpoint, 'model': model}, key


def normalized_reply(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError('服务没有返回回复文字。')
    text = content.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        value = json.loads(text)
    except ValueError:
        value = {'text': text}
    if not isinstance(value, dict) or not isinstance(value.get('text'), str) or not value['text'].strip():
        raise ValueError('回复格式不完整，请重试。')
    return {'text': value['text'].strip()[:4000],
            'emotion': value.get('emotion') if value.get('emotion') in ('normal', 'happy', 'annoyed') else 'normal',
            'action': 'sway' if value.get('action') == 'sway' else 'none'}


class CompanionChat:
    def __init__(self, path, *, keys=None, opener=None, memories=None, store=None, context=None):
        self.path = Path(path)
        self.keys = keys or WindowsKeys()
        self.http = opener or build_opener(ProxyHandler({}), NoRedirect())
        self.guard = threading.RLock()
        self.sending = threading.Lock()
        self.active_request = None
        self.cancelled_request_ids = set()
        self.history = []
        self.memories = memories
        self.revision = 0
        self.store = store or ConversationStore(self.path.with_name('chat-sessions.sqlite3'))
        if memories and self.store.path.resolve() == memories.path.resolve():
            raise ValueError('会话库必须与原记忆库分开。')
        # Application estimate cap, not a claim about the configured model's window.
        # UTF-8 conservative counting must fit the full persona and selected notes.
        # Callers targeting smaller windows must inject their matching Budget/counter.
        self.context = context if context is not None else ContextManager(budget=Budget(context_window=32768))
        self.layers = MemoryLayers(self.store)
        self.last_context = {}
        self._sync_notes()
        self._restore_history()

    def _config(self):
        if not self.path.exists():
            return dict(DEFAULTS)
        raw = self.path.read_bytes()
        if len(raw) > 8192:
            raise ValueError('聊天设置文件过大。')
        config, _ = validate_settings(json.loads(raw))
        return config

    def _target(self, config):
        return 'Hecate/CompanionChat/' + hashlib.sha256(config['endpoint'].encode()).hexdigest()[:32]

    def config(self):
        with self.guard:
            config = self._config()
            try:
                present = bool(self.keys.get(self._target(config)))
            except (ImportError, ValueError, OSError):
                present = False
            return {**config, 'key_present': present, 'configured': config['enabled'] and present}

    def configure(self, settings):
        config, key = validate_settings(settings)
        with self.guard:
            if self.sending.locked():
                raise ValueError('正在回复，请等待结束后再修改设置。')
            target = self._target(config)
            if config['enabled'] and not key and not self.keys.get(target):
                raise ValueError('启用前请填写这个接口的密钥。')
            if key:
                self.keys.set(target, key)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temporary.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.revision += 1
            self.context.cancel()
            self.store.retire_context('configuration_changed')
            self.history.clear()
            return self.config()

    def delete_key(self):
        with self.guard:
            self.keys.delete(self._target(self._config()))
            self.revision += 1
            self.context.cancel()
            self.store.retire_context('configuration_changed')
            self.history.clear()
            return self.config()

    def _restore_history(self):
        self.history=[{'role':m['role'],'content':m['content']} for p in self.store.recent(self.store.session_id) for m in p['messages']]

    def _all_notes(self):
        # Legacy notes remain untouched and browsable, never implicitly approved.
        return self.layers.context_notes()

    @staticmethod
    def _fingerprint(notes):
        return hashlib.sha256(encoded(sorted([(n['id'],n['revision'],n['chat_enabled'],n['important']) for n in notes])).encode()).hexdigest()

    def _sync_notes(self):
        notes=self._all_notes()
        if self.store.observe_notes(self._fingerprint(notes)):
            self.revision+=1;self.history.clear();self.context.cancel()
        return notes

    def _usable_notes(self,notes):
        pending=self.store.pending_changes()
        if any(c['note_id'] is None for c in pending):return []
        blocked={c['note_id'] for c in pending}
        return [n for n in notes if n['id'] not in blocked]

    def cancel(self,request_id=None):
        with self.guard:
            if request_id is not None:
                uid(request_id);self.cancelled_request_ids.add(request_id)
                if self.active_request!=request_id:return {'cancelled':True}
            elif self.active_request is not None:self.cancelled_request_ids.add(self.active_request)
            self.revision+=1;self.context.cancel();self.store.cancel_pending()
        return {'cancelled':True}

    def change_memory(self,params,*,forget=False):
        raise ValueError('旧手工记忆入口已移除；请在待审摘要中审查，或对已审记忆纠正/撤回。')

    def review_layers(self, decisions):
        with self.guard:
            self.cancel()
            result=self.layers.decide(decisions)
            self._sync_notes()
            return result

    def change_approved(self,key,revision,*,text=None,withdraw=False):
        with self.guard:
            self.cancel()
            result=self.layers.change_approved(key,revision,text=text,withdraw=withdraw)
            self._sync_notes()
            return result

    def _change_memory(self,params,*,forget=False,metadata=None):
        raise ValueError('旧主动笔记已只读保留；新版记忆请通过摘要审核或已审纠正处理。')

    def review_pending_change(self,operation_id,*,confirmed=False,note_id=None,applied=True):
        """Caller must inspect current notes and scope before explicitly acknowledging."""
        if confirmed is not True or type(applied) is not bool:raise ValueError('请先人工核对当前记忆和来源范围。')
        with self.guard:
            notes=self._sync_notes();pending=next((r for r in self.store.pending_changes() if r['id']==operation_id),None)
            if pending is None:raise ValueError('没有这个待核对操作。')
            target=note_id or pending['note_id']
            note=next((n for n in notes if n['id']==target),None)
            if applied and pending['note_id'] is None and note is None:raise ValueError('请指出实际新增的记忆编号，或明确标记未应用。')
            if note_id is not None and (note is None or pending['note_id'] not in (None,note_id)):raise ValueError('核对目标不匹配。')
            self.store.acknowledge_change(operation_id,note=note,applied=applied)
        return {'reviewed':True}

    def _validate_proposal(self,proposal):
        fields={'note','source_ids','scope','event_state','target_id','target_revision','request_id'}
        if type(proposal) is not dict or set(proposal)!=fields:raise ValueError('纠正候选字段不完整。')
        p=dict(proposal);p['note']=validate_note(p['note'])
        if type(p['scope']) is not str or type(p['event_state']) is not str or p['scope'] not in SCOPES or p['event_state'] not in {'planned','occurred','unspecified'}:raise ValueError('候选范围或事件状态无效。')
        self.store.source_messages(p['source_ids'],session_id=self.store.session_id)
        if (p['target_id'] is None)!=(p['target_revision'] is None):raise ValueError('替代关系须含编号和版本。')
        if p['target_id'] is not None:
            uid(p['target_id']);uid(p['target_revision'])
            if not any(n['id']==p['target_id'] and n['revision']==p['target_revision'] for n in self._all_notes()):raise ValueError('替代目标已删除或版本过时。')
        if p['scope'] in {'session','turn'} and p['target_id'] is not None:raise ValueError('局部偏好不能替换长期记忆。')
        if p['scope'] in {'session','turn'} and not p['note']['chat_enabled']:raise ValueError('局部要求未启用上下文，不予接入。')
        if p['scope']=='turn':
            uid(p['request_id'])
            with self.store.connection() as db:
                if db.execute('SELECT 1 FROM lc_turns WHERE id=?',(p['request_id'],)).fetchone():raise ValueError('局部要求须指向尚未发送的新请求。')
        elif p['request_id'] is not None:raise ValueError('只有turn范围可指定请求编号。')
        return p

    def propose_memory(self,proposal):
        with self.guard:
            self._sync_notes();p=self._validate_proposal(proposal)
            return {'candidate_id':self.store.add_candidate(self.store.session_id,p),'confirmed':False}

    def confirm_memory(self,candidate_id,*,confirmed=False):
        if confirmed is not True:raise ValueError('候选必须由用户明确确认。')
        with self.guard:
            self._sync_notes();row=self.store.candidate(candidate_id)
            if row['session_id']!=self.store.session_id:raise ValueError('请在来源会话内确认。')
            p=self._validate_proposal(row['payload'])
            if p['scope'] in {'session','turn'}:
                self.revision+=1;self.context.cancel();self.history.clear();self.store.cancel_pending()
                result={'directive_id':self.store.add_directive(self.store.session_id,p),'scope':p['scope']}
            else:
                meta={k:p[k] for k in ('scope','event_state','source_ids')};meta['correction']=p['target_id'] is not None
                result=self._change_memory({'id':p['target_id'],'revision':p['target_revision'],'note':p['note']},metadata=meta)
            self.store.remove_candidate(candidate_id)
            return result

    def extract_candidates(self,source_ids,extractor):
        """Explicit, caller-injected extraction. No startup/background extraction, no automatic confirmation."""
        with self.guard:
            config=self._config()
            if not config['enabled']:raise ValueError('聊天API关闭，未调用抽取器。')
            self._sync_notes();sources=self.store.source_messages(source_ids,session_id=self.store.session_id)
            revision=self.revision;epoch=self.store.epoch()
        proposals=extractor([{'id':m['id'],'origin':m['origin'],'content':m['content']} for m in sources])
        if type(proposals) is not list or len(proposals)>4:raise ValueError('抽取器最多返回4个候选。')
        with self.guard:
            self._sync_notes()
            if self.revision!=revision or self.store.epoch()!=epoch:raise ValueError('抽取来源已变化。')
            validated=[self._validate_proposal(p) for p in proposals]
            if any(not set(p['source_ids'])<=set(source_ids) for p in validated):raise ValueError('抽取器引入了请求范围外的来源。')
            return [{'candidate_id':self.store.add_candidate(self.store.session_id,p),'confirmed':False} for p in validated]

    def select_session(self,session_id=None):
        with self.guard:
            self.revision+=1;self.context.cancel();result=self.store.select_session(session_id);self._restore_history()
            return {'session_id':result}

    def _forget_derived(self,source_ids):
        policies=self.store.note_policies()
        for note in self._all_notes():
            if set(policies.get(note['id'],{}).get('source_ids',[]))&set(source_ids):
                self._change_memory({'id':note['id'],'revision':note['revision']},forget=True)

    def remove_source(self,message_id):
        with self.guard:
            # Purge a whole turn, including notes derived from either message.
            with self.store.connection() as db:
                row=db.execute('SELECT turn_id FROM lc_messages WHERE id=?',(uid(message_id),)).fetchone()
                if not row:raise ValueError('来源不存在。')
                ids=[r[0] for r in db.execute('SELECT id FROM lc_messages WHERE turn_id=?',(row[0],))]
            self._forget_derived(ids);self.revision+=1;self.context.cancel();self.history.clear()
            self.store.remove_source(message_id)
        return {'removed':True,'raw_history_policy':'matching_turn_purged_other_history_masked'}

    def delete_session(self,session_id):
        with self.guard:
            with self.store.connection() as db:
                self.store._session(db,session_id)
                ids=[r[0] for r in db.execute('SELECT id FROM lc_messages WHERE session_id=?',(session_id,))]
            self._forget_derived(ids);self.revision+=1;self.context.cancel();self.history.clear()
            current=self.store.delete_session(session_id)
        return {'deleted':True,'session_id':current}

    def reply(self,text):
        value=self.reply_request(text)
        return {k:v for k,v in value.items() if k in {'text','emotion','action','memory_refs'}}

    def reply_request(self,text,*,request_id=None,origin='user',topic='unspecified'):
        if not isinstance(text,str) or not text.strip() or len(text)>1000:raise ValueError('请输入1～1000字。')
        text=text.strip();begun=False
        with self.guard:
            if request_id is not None and request_id in self.cancelled_request_ids:raise ChatStateError('cancelled','此请求已停止。')
            config=self._config();key=self.keys.get(self._target(config)) if config['enabled'] else ''
            if not config['enabled'] or not key:raise ValueError('请先配置并启用聊天API。')
            notes=self._sync_notes()
            if not self.sending.acquire(blocking=False):raise ValueError('上一条请求还未结束，请稍等。')
        try:
            with self.guard:
                # Key deletion may have happened between acquiring sending and entering this block.
                config=self._config();key=self.keys.get(self._target(config)) if config['enabled'] else ''
                if not config['enabled'] or not key:raise ValueError('请先配置并启用聊天API。')
                notes=self._sync_notes()
                if request_id is None:
                    request_id=(self.store.reusable_request(self.store.session_id,text) if origin=='user' and topic=='unspecified' else None) or str(uuid.uuid4())
                if request_id in self.cancelled_request_ids:raise ChatStateError('cancelled','此请求已停止。')
                turn=self.store.begin_turn(self.store.session_id,text,request_id,origin,topic)
                if 'cached' in turn:
                    cached=turn['cached'];refs=[{'id':n['id'],'title':n['title']} for n in self._usable_notes(notes) if n['id'] in cached['ref_ids'] and n['chat_enabled']]
                    value={k:cached[k] for k in ('text','emotion','action','request_id','message_id','session_id')}
                    if refs:value['memory_refs']=refs
                    self.last_context={'summary_status':'cached','complete_history':False};return value
                begun=True;self.active_request=request_id;revision=self.revision;epoch=self.store.epoch();session_id=self.store.session_id
            summary_status=self.context.summarize(self.store,session_id)
            with self.guard:
                notes=self._sync_notes()
                if self.revision!=revision or self.store.epoch()!=epoch:raise ChatStateError('stale_reply','已停止等待这条回复。')
                messages,refs,report=self.context.build(self.store,session_id,request_id,system_prompt()+self.layers.permission_prompt(),text,
                    self._usable_notes(notes),self.store.note_policies(),origin=origin,topic=topic,summary_status=summary_status)
                self.last_context=report
            payload={'model':config['model'],'messages':messages,'stream':False,'max_tokens':700}
            if urlsplit(config['endpoint']).hostname=='api.deepseek.com':payload['thinking']={'type':'disabled'}
            request=Request(config['endpoint'],data=json.dumps(payload,ensure_ascii=False).encode(),
                            headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
            try:
                with self.http.open(request,timeout=60) as response:raw=response.read(1_048_577)
                if len(raw)>1_048_576:raise ValueError('回复过长，请缩短问题后重试。')
                choice=json.loads(raw)['choices'][0]
                if choice.get('finish_reason') not in (None,'stop'):raise ValueError('这次回复未完整生成，请重试。')
                reply=normalized_reply(choice['message']['content'])
            except HTTPError as error:
                errors={401:'密钥未获认可，请检查聊天设置。',402:'服务余额不足，请检查账户。',429:'请求过于频繁，请稍后再试。'}
                raise ValueError(errors.get(error.code,'聊天服务暂未完成请求，请稍后重试。')) from None
            except (ValueError,TypeError,KeyError,IndexError):raise ValueError('回复未完整返回，请稍后重试。') from None
            except Exception:raise ValueError('聊天连接未完成，请检查网络和接口设置。') from None
            with self.guard, (self.memories.external_gate() if hasattr(self.memories,'external_gate') else nullcontext()):
                self._sync_notes()
                if self.revision!=revision:raise ChatStateError('stale_reply','已停止等待这条回复。')
                assistant_id=self.store.complete(request_id,reply,epoch,[r['id'] for r in refs]);self._restore_history()
                if refs:reply['memory_refs']=refs
                return {**reply,'request_id':request_id,'message_id':assistant_id,'session_id':session_id}
        except Exception as error:
            if begun:self.store.fail(request_id,getattr(error,'code','request_failed'))
            raise
        finally:
            with self.guard:
                if self.active_request==request_id:self.active_request=None
            self.sending.release()

