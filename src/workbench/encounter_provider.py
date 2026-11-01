"""Host-injected, read-only recall. No model tools, network, or host-memory writes."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import threading

if __package__:
    from .conversation_store import ChatStateError
else:
    from conversation_store import ChatStateError


@dataclass(frozen=True)
class EncounterContext:
    data: dict | None = None
    catalog_revision: int | None = None
    generation: int = 0
    status: str = 'disabled'
    mode: str = 'related'


def recent_question(text):
    """Whole-utterance sharing intent; no topic keywords or model classification.

    Deliberately conservative: instructions to rewrite/quote a question do not
    match. Ambiguous phrasings use related recall, never latest-record fallback.
    """
    text = text.strip().rstrip('？?。！!').strip()
    return any(re.fullmatch(pattern, text) for pattern in (
        r'(?:你)?(?:最近|这几天|刚才)(?:都)?(?:看|读|遇|接触)(?:到|过|了|到了)?(?:些|点)?(?:什么|啥)(?:有趣的)?(?:东西|内容|文章|见闻)?',
        r'(?:你)?(?:最近|这几天)(?:有)?(?:什么|啥)(?:新)?见闻',
        r'(?:说说|聊聊|分享一下)(?:你)?(?:最近|这几天)(?:的见闻|(?:看|读)到的(?:东西|内容|文章))',
    ))


class LocalEncounterProvider:
    """Enable and path are trusted host configuration, never model arguments.

    Initialization/expected read failures degrade to an unavailable provider.
    Once a block is adopted, validation failures fail closed for that answer.
    """
    def __init__(self, directory=None, *, enabled=False):
        self._lock = threading.RLock()
        self._generation = 0
        self._enabled = enabled is True
        self.store = self.chat = self.service = None
        if not self._enabled:
            return
        if directory is None or not Path(directory).is_absolute():
            raise ValueError('启用见闻须由宿主提供显式绝对目录。')
        from libao_browse.encounters import EncounterStore
        from libao_browse.encounter_chat import EncounterChat
        from libao_browse.security import BrowseError
        try:
            self.store = EncounterStore(Path(directory))
            self.chat = EncounterChat(self.store)
            self.service = self.chat.service
        except (OSError, sqlite3.Error, BrowseError, ValueError):
            self.store = self.chat = self.service = None

    def disable(self):
        with self._lock:
            self._enabled = False
            self._generation += 1

    def prepare(self, question):
        from libao_browse.encounter_service import _terms
        from libao_browse.security import BrowseError
        with self._lock:
            generation = self._generation
            if not self._enabled:
                return EncounterContext(generation=generation)
            if self.chat is None:
                return EncounterContext(generation=generation, status='unavailable')
        mode = 'recent' if recent_question(question) else 'related'
        def empty(status):
            return EncounterContext(generation=generation, status=status, mode=mode)
        try:
            main = self.chat.recall(question, mode=mode, max_items=3, max_chars=2200)
            # Reflections are bounded separately by the existing API. It does
            # not filter by query; filter here, never use it as unrelated fill.
            reflections = self.chat.recall(mode='reflections', max_items=3, max_chars=1000)
            if not main.get('ok') or not reflections.get('ok'):
                return empty('unavailable')
            primary, selected = main['result'], reflections['result']
            wanted = _terms(question)
            ids = {(i['id'], i['revision']) for i in primary['items']}
            relevant = []
            for item in selected['items']:
                prose = ' '.join(item.get(k, '') for k in
                                 ('title', 'understandingRevision', 'nextResponse'))
                if ((item['id'], item['revision']) in ids or
                        (mode == 'related' and wanted & _terms(prose))):
                    relevant.append(item)
            # Keep at most three distinct sources, prioritizing ordinary hits.
            allowed = set(ids)
            bounded = []
            for item in relevant:
                key = (item['id'], item['revision'])
                if key in allowed or len(allowed) < 3:
                    allowed.add(key)
                    bounded.append(item)
            relevant = bounded
            if not primary['items'] and not relevant:
                return empty('no_results')
            if (primary['catalogRevision'] != selected['catalogRevision']):
                return empty('invalidated')
            catalog = primary['catalogRevision']
            data = {'trust': 'external_untrusted', 'hostMemoryLayer': None,
                    'mode': mode, 'catalogRevision': catalog,
                    'items': primary['items'], 'selectedReflections': relevant}
            return EncounterContext(data, catalog, generation, 'ready', mode)
        except (OSError, sqlite3.Error, BrowseError, ValueError, TypeError, KeyError):
            return empty('unavailable')

    @contextmanager
    def publication_guard(self, prepared):
        """Linearize validation + chat completion against ledger writers.

        SQLite BEGIN IMMEDIATE covers different Store instances/processes too.
        This short gate is never held during HTTP or model execution. Lock order
        is host chat guard -> provider -> encounter store/SQLite -> chat store.
        """
        if prepared.data is None:
            yield
            return
        try:
            with self._lock:
                if not self._enabled or self._generation != prepared.generation:
                    raise ChatStateError('external_context_stale', '见闻已停用，这条回复已作废。')
                with self.store.lock, self.store.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    check = self.service.dispatch('encounters.context.validate', {
                        'catalogRevision': prepared.catalog_revision})
                    if not check.get('ok') or check['result'].get('current') is not True:
                        raise ChatStateError('external_context_stale', '见闻来源已变化，这条回复已作废。')
                    yield
        except (OSError, sqlite3.Error):
            raise ChatStateError('external_validation_failed', '见闻版本暂时无法核对，这条回复已作废。') from None
