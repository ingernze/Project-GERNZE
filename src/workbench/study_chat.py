"""Authenticated host's explicit, one-request research selection adapters.

No text classifier, persistent lease, token returned to the browser or model
tool exists here. ResearchProvider remains opt-in at product composition.
"""
import re

from .research_catalog import ResearchAccess, META_COLUMNS, ids, uid


class StudyChat:
    def __init__(self, chat):
        self.chat = chat

    def status(self):
        provider = self.chat.research_provider
        return {'available': provider is not None and provider.available(),
                'maxMaterials': 8, 'scope': 'one_request'}

    def reply(self, text, request_id, materials):
        return self._reply(text, request_id, materials, 'study')

    def _reply(self, text, request_id, materials, restriction):
        label = '课程' if restriction == 'study' else '研究'
        if not self.status()['available']:
            raise ValueError(f'当前版本尚未启用{label}对话，资料仍可从书架查看。')
        if type(text) is not str or not text.strip() or len(text) > 1000:
            raise ValueError('请输入1～1000字。')
        uid(request_id)
        if type(materials) is not list or not 1 <= len(materials) <= 8:
            raise ValueError(f'请选择本次提问需要的{label}资料。')
        refs = []
        for item in materials:
            if type(item) is not dict or set(item) != {'id', 'revision'}:
                raise ValueError(f'{label}资料选择无效。')
            refs.append((uid(item['id']), uid(item['revision'])))
        if len({i for i, _ in refs}) != len(refs):
            raise ValueError(f'{label}资料重复。')
        provider = self.chat.research_provider
        if provider.DENY.search(re.sub(r'\s+', '', text)):
            return self.chat.reply_request(text, request_id=request_id)
        with self.chat.guard:
            session_id = self.chat.store.session_id
        # Look up classification and exact scope on the host. HTTP supplies no
        # scene/course UUID, trust or grant. Do not read ANY body here.
        with provider.catalog.connection() as db:
            provider.catalog._ready(db)
            courses = set()
            for ident, revision in refs:
                row = db.execute('SELECT ' + META_COLUMNS + ' FROM rc_entries WHERE id=?', (ident,)).fetchone()
                if row is None:
                    raise ValueError(f'{label}资料已变化，请重新从书架选择。')
                meta = provider.catalog._metadata(db, row)
                if meta['state'] != 'active' or meta['revision'] != revision or meta['restriction'] != restriction:
                    raise ValueError(f'{label}资料已变化或不属于本次用途。')
                courses.update(meta['courses'])
            access = ResearchAccess('study', ids(tuple(courses))) if restriction == 'study' else ResearchAccess()
            provider.catalog._selected(db, refs, access, 64000)
        # Context-local scope cannot leak to a simultaneous ordinary request.
        # It is bound to the exact text, ID and session, and reset on every exit.
        with provider.host_selection(text, request_id, session_id, refs, access):
            return self.chat.reply_request(text, request_id=request_id)


class ResearchChat(StudyChat):
    """General-only host selection. Cannot grant access to course material."""
    def reply(self, text, request_id, materials):
        return self._reply(text, request_id, materials, 'general')
