"""Explicit host import, never invoked by a model, viewer, or directory scan.

All sources, bodies, provenance and receipts commit together. The caller owns
classification/course scope; imported text cannot approve L2 or grant chat use.
"""
import json
import uuid

from .research_catalog import ResearchCatalog, ResearchError, SCHEMA, digest, ids, packed, uid


FORMAT = 'gernze-research-import-v1'
FIELDS = {'id', 'revision', 'previous', 'title', 'body', 'source_text',
          'source_ref', 'review_status', 'review_scope'}
REVIEW = {'reported_reviewed', 'reported_verified', 'partial', 'unverified'}
IMPORT_SCHEMA = (
    '''CREATE TABLE rc_import_items(namespace TEXT NOT NULL,external_id TEXT NOT NULL,
       external_revision TEXT NOT NULL,source_id TEXT NOT NULL UNIQUE REFERENCES rc_sources(id),
       source_revision TEXT NOT NULL,entry_id TEXT NOT NULL UNIQUE REFERENCES rc_entries(id),
       entry_revision TEXT NOT NULL,category TEXT NOT NULL,courses TEXT NOT NULL,
       source_kind TEXT NOT NULL,title TEXT NOT NULL,review_status TEXT NOT NULL,
       review_scope TEXT NOT NULL,source_ref TEXT NOT NULL,
       PRIMARY KEY(namespace,external_id))''',
    '''CREATE TABLE rc_import_receipts(namespace TEXT NOT NULL,external_id TEXT NOT NULL,
       external_revision TEXT NOT NULL,payload_hash TEXT NOT NULL,
       PRIMARY KEY(namespace,external_id,external_revision))''',
)


def text(value, limit):
    if type(value) is not str or not value.strip() or len(value.encode('utf-8')) > limit or '\0' in value:
        raise ValueError('invalid_import_text')
    return value


def validate(packet):
    if type(packet) is not dict or set(packet) != {'format', 'namespace', 'items'} or packet['format'] != FORMAT:
        raise ValueError('invalid_import_format')
    namespace = uid(packet['namespace'])
    items = packet['items']
    if type(items) is not list or not 1 <= len(items) <= 100:
        raise ValueError('invalid_import_count')
    seen, result, total = set(), [], 0
    for item in items:
        if type(item) is not dict or set(item) != FIELDS:
            raise ValueError('invalid_import_fields')
        ident = text(item['id'], 256)
        if ident in seen:
            raise ValueError('duplicate_import_id')
        seen.add(ident)
        uid(item['revision'])
        if item['previous'] is not None:
            uid(item['previous'])
            if item['previous'] == item['revision']:
                raise ValueError('invalid_import_previous')
        for key, limit in [('title', 256), ('body', 24000), ('source_text', 64000),
                           ('source_ref', 2048), ('review_scope', 2400)]:
            text(item[key], limit)
        if type(item['review_status']) is not str or item['review_status'] not in REVIEW:
            raise ValueError('invalid_import_review')
        payload = packed(item)
        total += len(payload.encode('utf-8'))
        if len(payload.encode('utf-8')) > 100000 or total > 4000000:
            raise ValueError('import_too_large')
        body = (item['title'] + '\n\n来源：' + item['source_ref'] +
                '\n验收记录（交付方报告，不是本次独立核验）：' + item['review_scope'] +
                '\n下文第一人称属于该来源作者；分类不表示已审记忆。\n\n' + item['body'])
        if len(body.encode('utf-8')) > 32000:
            raise ValueError('invalid_import_body')
        result.append((dict(item), payload, body))
    return namespace, result


