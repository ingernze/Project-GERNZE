"""Explicit desktop composition; no import-time persona overrides or source discovery."""
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
from workbench.companion_chat import NoRedirect
from .profile import prepare_profile,validate_profile
from .source import SelectedProgress
from .admission import AdmissionStore,AdmissionChat
from .summaries import SummaryContext,SummaryRunner


class AgentContext(SummaryContext):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runner=None
    def cancel(self):
        super().cancel()
        if self.runner is not None:self.runner.context.cancel()
    def summarize(self,store,session_id):
        if self.summarizer is None:return 'disabled'
        if session_id!=store.session_id:return 'cancelled'
        if self.runner is None:self.runner=SummaryRunner(self.runtime_chat,self.summarizer)
        self.runner.model=self.summarizer
        for key in ('timeout','keep_recent','batch','min_batch','summary_input_limit','summary_output_limit'):
            setattr(self.runner.context,key,getattr(self,key))
        return self.runner.run()


class AgentChat(AdmissionChat):
    context_class=AgentContext
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.context.runtime_chat=self
    def reply_request(self,text,*,request_id=None,origin='user',topic='unspecified'):
        # Only the host-selected keys are eligible; model/HTTP input cannot select
        # a source path, session, key, or a broader account-wide scope.
        return super().reply_request(text,request_id=request_id,origin=origin,topic=topic,
                                     select=self.agent_gate.reader is not None and origin=='user')


class AgentFactory:
    def __init__(self,profile,*,source_config=None,keys_backend=None,http=None,core_loader=None):
        # Reject invalid source configuration before creating any profile files.
        self.reader=SelectedProgress(source_config) if source_config is not None else None
        self.profile,self.ident=prepare_profile(profile)
        self.keys_backend=keys_backend;self.http=http;self.core_loader=core_loader
        if self.reader is not None and self.reader.path.is_relative_to(self.profile):
            raise ValueError('Agent来源须与桌面资料目录分开。')
    def __call__(self,path,*,memories=None,encounter_enabled=False,encounter_directory=None,
                 research_enabled=False,keys=None):
        validate_profile(self.profile,self.ident)
        if Path(path)!=self.profile/'workbench/chat.json':
            raise ValueError('Agent聊天入口不能接管其他资料目录。')
        if research_enabled:
            raise ValueError('Agent入口与研究会话暂不共用写入库。')
        if self.reader is not None:self.reader.validate_selection()
        from research_preview import PreviewKeys
        scoped_keys=PreviewKeys(self.profile,self.ident,keys if keys is not None else self.keys_backend)
        provider=None
        if encounter_enabled:
            from workbench.encounter_provider import LocalEncounterProvider
            provider=LocalEncounterProvider(encounter_directory,enabled=True)
        store=AdmissionStore(self.profile/'workbench/agent-chat-sessions.sqlite3',
                             profile=self.profile,core_loader=self.core_loader)
        http=self.http if self.http is not None else build_opener(ProxyHandler({}),NoRedirect())
        chat=AgentChat(path,store=store,reader=self.reader,keys=scoped_keys,http=http,
                       memories=memories,encounter_provider=provider)
        from .transfer import binding
        with store.connection() as db:
            store._owner(db)
            store._set(db,'ag_runtime_binding',binding(self.ident,self.reader))
        return chat
