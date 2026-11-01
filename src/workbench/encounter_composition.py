"""Runnable composition used by the host, without Codex/MCP/browser dependencies."""
from .companion_chat import CompanionChat
from .encounter_provider import LocalEncounterProvider


def create_desktop_chat(path, *, encounter_enabled=False, encounter_directory=None, research_enabled=False, **chat_options):
    # OFF means no encounter store imports, directory creation, or DB opening.
    provider = (LocalEncounterProvider(encounter_directory, enabled=True)
                if encounter_enabled is True else None)
    research=None
    if research_enabled is True:
        from pathlib import Path
        from .research_context import ResearchJournal, ResearchProvider
        if chat_options.get('store') is not None:
            raise ValueError('研究接线须使用支持依赖校验的会话库。')
        store=ResearchJournal(Path(path).with_name('chat-sessions.sqlite3'))
        chat_options['store']=store
        research=ResearchProvider(store)
    return CompanionChat(path, encounter_provider=provider, research_provider=research, **chat_options)