class ResearchImporter:
    def __init__(self, path, *, trace=None):
        self.catalog = ResearchCatalog(path, trace=trace)

    def apply(self, packet, *, category, courses=(), source_kind='companion'):
        # This is a trusted Python-host API, deliberately absent from HTTP and
        # model tool schemas. The packet cannot choose its own permissions.
        namespace, items = validate(packet)
        if category not in ('encounter', 'interest', 'course') or source_kind not in ('companion', 'web'):
            raise ValueError('invalid_import_classification')
        scopes = ids(courses)
        if (category == 'course') != bool(scopes):
            raise ValueError('invalid_import_course_scope')
        with self.catalog.connection(write=True, create=True) as db:
            return self._apply(db,namespace,items,category,scopes,source_kind)

    def _apply(self,db,namespace,items,category,scopes,source_kind,*,keep_local=False):
        scope_json = packed(scopes)
        restriction = 'study' if scopes else 'general'
        trust = 'agent_inferred' if source_kind == 'companion' else 'external_untrusted'
        counts = {'created': 0, 'updated': 0, 'unchanged': 0}
        entries = []
        # No initialize() outside this transaction: even initial schema creation
        # must roll back if an item or receipt fails later in this batch.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_meta'").fetchone():
            self.catalog._ready(db)  # No implicit upgrade of old catalogs.
        else:
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("INSERT INTO rc_meta VALUES ('schema','2')")
        version = db.execute("SELECT value FROM rc_meta WHERE key='import_schema'").fetchone()
        if version is None:
            for statement in IMPORT_SCHEMA:
                db.execute(statement)
            db.execute("INSERT INTO rc_meta VALUES ('import_schema','1')")
        elif version[0] != '1':
            raise ResearchError('unsupported_import_schema')
        for item, payload, body in items:
            key = (namespace, item['id'])
            row = db.execute('SELECT * FROM rc_import_items WHERE namespace=? AND external_id=?', key).fetchone()
            receipt = db.execute('SELECT payload_hash FROM rc_import_receipts WHERE namespace=? AND external_id=? AND external_revision=?',
                                 (*key, item['revision'])).fetchone()
            if row:
                if (row['category'], row['courses'], row['source_kind']) != (category, scope_json, source_kind):
                    raise ResearchError('import_scope_change_requires_rebuild')
                # Receipt alone cannot resurrect an independently changed,
                # withdrawn, or conflicted source/entry.
                if keep_local:
                    local = db.execute('SELECT s.revision,s.state,e.revision AS entry_revision,e.state AS entry_state FROM rc_sources s JOIN rc_entries e ON e.id=? WHERE s.id=?', (row['entry_id'],row['source_id'])).fetchone()
                    if not local or local['revision']!=row['source_revision'] or local['state']!='active' or local['entry_revision']!=row['entry_revision'] or local['entry_state']!='active':
                        counts.setdefault('retained_local',[]).append(item['id'])
                        continue
                selected = self.catalog._selected(db, [(row['entry_id'], row['entry_revision'])],
                                                 self._access(scopes), 64000)[0]
                if selected['source_versions'] != {row['source_id']: row['source_revision']}:
                    raise ResearchError('import_source_changed')
                if receipt:
                    if receipt[0] != digest(payload):
                        raise ResearchError('import_revision_content_mismatch')
                    if row['external_revision'] != item['revision']:
                        raise ResearchError('old_import_replay')
                    counts['unchanged'] += 1
                    entries.append((row['entry_id'], row['entry_revision']))
                    continue
                if item['previous'] != row['external_revision']:
                    raise ResearchError('import_revision_changed')
                source_id, entry_id = row['source_id'], row['entry_id']
            else:
                if receipt or item['previous'] is not None:
                    raise ResearchError('missing_import_predecessor')
                source_id = str(uuid.uuid5(uuid.UUID(namespace), 'source/' + item['id']))
                entry_id = str(uuid.uuid5(uuid.UUID(namespace), 'entry/' + item['id']))
            source_revision, entry_revision = str(uuid.uuid4()), str(uuid.uuid4())
            parents = packed([(source_id, source_revision)])
            if row:
                db.execute('UPDATE rc_sources SET revision=?,payload_hash=? WHERE id=?',
                           (source_revision, digest(payload), source_id))
                db.execute('UPDATE rc_entries SET revision=?,body_hash=?,body_bytes=?,parents=? WHERE id=?',
                           (entry_revision, digest(body), len(body.encode('utf-8')), parents, entry_id))
                db.execute('UPDATE rc_bodies SET body=? WHERE id=?', (body, entry_id))
                db.execute('UPDATE rc_import_items SET external_revision=?,source_revision=?,entry_revision=?,title=?,review_status=?,review_scope=?,source_ref=? WHERE namespace=? AND external_id=?',
                           (item['revision'], source_revision, entry_revision, item['title'], item['review_status'], item['review_scope'], item['source_ref'], *key))
                counts['updated'] += 1
            else:
                db.execute('INSERT INTO rc_sources VALUES (?,?,?,?,?,?,?,?,?)',
                           (source_id, source_revision, source_kind, restriction, scope_json, 'active', digest(payload), '[]', 1))
                db.execute('INSERT INTO rc_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (entry_id, entry_revision, packed([category]), trust, restriction, scope_json, 'active',
                            digest(body), len(body.encode('utf-8')), parents, None, None))
                db.execute('INSERT INTO rc_bodies VALUES (?,?)', (entry_id, body))
                db.execute('INSERT INTO rc_import_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (*key, item['revision'], source_id, source_revision, entry_id, entry_revision,
                            category, scope_json, source_kind, item['title'], item['review_status'], item['review_scope'], item['source_ref']))
                counts['created'] += 1
            db.execute('INSERT INTO rc_source_payloads VALUES (?,?,?)', (source_id, source_revision, payload))
            db.execute('INSERT INTO rc_import_receipts VALUES (?,?,?,?)', (*key, item['revision'], digest(payload)))
            entries.append((entry_id, entry_revision))
        return {**counts, 'entries': entries, 'l2Approved': False, 'chatAccessGranted': False}

    def apply_bundle(self,batches,*,namespace,active_ids,check_current=lambda:None):
        """Trusted local publication: all imports and soft retirements share a transaction."""
        uid(namespace)
        if type(batches) is not list or len(batches)>2048 or type(active_ids) is not set or len(active_ids)>10000:
            raise ValueError('invalid_import_bundle')
        prepared=[]
        for batch in batches:
            ns,items=validate(batch['packet']);category=batch['category'];kind=batch['source_kind'];scopes=ids(batch['courses'])
            if ns!=namespace or category not in ('encounter','interest','course') or kind!='companion' or (category=='course')!=bool(scopes):
                raise ValueError('invalid_import_bundle_scope')
            prepared.append((ns,items,category,scopes,kind))
        result={'created':0,'updated':0,'unchanged':0,'retired':0,'retainedLocal':0};retained=set()
        with self.catalog.connection(write=True,create=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_meta'").fetchone():self.catalog._ready(db)
            for args in prepared:
                value=self._apply(db,*args,keep_local=True)
                for key in ('created','updated','unchanged'):result[key]+=value[key]
                retained.update(value.get('retained_local',[]))
            # A publication's absence retires only this host-approved namespace.
            # Keep every body/receipt; source conflict blocks automatic reactivation.
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_import_items'").fetchone()
            rows=list(db.execute('SELECT * FROM rc_import_items WHERE namespace=?',(namespace,))) if exists else []
            for row in rows:
                if row['external_id'] in active_ids:continue
                source=db.execute('SELECT s.revision,s.state,e.revision AS entry_revision,e.state AS entry_state FROM rc_sources s JOIN rc_entries e ON e.id=? WHERE s.id=?',(row['entry_id'],row['source_id'])).fetchone()
                if source and source['revision']==row['source_revision'] and source['state']=='active' and source['entry_revision']==row['entry_revision'] and source['entry_state']=='active':
                    db.execute("UPDATE rc_sources SET revision=?,state='conflict',payload_stored=0 WHERE id=?",(str(uuid.uuid4()),row['source_id']))
                    result['retired']+=1
                else:retained.add(row['external_id'])
            check_current()
        result['retainedLocal']=len(retained)
        return result

    @staticmethod
    def _access(scopes):
        from .research_catalog import ResearchAccess
        return ResearchAccess('study', scopes) if scopes else ResearchAccess()


def load_packet(path):
    """Explicit single local JSON file; no paths or code inside it are followed."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_import_json_key')
            result[key] = value
        return result
    with open(path, 'rb') as stream:
        data = stream.read(4000001)
    if len(data) > 4000000:
        raise ValueError('import_too_large')
    packet = json.loads(data.decode('utf-8'), object_pairs_hook=unique_pairs)
    validate(packet)
    return packet
