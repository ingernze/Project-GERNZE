"""Negotiated, complete read-only research cache over the paired layer channel.

Never merged into user facts. Course text/raw chats/source archives never sent.
An omitted/invalid item disappears in the next complete monotonic snapshot;
there is no client push or partial-page replacement that could revive it.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from .research_catalog import ResearchAccess, ResearchCatalog, ResearchError, digest
from .research_context import ResearchJournal
from .research_summaries import ResearchSummaries, META, reference, normalized_refs

FORMAT='gernze-research-cache-v1'
FORMAT_V2='gernze-research-cache-v2'


def export_cache(db, server_id, scope, *, include_phone=False):
    if db.execute('PRAGMA user_version').fetchone()[0]!=4:
        raise ValueError('research_cache_unavailable')
    schema=db.execute("SELECT value FROM rc_meta WHERE key='summary_schema'").fetchone()
    if not schema or schema[0]!='2':raise ValueError('research_cache_unavailable')
    # Reader-only facade: does not acquire ownership, migrate, recover pending
    # turns, initialize a library, or construct a runtime in the publisher.
    catalog=ResearchCatalog(Path(db.execute('PRAGMA database_list').fetchone()[2]))
    journal=SimpleNamespace(catalog=catalog)
    journal._verify=lambda connection,manifest,access:ResearchJournal._verify(journal,connection,manifest,access)
    summaries=ResearchSummaries(journal)
    rows=db.execute('SELECT '+META+' FROM rc_summary_meta ORDER BY version LIMIT 129').fetchall()
    if len(rows)>128:raise ValueError('research_cache_limit')
    records=[];body_bytes=0
    for row in rows:
        try:
            group=json.loads(row['group_key']);courses=tuple(group['courses'])
            access=ResearchAccess('study',courses) if group['scene']=='study' else ResearchAccess()
            meta=summaries.verify(db,reference(row),access)
        except (ValueError,TypeError,KeyError):continue
        # Access above validates metadata ancestry only, not permission to read
        # a course body. The standard sync flow never fetches those bodies.
        is_course=group['scene']=='study'
        review=db.execute('SELECT status,reason FROM rc_summary_reviews WHERE summary_id=? AND revision=? AND body_hash=?',
                          (meta['id'],meta['revision'],meta['body_hash'])).fetchone()
        value={**reference(meta),'restriction':'study' if is_course else 'general','courses':list(courses),
               'facets':sorted({facet for item in meta['manifest'] for facet in catalog._selected(db,[(item['id'],item['revision'])],access,64000)[0]['facets']}),
               'trust':'research_summary','review':dict(review) if review else {'status':'pending','reason':''},
               'sources':meta['manifest'],'parents':normalized_refs(json.loads(meta['parents'])),
               'raw_refs':meta['raw_refs'],'body':None}
        if include_phone:value['phone_refs']=[]
        if not is_course:
            text=db.execute('SELECT body FROM rc_summary_bodies WHERE id=?',(meta['id'],)).fetchone()
            if not text or digest(text[0])!=meta['body_hash'] or len(text[0].encode('utf-8'))!=meta['body_bytes']:raise ValueError('research_cache_integrity')
            value['body']=text[0];body_bytes+=meta['body_bytes']
        if body_bytes>262144:raise ValueError('research_cache_limit')
        records.append(value)
    if include_phone:
        from .phone_research_summaries import available,verify,META as PHONE_META
        if available(db):
            phone_rows=db.execute('SELECT '+PHONE_META+' FROM rc_phone_summary_meta ORDER BY version LIMIT 129').fetchall()
            if len(phone_rows)+len(records)>128:raise ValueError('research_cache_limit')
            for row in phone_rows:
                try:meta=verify(journal,db,reference(row),ResearchAccess())
                except (ValueError,TypeError,KeyError):continue
                body=db.execute('SELECT body FROM rc_phone_summary_bodies WHERE id=?',(meta['id'],)).fetchone()
                if not body or digest(body[0])!=meta['body_hash'] or len(body[0].encode('utf-8'))!=meta['body_bytes']:raise ValueError('research_cache_integrity')
                body_bytes+=meta['body_bytes']
                if body_bytes>262144:raise ValueError('research_cache_limit')
                facets=sorted({f for item in meta['manifest'] for f in catalog._selected(db,[(item['id'],item['revision'])],ResearchAccess(),64000)[0]['facets']})
                checked=db.execute('SELECT status,reason FROM rc_summary_reviews WHERE summary_id=? AND revision=? AND body_hash=?',(meta['id'],meta['revision'],meta['body_hash'])).fetchone()
                review=dict(checked) if checked else {'status':'pending','reason':'手机原文整理，未独立核对'}
                records.append({**reference(meta),'restriction':'general','courses':[],'facets':facets,'trust':'research_summary','review':review,'sources':meta['manifest'],'parents':json.loads(meta['parents']),'raw_refs':meta['raw_refs'],'phone_refs':meta['phone_refs'],'body':body[0]})
    previous=db.execute("SELECT value FROM rc_meta WHERE key='phone_cache_sequence'").fetchone()
    sequence=int(previous[0])+1 if previous else 1
    if sequence>9007199254740991:raise ValueError('research_cache_sequence_limit')
    db.execute("INSERT OR REPLACE INTO rc_meta VALUES ('phone_cache_sequence',?)",(str(sequence),))
    result={'format':FORMAT_V2 if include_phone else FORMAT,'serverId':server_id,'scope_id':scope,'sequence':sequence,'complete':True,'records':records}
    from .conversation_store import encoded
    if len(encoded(result).encode('utf-8'))>1048576:raise ValueError('research_cache_limit')
    return result
