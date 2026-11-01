"""Paired, read-only catalog pages. Sync receipts never grant chat authority."""
from contextlib import contextmanager
import json
import sqlite3
import uuid

from .conversation_store import ConversationStore
from .research_catalog import ResearchCatalog, ResearchAccess, META_COLUMNS, packed, digest, uid

FORMAT='gernze-bookshelf-cache-v1'
STATE='bookshelf-sync-v1'
MAX_TOTAL=8388608
MAX_MANIFEST=2097152
MAX_PAGE=1048576
MAX_SEQUENCE=9007199254740991


def require(ok):
    if not ok:raise ValueError('bookshelf_changed_or_invalid')


def fields(value,names):
    require(type(value) is dict and set(value)==set(names.split()))


def size(value):return len(packed(value).encode('utf-8'))


class BookshelfTransfer:
    def __init__(self,store,server_id,scope):
        self.store=store;self.server_id=server_id;self.scope=scope
        self.catalog=ResearchCatalog(store.path)

    @contextmanager
    def read(self):
        # _SyncStore.connection is a writer transaction; do NOT use it here.
        db=sqlite3.connect(self.store.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            require(db.execute('PRAGMA user_version').fetchone()[0] in (1,4))
            require(bool(ConversationStore._get(db,'owner')))
            yield db
        finally:db.rollback();db.close()

    def available(self):
        with self.read() as db:
            row=db.execute("SELECT value FROM rc_meta WHERE key='schema'").fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_meta'").fetchone() else None
            return bool(row and row[0]=='2' and db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_import_items'").fetchone())

    def projection(self,db):
        self.catalog._ready(db)
        labels=db.execute('SELECT entry_id,entry_revision,category,title,review_status FROM rc_import_items ORDER BY entry_id LIMIT 5001').fetchall()
        require(len(labels)<=5000)
        entries=[];seen=set();total=0
        for label in labels:
            require(label['entry_id'] not in seen);seen.add(label['entry_id'])
            row=db.execute('SELECT '+META_COLUMNS+' FROM rc_entries WHERE id=?',(label['entry_id'],)).fetchone()
            if not row:continue
            meta=self.catalog._metadata(db,row)
            if meta['state']!='active' or meta['revision']!=label['entry_revision']:continue
            category=label['category']
            require(category in ('encounter','interest','course'))
            if category=='course':require(meta['restriction']=='study')
            else:require(meta['restriction']=='general' and category in meta['facets'])
            require(type(meta['body_bytes']) is int and 0<meta['body_bytes']<=32000)
            require(type(label['title']) is str and len(label['title'])<=1000)
            sources=[]
            for ident,revision in sorted(meta['source_versions'].items()):
                source=db.execute('SELECT revision,kind,restriction,courses,state,payload_hash,parents,payload_stored FROM rc_sources WHERE id=?',(ident,)).fetchone()
                require(source and source['revision']==revision and source['state']=='active')
                sources.append([ident,digest(packed(dict(source)))])
            entries.append({'id':uid(meta['id']),'revision':uid(meta['revision']),'category':category,
                'title':label['title'],'review':label['review_status'],'trust':meta['trust'],
                'bodyHash':meta['body_hash'],'bodyBytes':meta['body_bytes'],
                'sources':sources,'courses':list(meta['courses'])})
            if category!='course':total+=meta['body_bytes']
            require(total<=MAX_TOTAL)
        projection={'entries':entries,'courseBodyPolicy':'metadata_only'}
        require(size(projection)<=MAX_MANIFEST-2048)
        return projection

    def saved(self,db):
        row=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',(STATE,)).fetchone()
        if not row:return None
        value=json.loads(row[0]);require(size(value)<=MAX_MANIFEST)
        require(value['format']==FORMAT and value['serverId']==self.server_id and value['scope_id']==self.scope)
        require(type(value['sequence']) is int and 1<=value['sequence']<=MAX_SEQUENCE)
        require(value['manifestHash']==digest(packed({k:v for k,v in value.items() if k!='manifestHash'})))
        return value

    def manifest(self,previous):
        if previous is not None:
            fields(previous,'serverId scope_id sequence snapshotId manifestHash')
            require(previous['serverId']==self.server_id and previous['scope_id']==self.scope)
            require(type(previous['sequence']) is int and 1<=previous['sequence']<=MAX_SEQUENCE)
        with self.store.connection() as db:
            self.store._owner(db)
            before=self.saved(db)
            if previous is not None:
                require(before is not None and before['sequence']>=previous['sequence'])
                if before['sequence']==previous['sequence']:
                    require(all(before[k]==previous[k] for k in ('snapshotId','manifestHash')))
            projection=self.projection(db);fingerprint=digest(packed(projection))
            if before and before['contentFingerprint']==fingerprint:return before
            sequence=(before['sequence'] if before else 0)+1;require(sequence<=MAX_SEQUENCE)
            ordinary=[e for e in projection['entries'] if e['category']!='course']
            value={'format':FORMAT,'serverId':self.server_id,'scope_id':self.scope,
                'snapshotId':str(uuid.uuid4()),'sequence':sequence,'contentFingerprint':fingerprint,
                **projection,'complete':True,'bodyEntryCount':len(ordinary),'bodyBytesTotal':sum(e['bodyBytes'] for e in ordinary)}
            value['manifestHash']=digest(packed(value));require(size(value)<=MAX_MANIFEST)
            db.execute('INSERT OR REPLACE INTO lm_layer_sync_meta VALUES (?,?)',(STATE,packed(value)))
            self.store._owner(db)
            return value

    def current(self,db,request):
        value=self.saved(db);require(value is not None)
        require(value['snapshotId']==request['snapshotId'] and value['manifestHash']==request['manifestHash'])
        require(digest(packed(self.projection(db)))==value['contentFingerprint'])
        return value

    @staticmethod
    def binding(value):
        return {k:value[k] for k in ('format','serverId','scope_id','snapshotId','sequence','contentFingerprint','manifestHash')}

    def page(self,request):
        with self.read() as db:
            value=self.current(db,request);entries=[e for e in value['entries'] if e['category']!='course']
            offset=request['offset'];require(type(offset) is int and 0<=offset<len(entries))
            result={**self.binding(value),'offset':offset,'entries':[],'next':None,'complete':False}
            for meta in entries[offset:offset+32]:
                self.catalog._selected(db,[(meta['id'],meta['revision'])],ResearchAccess(),32000)
                row=db.execute('SELECT body FROM rc_bodies WHERE id=?',(meta['id'],)).fetchone()
                require(row and len(row['body'].encode('utf-8'))==meta['bodyBytes'] and digest(row['body'])==meta['bodyHash'])
                record={k:meta[k] for k in ('id','revision','bodyHash','bodyBytes')};record['body']=row['body']
                result['entries'].append(record)
                count=offset+len(result['entries']);result['complete']=count==len(entries);result['next']=None if result['complete'] else count
                if size(result)>MAX_PAGE:
                    result['entries'].pop();count=offset+len(result['entries']);result['complete']=False;result['next']=count
                    break
            require(bool(result['entries']) and size(result)<=MAX_PAGE)
            return result

    def finalize(self,request):
        uid(request['attemptId'])
        require(type(request['transferDigest']) is str and len(request['transferDigest'])==64 and all(c in '0123456789abcdef' for c in request['transferDigest']))
        with self.read() as db:
            value=self.current(db,request)
            require(type(request['count']) is int and request['count']==value['bodyEntryCount'])
            require(type(request['bytes']) is int and request['bytes']==value['bodyBytesTotal'])
            require(type(request['pages']) is int and (1<=request['pages']<=256 if request['count'] else request['pages']==0))
            # This acknowledges a directory check, NOT delivery or authority.
            return {**self.binding(value),'phase':'finalize','count':request['count'],'bytes':request['bytes'],
                'pages':request['pages'],'transferDigest':request['transferDigest'],'attemptId':request['attemptId'],'directoryChecked':True}

    def exchange(self,body):
        fields(body,'bookshelf');r=body['bookshelf'];require(type(r) is dict and r.get('format')==FORMAT)
        phase=r.get('phase')
        if phase=='manifest':
            fields(r,'format phase previous');return self.manifest(r['previous'])
        if phase=='bodies':
            fields(r,'format phase snapshotId manifestHash offset');return self.page(r)
        if phase=='finalize':
            fields(r,'format phase snapshotId manifestHash attemptId count bytes pages transferDigest');return self.finalize(r)
        raise ValueError('unknown_bookshelf_phase')
