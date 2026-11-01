"""Paired-host research raw archive, separate from facts and runtime history.

Receipts are phone-host attestations, not signed proof of a historical model
request. Current-source status is checked separately on explicit dated reads.
"""
import hashlib,json,sqlite3
from types import SimpleNamespace
from .conversation_store import encoded,uid
from .phone_archive import PhoneArchive,ZERO,valid_turn,chain

FORMAT='gernze-phone-research-raw-v1'
USE_FORMAT='gernze-phone-research-use-v1'
USE_FORMAT_V2='gernze-phone-research-use-v2'
SOURCE_KEYS={'id','revision','body_hash','restriction','courses','facets','trust','review','sources','parents','raw_refs'}

def sha(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('invalid_research_digest')

def reference(value):
    if type(value) is not dict or set(value)!={'id','revision','body_hash'}:raise ValueError('invalid_research_reference')
    uid(value['id']);uid(value['revision']);sha(value['body_hash'])

def validate_receipt(receipt,turn,session,server,scope):
    if type(receipt) is not dict or set(receipt)!={'format','cache','request','source'} or receipt['format'] not in (USE_FORMAT,USE_FORMAT_V2):raise ValueError('invalid_research_receipt')
    cache=receipt['cache'];req=receipt['request'];source=receipt['source']
    if type(cache) is not dict or set(cache)!={'serverId','scope_id','sequence','fingerprint'} or cache['serverId']!=server or cache['scope_id']!=scope or type(cache['sequence']) is not int or not 1<=cache['sequence']<=9007199254740991:raise ValueError('research_pairing_mismatch')
    sha(cache['fingerprint'])
    if type(req) is not dict or set(req)!={'id','sessionId','inputHash'} or req['sessionId']!=session:raise ValueError('invalid_research_request')
    uid(req['id']);sha(req['inputHash'])
    if req['inputHash']!=hashlib.sha256(turn['user'].encode('utf-8')).hexdigest():raise ValueError('research_input_changed')
    if type(source) is not dict or set(source)!=(SOURCE_KEYS|{'phone_refs'} if receipt['format']==USE_FORMAT_V2 else SOURCE_KEYS) or source['restriction']!='general' or source['courses']!=[] or source['trust']!='research_summary':raise ValueError('research_scope_denied')
    if receipt['format']==USE_FORMAT_V2:
        from .phone_research_summaries import phone_refs
        if source['phone_refs']:phone_refs(source['phone_refs'])
        elif source['phone_refs']!=[]:raise ValueError('invalid_phone_summary_refs')
    reference({k:source[k] for k in ('id','revision','body_hash')})
    facets=source['facets'];review=source['review']
    if type(facets) is not list or not 1<=len(facets)<=2 or any(type(f) is not str or f not in ('encounter','interest') for f in facets) or len(set(facets))!=len(facets):raise ValueError('research_scope_denied')
    if type(review) is not dict or set(review)!={'status','reason'} or review['status'] not in ('pending','supported','defer') or type(review['reason']) is not str or len(review['reason'])>300:raise ValueError('invalid_research_review')
    from .research_context import merge_exposures
    if type(source['sources']) is not list or not 1<=len(source['sources'])<=64:raise ValueError('invalid_research_sources')
    manifest=merge_exposures([source['sources']])
    if not manifest:raise ValueError('invalid_research_sources')
    for item in manifest:
        reference({k:item[k] for k in ('id','revision','body_hash')})
        if item['restriction']!='general' or item['courses']!=[] or type(item['source_versions']) is not dict or not 1<=len(item['source_versions'])<=256:raise ValueError('research_scope_denied')
        for ident,version in item['source_versions'].items():uid(ident);uid(version)
    if type(source['parents']) is not list or len(source['parents'])>64:raise ValueError('invalid_research_parents')
    for parent in source['parents']:reference(parent)
    raw=source['raw_refs']
    if type(raw) is not dict or not 1<=len(raw)<=256:raise ValueError('invalid_research_raw_refs')
    for ident,digest in raw.items():uid(ident);sha(digest)
    return receipt

class PhoneResearchArchive(PhoneArchive):
    def __init__(self,journal,server_id=None,scope=None):
        super().__init__(journal);self.journal=journal;self.server_id=server_id;self.scope=scope

    @staticmethod
    def ready(db,create=False):
        if db is None:return False
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='pr_schema' AND type='table'").fetchone()
        if not exists:
            if not create:return False
            db.execute('CREATE TABLE pr_schema(version INTEGER NOT NULL)');db.execute('INSERT INTO pr_schema VALUES (1)')
        if [r[0] for r in db.execute('SELECT version FROM pr_schema')] not in ([1],[2]):raise ValueError('updated_research_archive_required')
        if create:
            db.execute('CREATE TABLE IF NOT EXISTS pr_sessions(device TEXT NOT NULL,session TEXT NOT NULL,server TEXT NOT NULL,scope TEXT NOT NULL,base INTEGER NOT NULL,next INTEGER NOT NULL,chain TEXT NOT NULL,PRIMARY KEY(device,session))')
            db.execute('CREATE TABLE IF NOT EXISTS pr_meta(device TEXT NOT NULL,session TEXT NOT NULL,seq INTEGER NOT NULL,user_at TEXT,assistant_at TEXT,kind TEXT NOT NULL,request_id TEXT,content_hash TEXT NOT NULL,chain TEXT NOT NULL,PRIMARY KEY(device,session,seq))')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS pr_request ON pr_meta(device,request_id) WHERE request_id IS NOT NULL')
            db.execute('CREATE TABLE IF NOT EXISTS pr_bodies(device TEXT NOT NULL,session TEXT NOT NULL,seq INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(device,session,seq))')
            db.execute('CREATE TABLE IF NOT EXISTS pr_receipts(device TEXT NOT NULL,session TEXT NOT NULL,seq INTEGER NOT NULL,receipt TEXT NOT NULL,message_bytes INTEGER NOT NULL,user_chars INTEGER NOT NULL,received_at TEXT NOT NULL,PRIMARY KEY(device,session,seq))')
            db.execute('UPDATE pr_schema SET version=2')
        return True

    def exchange(self,device,body):
        uid(device);uid(self.server_id);uid(self.scope)
        if type(body) is not dict or set(body)!={'format','serverId','scope_id','sessionId','baseStart','start','previous','turns'} or body['format']!=FORMAT or len(encoded(body).encode('utf-8'))>524288:raise ValueError('invalid_research_raw_exchange')
        if body['serverId']!=self.server_id or body['scope_id']!=self.scope:raise ValueError('research_pairing_mismatch')
        sid=body['sessionId'];base=body['baseStart'];start=body['start'];previous=body['previous'];turns=body['turns']
        if type(sid) is not str or not 1<=len(sid)<=100 or any(ord(c)<32 for c in sid) or type(base) is not int or type(start) is not int or not 0<=base<=start<=100000 or type(turns) is not list or len(turns)>16 or start+len(turns)>100000:raise ValueError('invalid_research_raw_exchange')
        sha(previous)
        request_ids=set()
        for i,t in enumerate(turns):
            if type(t) is not dict or set(t)!={'index','user','assistant','userAt','assistantAt','research'}:raise ValueError('invalid_research_raw_turn')
            valid_turn({k:v for k,v in t.items() if k!='research'},start+i)
            if t['research'] is not None:
                validate_receipt(t['research'],t,sid,self.server_id,self.scope)
                request=t['research']['request']['id']
                if request in request_ids:raise ValueError('duplicate_research_request')
                request_ids.add(request)
            if start+i==base and t['research'] is None:raise ValueError('research_tail_must_begin_with_receipt')
        with self.connection(True) as db:
            self.ready(db,True)
            legacy=db.execute('SELECT count FROM sessions WHERE device=? AND session=?',(device,sid)).fetchone()
            if (legacy['count'] if legacy else 0)!=base:raise ValueError('ordinary_prefix_not_confirmed')
            old=db.execute('SELECT * FROM pr_sessions WHERE device=? AND session=?',(device,sid)).fetchone()
            if old and (old['base']!=base or old['server']!=self.server_id or old['scope']!=self.scope):raise ValueError('research_archive_binding_changed')
            count,current=(old['next'],old['chain']) if old else (base,ZERO)
            if not turns:return {'format':FORMAT,'sessionId':sid,'baseStart':base,'next':count,'chain':current,'accepted':0}
            if start>count:raise ValueError('research_raw_cursor_changed')
            expected=ZERO if start==base else db.execute('SELECT chain FROM pr_meta WHERE device=? AND session=? AND seq=?',(device,sid,start-1)).fetchone()[0]
            if previous!=expected:raise ValueError('research_raw_source_changed')
            digest=previous;accepted=0
            for t in turns:
                digest=chain(digest,t);seq=t['index'];text=encoded(t);content_hash=hashlib.sha256(text.encode('utf-8')).hexdigest()
                if seq<count:
                    same=db.execute('SELECT content_hash,chain FROM pr_meta WHERE device=? AND session=? AND seq=?',(device,sid,seq)).fetchone()
                    if not same or same['content_hash']!=content_hash or same['chain']!=digest:raise ValueError('research_raw_source_changed')
                else:
                    receipt=t['research'];req=receipt['request']['id'] if receipt else None
                    db.execute('INSERT INTO pr_bodies VALUES (?,?,?,?)',(device,sid,seq,text))
                    db.execute('INSERT INTO pr_meta VALUES (?,?,?,?,?,?,?,?,?)',(device,sid,seq,t['userAt'],t['assistantAt'],'research' if receipt else 'plain',req,content_hash,digest));accepted+=1
                    if receipt:
                        from .conversation_store import stamp
                        messages=[{'role':'user','content':t['user']},{'role':'assistant','content':t['assistant']}]
                        db.execute('INSERT INTO pr_receipts VALUES (?,?,?,?,?,?,?)',(device,sid,seq,encoded(receipt),len(encoded(messages).encode('utf-8')),len(t['user']),stamp()))
            if start+len(turns)>count:count=start+len(turns);current=digest
            db.execute('INSERT OR REPLACE INTO pr_sessions VALUES (?,?,?,?,?,?,?)',(device,sid,self.server_id,self.scope,base,count,current))
            return {'format':FORMAT,'sessionId':sid,'baseStart':base,'next':count,'chain':current,'accepted':accepted}

    def metadata(self):
        with self.connection() as db:
            if not self.ready(db):return []
            return [dict(r) for r in db.execute('SELECT device,session,seq,user_at,assistant_at,kind,request_id FROM pr_meta ORDER BY device,session,seq')]

    def raw(self,device,session,index):
        with self.connection() as db:
            if not self.ready(db):return None
            row=db.execute('SELECT b.payload,m.content_hash FROM pr_bodies b JOIN pr_meta m USING(device,session,seq) WHERE device=? AND session=? AND seq=?',(device,session,index)).fetchone()
            if not row:return None
            if hashlib.sha256(row['payload'].encode('utf-8')).hexdigest()!=row['content_hash']:raise ValueError('research_archive_integrity')
            return json.loads(row['payload'])

    def source_status(self,receipt):
        """Metadata only; never loads course/research/chat body for this label."""
        from .research_catalog import ResearchCatalog,ResearchAccess
        from .research_context import ResearchJournal
        from .research_summaries import ResearchSummaries,reference as summary_ref,normalized_refs
        catalog=ResearchCatalog(self.journal)
        if not catalog.path.is_file():return 'unavailable'
        try:
            with catalog.connection() as db:
                if db.execute('PRAGMA user_version').fetchone()[0]!=4:return 'unavailable'
                journal=SimpleNamespace(catalog=catalog)
                journal._verify=lambda conn,manifest,access:ResearchJournal._verify(journal,conn,manifest,access)
                from .phone_research_summaries import verify_any
                src=receipt['source'];meta=verify_any(journal,db,summary_ref(src),ResearchAccess())
                facets=sorted({f for item in meta['manifest'] for f in catalog._selected(db,[(item['id'],item['revision'])],ResearchAccess(),64000)[0]['facets']})
                current={'sources':meta['manifest'],'parents':normalized_refs(json.loads(meta['parents'])),'raw_refs':meta['raw_refs'],'facets':facets}
                if src.get('phone_refs') or meta.get('phone_refs'):current['phone_refs']=meta.get('phone_refs',[])
                return 'current' if all(encoded(src[k])==encoded(v) for k,v in current.items()) else 'changed'
        except (ValueError,TypeError,KeyError):return 'changed'
        except (sqlite3.Error,OSError):return 'unavailable'
