"""Host-owned research catalog. Separate metadata/body tables; no L2 authority.

Optional desktop wiring lives in research_context and is disabled by default.
No production activation, network, model or semantic routing happens here.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def uid(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('invalid_research_id')
    return value


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def ids(values):
    if type(values) not in (list, tuple) or len(values) > 16:
        raise ValueError('invalid_course_scopes')
    return tuple(sorted({uid(v) for v in values}))


class ResearchError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchAccess:
    # Internal host input, NOT an HTTP/model schema or a signed permission.
    # Trusted host code binds it to a request; no public issuer is enabled.
    scene: str = 'casual'
    courses: tuple = ()

    def __post_init__(self):
        if self.scene not in ('casual', 'study') or type(self.courses) is not tuple:
            raise ValueError('invalid_research_access')
        normalized = ids(self.courses)
        if normalized != self.courses or self.scene != 'study' and self.courses:
            raise ValueError('invalid_research_access')


SCHEMA = (
    'CREATE TABLE rc_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
    '''CREATE TABLE rc_sources(id TEXT PRIMARY KEY,revision TEXT NOT NULL,
       kind TEXT NOT NULL,restriction TEXT NOT NULL,courses TEXT NOT NULL,
       state TEXT NOT NULL,payload_hash TEXT NOT NULL,parents TEXT NOT NULL,
       payload_stored INTEGER NOT NULL)''',
    '''CREATE TABLE rc_source_payloads(source_id TEXT NOT NULL REFERENCES rc_sources(id),
       revision TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(source_id,revision))''',
    '''CREATE TABLE rc_entries(id TEXT PRIMARY KEY,revision TEXT NOT NULL,
       facets TEXT NOT NULL,trust TEXT NOT NULL,restriction TEXT NOT NULL,
       courses TEXT NOT NULL,state TEXT NOT NULL,body_hash TEXT NOT NULL,
       body_bytes INTEGER NOT NULL,parents TEXT NOT NULL,
       conflict_group TEXT,assertion_hash TEXT)''',
    '''CREATE TABLE rc_bodies(id TEXT PRIMARY KEY REFERENCES rc_entries(id),
       body TEXT NOT NULL)''',
    'CREATE INDEX rc_entries_group ON rc_entries(conflict_group)',
)
META_COLUMNS = 'id,revision,facets,trust,restriction,courses,state,body_hash,body_bytes,parents,conflict_group,assertion_hash'
SOURCE_COLUMNS = 'id,revision,kind,restriction,courses,state,payload_hash,parents,payload_stored'


class ResearchCatalog:
    def __init__(self, path, *, trace=None):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError('research_path_must_be_absolute')
        self.trace = trace

    @contextmanager
    def connection(self, *, write=False, create=False):
        mode = 'rwc' if create else ('rw' if write else 'ro')
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            if not write:
                db.execute('PRAGMA query_only=ON')
            if self.trace:
                db.set_trace_callback(self.trace)
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        """Explicit host bootstrap only; constructing a reader creates nothing."""
        with self.connection(write=True, create=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rc_meta'").fetchone()
            if exists:
                row = db.execute("SELECT value FROM rc_meta WHERE key='schema'").fetchone()
                if row and row[0] == '1':
                    # v1 stored only a root digest. Never invent the missing
                    # original or classify those old research roots as proven.
                    db.execute('ALTER TABLE rc_sources ADD COLUMN payload_stored INTEGER NOT NULL DEFAULT 0')
                    db.execute(SCHEMA[2])
                    db.execute("UPDATE rc_meta SET value='2' WHERE key='schema'")
                elif not row or row[0] != '2':
                    raise ResearchError('unsupported_research_schema')
            else:
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute("INSERT INTO rc_meta VALUES ('schema','2')")

    def _ready(self, db):
        row = db.execute("SELECT value FROM rc_meta WHERE key='schema'").fetchone()
        if not row or row[0] != '2':
            raise ResearchError('unsupported_research_schema')

    def _sources(self, db, refs, seen=(), memo=None):
        if type(refs) not in (list, tuple) or not 1 <= len(refs) <= 8 or len(seen) > 32:
            raise ResearchError('invalid_source_refs')
        normalized, direct = [], set()
        for ref in refs:
            if type(ref) not in (list, tuple) or len(ref) != 2:
                raise ResearchError('invalid_source_refs')
            ident, revision = map(uid, ref)
            if ident in seen or ident in direct:
                raise ResearchError('duplicate_or_cyclic_source')
            direct.add(ident)
            normalized.append((ident, revision))
        memo = {} if memo is None else memo
        memo_key = tuple(normalized)
        if memo_key in memo:
            if memo[memo_key] is None:
                raise ResearchError('duplicate_or_cyclic_source')
            return memo[memo_key]
        if len(memo) >= 256:
            raise ResearchError('source_lineage_too_large')
        memo[memo_key] = None
        courses, study, roots = set(), False, {}
        for ident, revision in normalized:
            row = db.execute('SELECT ' + SOURCE_COLUMNS + ' FROM rc_sources WHERE id=?', (ident,)).fetchone()
            if not row or row['state'] != 'active' or row['revision'] != revision or row['payload_stored'] != 1:
                raise ResearchError('source_unavailable')
            if row['restriction'] not in ('general', 'study'):
                raise ResearchError('unknown_source_restriction')
            scope = ids(json.loads(row['courses']))
            if row['kind'] not in ('web', 'chat_user', 'companion', 'course', 'derived'):
                raise ResearchError('unknown_source_kind')
            if (row['kind'] == 'course' or scope) and row['restriction'] != 'study':
                raise ResearchError('source_restriction_mismatch')
            study |= row['restriction'] == 'study'
            courses.update(scope)
            if ident in roots and roots[ident] != revision:
                raise ResearchError('inconsistent_source_versions')
            roots[ident] = revision
            parents = json.loads(row['parents'])
            if (row['kind'] == 'derived') != bool(parents):
                raise ResearchError('invalid_source_lineage')
            if parents:
                parent_study, parent_courses, ancestry = self._sources(db, parents, seen + (ident,), memo)
                if parent_study and (row['restriction'] != 'study' or not set(parent_courses) <= set(scope)):
                    raise ResearchError('source_restriction_mismatch')
                study |= parent_study
                courses.update(parent_courses)
                for key, value in ancestry.items():
                    if key in roots and roots[key] != value:
                        raise ResearchError('inconsistent_source_versions')
                    roots[key] = value
        if study and not courses:
            raise ResearchError('missing_course_scope')
        result = study, tuple(sorted(courses)), roots
        memo[memo_key] = result
        return result

    def create_source(self, kind, source_text, *, courses=(), parents=()):
        if kind not in ('web', 'chat_user', 'companion', 'course', 'derived'):
            raise ValueError('invalid_source_kind')
        if type(source_text) is not str or len(source_text.encode('utf-8')) > 100000:
            raise ValueError('invalid_source_text')
        scopes = set(ids(courses))
        if (kind == 'derived') != bool(parents):
            raise ValueError('derived_requires_parents')
        with self.connection(write=True) as db:
            self._ready(db)
            study = kind == 'course' or bool(scopes)
            if parents:
                inherited, inherited_scopes, _ = self._sources(db, parents)
                study |= inherited
                scopes.update(inherited_scopes)
            if study and not scopes:
                raise ResearchError('missing_course_scope')
            ident, revision = str(uuid.uuid4()), str(uuid.uuid4())
            db.execute('INSERT INTO rc_sources VALUES (?,?,?,?,?,?,?,?,?)',
                       (ident, revision, kind, 'study' if study else 'general',
                        packed(sorted(scopes)), 'active', digest(source_text), packed(parents), 1))
            db.execute('INSERT INTO rc_source_payloads VALUES (?,?,?)', (ident, revision, source_text))
        return ident, revision

    def change_source(self, ident, expected_revision, *, source_text=None, state='active'):
        """CAS within one writer transaction; never orders opaque UUID revisions."""
        uid(ident); uid(expected_revision)
        if state not in ('active', 'withdrawn', 'conflict') or source_text is not None and type(source_text) is not str:
            raise ValueError('invalid_source_change')
        if source_text is not None and len(source_text.encode('utf-8')) > 100000:
            raise ValueError('invalid_source_text')
        with self.connection(write=True) as db:
            self._ready(db)
            row = db.execute('SELECT ' + SOURCE_COLUMNS + ' FROM rc_sources WHERE id=?', (ident,)).fetchone()
            if not row or row['revision'] != expected_revision:
                raise ResearchError('source_revision_changed')
            if row['state'] != 'active':
                raise ResearchError('source_requires_explicit_rebuild')
            if state == 'active' and source_text is None:
                raise ValueError('source_text_required_for_revision')
            revision = str(uuid.uuid4())
            db.execute('UPDATE rc_sources SET revision=?,state=?,payload_hash=?,payload_stored=? WHERE id=?',
                       (revision, state, digest(source_text) if source_text is not None else row['payload_hash'],
                        int(source_text is not None), ident))
            if source_text is not None:
                db.execute('INSERT INTO rc_source_payloads VALUES (?,?,?)', (ident, revision, source_text))
        return ident, revision

    def add_entry(self, body, parents, *, facets=('interest',), trust='external_untrusted',
                  conflict_group=None, assertion_hash=None):
        if type(body) is not str or not body.strip() or len(body.encode('utf-8')) > 32000:
            raise ValueError('invalid_research_body')
        if type(facets) not in (list, tuple) or not facets or set(facets) - {'encounter', 'interest', 'course'}:
            raise ValueError('invalid_research_facets')
        if trust not in ('external_untrusted', 'agent_inferred', 'user_reported_unreviewed'):
            raise ValueError('research_cannot_approve_l2')
        if conflict_group is not None:
            uid(conflict_group)
            if type(assertion_hash) is not str or len(assertion_hash) != 64 or any(c not in '0123456789abcdef' for c in assertion_hash):
                raise ValueError('invalid_assertion_hash')
        elif assertion_hash is not None:
            raise ValueError('assertion_requires_conflict_group')
        with self.connection(write=True) as db:
            self._ready(db)
            study, courses, _ = self._sources(db, parents)
            if 'course' in facets and not study:
                raise ResearchError('course_facet_requires_scoped_source')
            ident, revision = str(uuid.uuid4()), str(uuid.uuid4())
            db.execute('INSERT INTO rc_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, revision, packed(sorted(set(facets))), trust,
                        'study' if study else 'general', packed(courses), 'active', digest(body),
                        len(body.encode('utf-8')), packed(parents), conflict_group, assertion_hash))
            db.execute('INSERT INTO rc_bodies VALUES (?,?)', (ident, body))
            if conflict_group is not None:
                rows = db.execute("SELECT id,assertion_hash,state FROM rc_entries WHERE conflict_group=? AND state IN ('active','conflict')", (conflict_group,)).fetchall()
                if len({r['assertion_hash'] for r in rows}) > 1:
                    for row in rows:
                        db.execute("UPDATE rc_entries SET state='conflict',revision=? WHERE id=?", (str(uuid.uuid4()), row['id']))
                revision = db.execute('SELECT revision FROM rc_entries WHERE id=?', (ident,)).fetchone()[0]
        return ident, revision

    def _metadata(self, db, row):
        data = dict(row)
        try:
            for key in ('facets', 'courses', 'parents'):
                data[key] = json.loads(data[key])
            ids(data['courses'])
            if data['trust'] not in ('external_untrusted', 'agent_inferred', 'user_reported_unreviewed'):
                raise ResearchError('unknown_research_trust')
            if type(data['facets']) is not list or not data['facets'] or set(data['facets']) - {'encounter', 'interest', 'course'}:
                raise ResearchError('unknown_research_facets')
            if ('course' in data['facets'] or data['courses']) and data['restriction'] != 'study':
                raise ResearchError('restriction_mismatch')
            study, courses, roots = self._sources(db, data['parents'])
            if study and (data['restriction'] != 'study' or not set(courses) <= set(data['courses'])):
                raise ResearchError('restriction_mismatch')
            data['source_versions'] = roots
        except (ValueError, TypeError, KeyError):
            data['state'] = 'unavailable'
            data['source_versions'] = {}
        return data

    def catalog(self, *, limit=100, after='', facet=None, restriction=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('invalid_catalog_limit')
        if facet not in (None, 'encounter', 'interest', 'course') or restriction not in (None, 'general', 'study'):
            raise ValueError('invalid_catalog_filter')
        if after:
            uid(after)
        with self.connection() as db:
            self._ready(db)
            where, args = 'id>?', [after]
            if facet is not None:
                where += ' AND facets LIKE ?'
                args.append('%"' + facet + '"%')
            if restriction is not None:
                where += ' AND restriction=?'
                args.append(restriction)
            rows = db.execute('SELECT ' + META_COLUMNS + ' FROM rc_entries WHERE ' + where + ' ORDER BY id LIMIT ?', (*args, limit)).fetchall()
            return [self._metadata(db, row) for row in rows]

    def _selected(self, db, refs, access, max_bytes):
        if type(access) is not ResearchAccess or type(refs) not in (list, tuple) or len(refs) > 8:
            raise ResearchError('invalid_research_selection')
        if type(max_bytes) is not int or not 0 <= max_bytes <= 64000:
            raise ValueError('invalid_research_budget')
        selected, seen, total = [], set(), 0
        for ident, revision in refs:
            uid(ident); uid(revision)
            if ident in seen:
                raise ResearchError('duplicate_research_selection')
            seen.add(ident)
            row = db.execute('SELECT ' + META_COLUMNS + ' FROM rc_entries WHERE id=?', (ident,)).fetchone()
            if not row or row['revision'] != revision:
                raise ResearchError('research_revision_changed')
            meta = self._metadata(db, row)
            if meta['state'] != 'active' or meta['restriction'] not in ('general', 'study'):
                raise ResearchError('research_unavailable')
            if meta['restriction'] == 'study' and (access.scene != 'study' or not meta['courses'] or not set(meta['courses']) <= set(access.courses)):
                raise ResearchError('course_access_denied')
            total += meta['body_bytes']
            if meta['body_bytes'] <= 0 or total > max_bytes:
                raise ResearchError('research_budget_exceeded')
            selected.append(meta)
        return selected

    def read_selected(self, refs, *, access=ResearchAccess(), max_bytes=64000):
        with self.connection() as db:
            self._ready(db)
            # Authorize ALL selections and total size before ANY body query.
            selected = self._selected(db, refs, access, max_bytes)
            result = []
            for meta in selected:
                row = db.execute('SELECT body FROM rc_bodies WHERE id=?', (meta['id'],)).fetchone()
                if not row or len(row['body'].encode('utf-8')) != meta['body_bytes'] or digest(row['body']) != meta['body_hash']:
                    raise ResearchError('research_body_integrity_failed')
                result.append({'metadata': meta, 'body': row['body']})
            return result

    @contextmanager
    def validation_transaction(self, refs, *, access=ResearchAccess(), max_bytes=64000):
        """Short host publication gate; yields the SAME SQLite transaction.

        The future host must save its result/dependencies on this connection,
        not another DB transaction. No remote operation belongs inside this gate.
        """
        with self.connection(write=True) as db:
            self._ready(db)
            self._selected(db, refs, access, max_bytes)
            yield db
