"""Read-only bookshelf projection. Browsing never grants chat access or writes L2."""
from contextlib import contextmanager
import json

from .research_catalog import ResearchAccess, ResearchCatalog, ResearchError, META_COLUMNS, uid


CATEGORIES = (
    ('approved', '聊天积累的已审记忆', '经审查保留的聊天记忆；旧记忆保持原有归属。'),
    ('encounter', '莉宝的见闻与兴趣', '阅读、见闻与认识，逐条保留来源和核实状态。'),
    ('interest', '关于你的兴趣专题', '歌单、小说、出行等资料；研究与已确认事实分开。'),
    ('course', '大学课程资料', '点开资料后才读取正文；日常聊天不自动带入。'),
)
APPROVED_WHERE = "FROM lm_approved a WHERE a.deleted=0 AND NOT EXISTS (SELECT 1 FROM lm_sync_conflicts c WHERE c.tier=2 AND c.key=a.key)"


class ResearchBooks:
    def __init__(self, store, *, trace=None):
        self.store = store
        self.trace = trace
        self.catalog = ResearchCatalog(store.path, trace=trace)  # Reader only.

    @contextmanager
    def connection(self):
        with self.store.read_connection() as db:
            if self.trace is not None:
                db.set_trace_callback(self.trace)
            yield db

    @staticmethod
    def category(value):
        if type(value) is not str or value not in {row[0] for row in CATEGORIES}:
            raise ValueError('请选择书架中的一个分类。')
        return value

    @staticmethod
    def research_status(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rc_meta'").fetchone():
            return 'empty'
        row = db.execute("SELECT value FROM rc_meta WHERE key='schema'").fetchone()
        return 'ready' if row and row[0] == '2' else 'unsupported'

    @staticmethod
    def matches(meta, category):
        if category == 'course':
            return meta['restriction'] == 'study'
        return meta['restriction'] == 'general' and category in meta['facets']

    def groups(self):
        counts = {row[0]: 0 for row in CATEGORIES}
        with self.connection() as db:
            counts['approved'] = db.execute('SELECT COUNT(*) ' + APPROVED_WHERE).fetchone()[0]
            status = self.research_status(db)
            if status == 'ready':
                # Counts need only metadata, never snippets or source originals.
                for row in db.execute('SELECT facets,restriction FROM rc_entries'):
                    try:
                        meta = {'facets': json.loads(row['facets']), 'restriction': row['restriction']}
                        if type(meta['facets']) is not list:
                            continue
                        for category in counts:
                            if category != 'approved' and self.matches(meta, category):
                                counts[category] += 1
                    except (ValueError, TypeError):
                        continue
        return {'groups': [{'id': key, 'label': label, 'hint': hint, 'count': counts[key]}
                           for key, label, hint in CATEGORIES],
                'researchStatus': status, 'readOnly': True, 'chatAccessGranted': False}

    def entries(self, category, after=''):
        self.category(category)
        if type(after) is not str or len(after) > 512:
            raise ValueError('书架分页无效。')
        with self.connection() as db:
            if category == 'approved':
                rows = db.execute('SELECT a.key,a.revision,a.updated_at ' + APPROVED_WHERE +
                                  ' AND a.key>? ORDER BY a.key LIMIT 31', (after,)).fetchall()
                entries = [{'id': r['key'], 'revision': r['revision'], 'state': 'active',
                            'trust': 'user_confirmed', 'updatedAt': r['updated_at']} for r in rows[:30]]
                return {'category': category, 'entries': entries,
                        'next': entries[-1]['id'] if len(rows) > 30 else None}
            status = self.research_status(db)
        if status != 'ready':
            return {'category': category, 'entries': [], 'next': None, 'researchStatus': status}
        rows = self.catalog.catalog(limit=31, after=after,
                                    facet=None if category == 'course' else category,
                                    restriction='study' if category == 'course' else 'general')
        entries = [{'id': r['id'], 'revision': r['revision'], 'state': r['state'], 'trust': r['trust']}
                   for r in rows[:30]]
        # Optional import labels are metadata only, scoped to the exact
        # entry revision returned above. No source original/body is opened.
        with self.connection() as db:
            version = db.execute("SELECT value FROM rc_meta WHERE key='import_schema'").fetchone()
            if version and version[0] == '1':
                for entry in entries:
                    record = db.execute('SELECT title,review_status,review_scope FROM rc_import_items WHERE entry_id=? AND entry_revision=? AND category=?',
                                        (entry['id'], entry['revision'], category)).fetchone()
                    if record:
                        entry.update(title=record['title'], reviewStatus=record['review_status'], reviewScope=record['review_scope'])
        return {'category': category, 'entries': entries,
                'next': entries[-1]['id'] if len(rows) > 30 else None, 'researchStatus': status}

    def read(self, category, id, revision, purpose):
        self.category(category)
        expected = 'study_material' if category == 'course' else 'browse'
        if purpose != expected:
            raise ValueError('请从对应分类明确打开这份资料。')
        if type(id) is not str or not id or len(id) > 512 or type(revision) is not str:
            raise ValueError('资料编号无效。')
        with self.connection() as db:
            if category == 'approved':
                row = db.execute('SELECT a.key,a.revision ' + APPROVED_WHERE + ' AND a.key=?', (id,)).fetchone()
                if not row or row['revision'] != revision:
                    raise ValueError('这条记忆已变化，请刷新书架。')
                body = db.execute('SELECT body FROM lm_approved WHERE key=? AND revision=?', (id, revision)).fetchone()[0]
                return {'id': id, 'revision': revision, 'body': body, 'trust': 'user_confirmed', 'readOnly': True}
            if self.research_status(db) != 'ready':
                raise ValueError('尚无可读取的研究资料。')
        uid(id); uid(revision)
        try:
            with self.catalog.connection() as db:
                self.catalog._ready(db)
                row = db.execute('SELECT ' + META_COLUMNS + ' FROM rc_entries WHERE id=?', (id,)).fetchone()
                if not row:
                    raise ResearchError('missing_entry')
                meta = self.catalog._metadata(db, row)
                if meta['revision'] != revision or meta['state'] != 'active' or not self.matches(meta, category):
                    raise ResearchError('entry_changed_or_out_of_group')
            # This explicit local viewer intent grants only this read. It never
            # binds a ResearchProvider request, changes chat, or approves L2.
            access = ResearchAccess('study', tuple(meta['courses'])) if category == 'course' else ResearchAccess()
            result = self.catalog.read_selected([(id, revision)], access=access, max_bytes=32000)[0]
        except ResearchError:
            raise ValueError('资料已变化、来源已撤回或不属于此分类，请刷新。') from None
        return {'id': id, 'revision': revision, 'body': result['body'],
                'trust': meta['trust'], 'sourceCount': len(meta['source_versions']), 'readOnly': True}
