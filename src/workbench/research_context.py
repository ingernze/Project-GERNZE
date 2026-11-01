"""Opt-in desktop wiring with actual journal transactions and lazy history.

Explicit host UI adapter lives in study_chat; no legacy reclassification or model tools.
Research-bearing turns use separate scoped deltas and attributed review receipts;
legacy user-fact L3/L2 still exclude them. Negotiated phone caches remain read-only.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import re
import threading
import uuid

from .context_manager import conservative_count
from .conversation_store import ConversationStore, ChatStateError, encoded, uid
from .research_catalog import ResearchAccess, ResearchCatalog, ResearchError


FIELDS = ('id', 'revision', 'body_hash', 'source_versions', 'restriction', 'courses')


def exposure(meta):
    return {key: meta[key] for key in FIELDS}


def merge_exposures(groups):
    result = {}
    for group in groups:
        for item in group:
            if type(item) is not dict or set(item) != set(FIELDS):
                raise ResearchError('invalid_exposure_manifest')
            previous = result.get(item['id'])
            if previous is not None and previous != item:
                raise ResearchError('inconsistent_exposure_versions')
            result[item['id']] = item
    if len(result) > 64:
        raise ResearchError('exposure_manifest_too_large')
    return [result[key] for key in sorted(result)]


@dataclass
class RequestScope:
    request_id: str
    session_id: str
    access: ResearchAccess = ResearchAccess()
    refs: tuple = ()
    input_only: bool = False
    manifest: list = field(default_factory=list)
    summary_refs: list = field(default_factory=list)
    validate_host: object = lambda: None
    publication_guard: object = nullcontext

    def fingerprint(self):
        return encoded({'policy': 1, 'scene': self.access.scene,
                        'courses': self.access.courses, 'refs': self.refs,
                        'input_only': self.input_only})


class ResearchJournal(ConversationStore):
    # Old installed binaries reject version 4 instead of replaying scoped text
    # without a gate. Only this explicit opt-in writer upgrades the version.
    SUPPORTED_VERSIONS = (0, 1, 2, 3, 4)

    def __init__(self, path, *, trace=None):
        self.trace = trace
        self.scope = ContextVar('research_request_' + str(uuid.uuid4()), default=None)
        self.summary_filter = ContextVar('research_summary_' + str(uuid.uuid4()), default=False)
        super().__init__(path)
        self.catalog = ResearchCatalog(self.path, trace=trace)
        self.catalog.initialize()
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS rc_exposures(turn_id TEXT PRIMARY KEY,scope TEXT NOT NULL,payload TEXT NOT NULL)')
            from .research_summaries import ResearchSummaries
            ResearchSummaries.initialize(db)
            from .phone_research_summaries import initialize
            initialize(db)
            db.execute('PRAGMA user_version=4')
        self.research_summaries = ResearchSummaries(self)

    @contextmanager
    def connection(self):
        with super().connection() as db:
            if self.trace is not None:
                db.set_trace_callback(self.trace)
            yield db

    @contextmanager
    def read_connection(self):
        with super().read_connection() as db:
            if self.trace is not None:
                db.set_trace_callback(self.trace)
            yield db

    def scoped_summary_store(self, keep_recent, batch, minimum=3):
        return self.research_summaries.proxy(keep_recent, batch, minimum)

    def phone_summary_store(self,keep_recent,batch,minimum,input_limit):
        from .phone_research_summaries import proxy
        return proxy(self,keep_recent,batch,minimum,input_limit)

    def research_input_only(self):
        current = self.scope.get()
        return bool(current and current.input_only)

    def _record(self, db, turn_id):
        row = db.execute('SELECT scope,payload FROM rc_exposures WHERE turn_id=?', (turn_id,)).fetchone()
        if row is None:
            return None  # Legacy behavior retained; unknown is not reclassified.
        data = json.loads(row['payload'])
        if type(data) is not list:
            raise ResearchError('invalid_exposure_manifest')
        return {'scope': row['scope'], 'manifest': merge_exposures([data]),
                'summary_refs': self.research_summaries.links(db, turn_id)}

    def _verify(self, db, manifest, access):
        self.catalog._ready(db)
        for expected in merge_exposures([manifest]):
            meta = self.catalog._selected(db, [(expected['id'], expected['revision'])], access, 64000)[0]
            if exposure(meta) != expected:
                raise ResearchError('research_exposure_changed')

    def _allowed(self, db, turn_id):
        if self.research_input_only():
            return False
        try:
            record = self._record(db, turn_id)
            if record is None:
                return True
            if self.summary_filter.get() and record['manifest']:
                return False
            current = self.scope.get()
            if current:
                current.validate_host()
            access = current.access if current else ResearchAccess()
            self._verify(db, record['manifest'], access)
            for ref in record['summary_refs']:
                self.research_summaries.verify(db, ref, access)
            return True
        except (ValueError, KeyError, TypeError):
            return False

    def _pairs_from_rows(self, db, rows):
        # Permission/dependency metadata is checked before the base body SELECT.
        permitted = [row for row in rows if self._allowed(db, row['id'])]
        return super()._pairs_from_rows(db, permitted)

    def recent(self, session_id, limit=6):
        if self.research_input_only():
            return []
        with self.connection() as db:
            self._session(db, session_id)
            # Walk bounded metadata pages so excluded course turns do not hide
            # all otherwise usable recent conversation. Never load their text.
            permitted = []
            for offset in range(0, 256, 32):
                rows = db.execute("SELECT t.* FROM lc_turns t JOIN lc_messages m ON m.id=t.user_id WHERE t.session_id=? AND t.status='complete' AND m.allowed=1 ORDER BY t.seq DESC LIMIT 32 OFFSET ?", (session_id, offset)).fetchall()
                for row in rows:
                    if self._allowed(db, row['id']):
                        permitted.append(row)
                        if len(permitted) >= limit:
                            break
                if len(permitted) >= limit or len(rows) < 32:
                    break
            return super()._pairs_from_rows(db, reversed(permitted))

    def _completed(self, db, turn):
        current = self.scope.get()
        record = self._record(db, turn['id'])
        if record is not None:
            if current is None or record['scope'] != current.fingerprint():
                raise ChatStateError('research_cache_scope', '这条旧回复不属于当前取用范围。')
            try:
                current.validate_host()
                self._verify(db, record['manifest'], current.access)
                for ref in record['summary_refs']:
                    self.research_summaries.verify(db, ref, current.access)
            except ResearchError:
                raise ChatStateError('research_context_stale', '研究来源已变化，不能重放旧回复。') from None
        elif current is not None and (current.input_only or current.refs):
            raise ChatStateError('research_cache_scope', '旧回复没有可核对的本轮取用记录。')
        result = super()._completed(db, turn)
        if current is not None:
            wanted = {ident for ident, _ in current.refs}
            used = sum(item['id'] in wanted for item in record['manifest']) if record is not None else 0
            result['research_use'] = {'status': 'cached', 'used': used}
        return result

    def complete(self, request_id, reply, epoch, ref_ids):
        current = self.scope.get()
        if current is None or current.request_id != request_id:
            raise ChatStateError('research_scope_missing', '研究请求的会话范围已失效。')
        with current.publication_guard(), self.connection() as db:
            try:
                current.validate_host()
                self._verify(db, current.manifest, current.access)
                for ref in current.summary_refs:
                    self.research_summaries.verify(db, ref, current.access)
            except ResearchError:
                raise ChatStateError('research_context_stale', '研究来源或取用范围已变化，这条回复已作废。') from None
            ident = self._complete(db, request_id, reply, epoch, ref_ids)
            db.execute('INSERT INTO rc_exposures VALUES (?,?,?)',
                       (request_id, current.fingerprint(), encoded(current.manifest)))
            db.executemany('INSERT INTO rc_turn_summary_links VALUES (?,?,?,?)',
                           [(request_id, r['id'], r['revision'], r['body_hash']) for r in current.summary_refs])
            return ident

    def _summary_candidate_clause(self):
        # Only the canonical empty manifest is safe for the legacy summary.
        # Exclude research metadata before LIMIT; do not mark raw turns covered.
        return " AND NOT EXISTS (SELECT 1 FROM rc_exposures r WHERE r.turn_id=t.id AND r.payload!='[]')"

    def summary_view(self, session_id, **kwargs):
        if self.research_input_only():
            return {'epoch': self.epoch(), 'latest_seq': 0, 'new_turns': [], 'segments': [],
                    'last_attempt_seq': 0, 'last_attempt_status': 'current_input_only',
                    'old_unsummarized_turns': 0, 'owner': self.owner}
        token = self.summary_filter.set(True)
        try:
            return super().summary_view(session_id, **kwargs)
        finally:
            self.summary_filter.reset(token)

    def commit_summary(self, session_id, view, turns, text):
        # Do not launder research-derived answers into unscoped L3/legacy L2.
        # Research exposure rows are immutable and committed with the answer.
        with self.connection() as db:
            for turn in turns:
                record = self._record(db, turn['id'])
                if record is not None and record['manifest']:
                    return False
        return super().commit_summary(session_id, view, turns, text)


class ResearchProvider:
    """Selections are bound by trusted Python host code, never request JSON.

    There is no text-to-study-grant heuristic or follow-up lease. Explicit
    refusal can only narrow the scope, including a previously bound selection.
    """
    error_type = ResearchError
    DENY = re.compile(r'(?:不要|别|禁止|无需|不用)(?:再|去|额外|自动)?(?:读取|检索|查询|取用|调用|使用|加载|参考|读|用)(?:任何|已有|保存的|相关|我的|其他|的)*(?:课程资料|课程材料|学习资料|资料|材料|历史|缓存|记忆)|(?:只|仅)(?:根据|基于|使用)(?:我这句话|本轮输入|这条消息|我当前贴出的材料|我贴的材料|当前材料)')

    def __init__(self, journal):
        if type(journal) is not ResearchJournal:
            raise ValueError('research_requires_scoped_journal')
        self.journal = journal
        self.catalog = journal.catalog
        self._host_binding = ContextVar('research_host_' + str(uuid.uuid4()), default=None)
        self._bindings = {}
        self._lock = threading.RLock()
        self._generation = 0
        self._enabled = True

    def bind(self, request_id, session_id, refs=(), *, access=ResearchAccess()):
        uid(request_id); uid(session_id)
        if type(access) is not ResearchAccess or type(refs) not in (list, tuple) or len(refs) > 8:
            raise ValueError('invalid_research_binding')
        frozen = tuple((uid(i), uid(r)) for i, r in refs)
        binding = (session_id, frozen, access)
        with self._lock:
            old = self._bindings.get(request_id)
            if old is not None and old != binding:
                raise ValueError('research_request_binding_changed')
            if old is None and len(self._bindings) >= 256:
                raise ValueError('research_binding_limit')
            self._bindings[request_id] = binding

    def available(self):
        with self._lock:
            return self._enabled

    @contextmanager
    def host_selection(self, text, request_id, session_id, refs, access):
        uid(request_id); uid(session_id)
        if type(text) is not str or type(access) is not ResearchAccess or len(refs) > 8:
            raise ValueError('invalid_host_selection')
        binding = (request_id, session_id, text, tuple(refs), access)
        token = self._host_binding.set(binding)
        try:
            yield
        finally:
            self._host_binding.reset(token)

    def disable(self):
        with self._lock:
            self._enabled = False
            self._generation += 1

    @contextmanager
    def request_scope(self, text, request_id, session_id, origin):
        ident = uid(request_id) if request_id is not None else str(uuid.uuid4())
        with self._lock:
            binding = self._bindings.get(ident)
            generation = self._generation
        host = self._host_binding.get()
        if host is not None:
            if host[:3] != (ident, session_id, text) or origin != 'user':
                raise ResearchError('host_request_mismatch')
            binding = (session_id, host[3], host[4])
        if binding is not None and binding[0] != session_id:
            raise ChatStateError('research_session_changed', '研究取用不属于当前会话。')
        refs, access = (binding[1], binding[2]) if binding is not None else ((), ResearchAccess())
        input_only = origin == 'user' and bool(self.DENY.search(re.sub(r'\s+', '', text)))
        if origin != 'user' or input_only:
            refs, access = (), ResearchAccess()

        def validate():
            with self._lock:
                if not self._enabled or self._generation != generation or self.journal.session_id != session_id:
                    raise ResearchError('research_provider_changed')

        @contextmanager
        def publication():
            with self._lock:
                validate()
                yield
        state = RequestScope(ident, session_id, access, refs, input_only,
                             validate_host=validate, publication_guard=publication)
        token = self.journal.scope.set(state)
        try:
            yield ident
        finally:
            self.journal.scope.reset(token)

    def prepare(self, report, manager):
        state = self.journal.scope.get()
        state.validate_host()
        result = {'data': None, 'manifest': [], 'status': 'not_selected'}
        if state.input_only:
            result['status'] = 'current_input_only'
            return result
        if not state.refs:
            return result
        # A pre-body UTF-8 bound is meaningful for the existing byte estimator.
        # Unknown token counters need an explicit bound adapter, not a guess.
        if manager.token_counter is not conservative_count:
            result['status'] = 'unsupported_budget_counter'
            return result
        with self.catalog.connection() as db:
            self.catalog._ready(db)
            try:
                metadata = self.catalog._selected(db, state.refs, state.access, 64000)
            except ResearchError:
                result['status'] = 'scope_or_source_blocked'
                return result
        # JSON control escapes can expand a UTF-8 byte by at most six. Keep
        # a generous per-record envelope; the real builder still checks again.
        envelope = 1000 + sum(len(encoded(exposure(m)).encode('utf-8')) + 256 for m in metadata)
        bound = envelope + sum(m['body_bytes'] * 6 for m in metadata)
        if bound > report['input_limit'] - report['count']:
            result['status'] = 'budget_omitted_before_body'
            return result
        bodies = self.catalog.read_selected(state.refs, access=state.access)
        expected = [exposure(m) for m in metadata]
        if [exposure(row['metadata']) for row in bodies] != expected:
            raise ResearchError('research_changed_during_read')
        result.update(data=[{'id': r['metadata']['id'], 'revision': r['metadata']['revision'],
                            'trust': r['metadata']['trust'], 'text': r['body']} for r in bodies],
                      manifest=expected, status='ready')
        return result

    def adopt(self, prepared, report):
        state = self.journal.scope.get()
        from .research_summaries import normalized_refs
        groups = [prepared['manifest']] if report['research_adopted'] else []
        summary_refs = list(report.get('research_summary_refs', []))
        with state.publication_guard(), self.journal.connection() as db:
            for turn_id in report['recent_turn_ids'] + report['retrieved_turn_ids']:
                record = self.journal._record(db, turn_id)
                if record is not None:
                    groups.append(record['manifest'])
                    summary_refs.extend(record['summary_refs'])
            summary_refs = normalized_refs(summary_refs)
            for ref in summary_refs:
                groups.append(self.journal.research_summaries.verify(db, ref, state.access)['manifest'])
            manifest = merge_exposures(groups)
            state.validate_host()
            self.journal._verify(db, manifest, state.access)
        state.manifest = manifest
        state.summary_refs = summary_refs
