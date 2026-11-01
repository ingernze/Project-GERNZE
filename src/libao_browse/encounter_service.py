"""Host-only local encounter API. No network route or model tool is registered here."""
import base64
import hashlib
import hmac
import json
import math
import re
import sqlite3

from .encounters import EncounterStore, FIELDS, _catalog_revision
from .security import BrowseError


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise BrowseError('input','参数超出允许范围')
    return value


def _identifier(value):
    if not isinstance(value,str) or not 1 <= len(value) <= 128 or not re.fullmatch(r'[A-Za-z0-9:_-]+',value):
        raise BrowseError('input','见闻ID无效')
    return value


def _query(value, required=False):
    if not isinstance(value,str) or len(value)>1000 or (required and not value.strip()):
        raise BrowseError('input','检索词无效')
    return value.strip()


def _terms(query):
    words=[]
    for word in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]{2,40}',query.casefold()):
        if re.fullmatch(r'[\u4e00-\u9fff]+',word) and len(word)>2:
            words.extend(word[i:i+2] for i in range(len(word)-1))
        elif len(word)>1:
            words.append(word)
    return set(words)


def _rank(rows,query):
    if not query:return [(0,row) for row in rows]
    terms=_terms(query)
    if not terms:return []
    ranked=[]
    for row in rows:
        source=json.loads(row[2]);body=json.loads(row[3])
        title=str(source.get('title','')).casefold()
        prose=' '.join(str(body.get(k,'')) for k in FIELDS).casefold()
        quotes=' '.join(str(e.get('quote','')) for e in body.get('evidence',[]) if isinstance(e,dict)).casefold()
        score=sum(3*(term in title)+2*(term in prose)+(term in quotes) for term in terms)
        if score:ranked.append((score,row))
    return sorted(ranked,key=lambda sr:(-sr[0],-sr[1][4],sr[1][0]))


def _coverage(value):
    if isinstance(value,str):return value[:300]
    if not isinstance(value,dict):return None
    allowed={'state','paragraphsRead','truncated','imagesRead','videoViewed','missing',
             'timedSeconds','durationSeconds','timedFraction','segmentsRead'}
    return {key:item[:300] if isinstance(item,str) else item
            for key,item in value.items() if key in allowed and
            (type(item) in (str,int,bool) or (type(item) is float and math.isfinite(item)))}


def _record(row):
    source=json.loads(row[2]);body=json.loads(row[3])
    visible={k:source.get(k) for k in ('id','platform','url','title','author','contentBasis','coverage','readAt')}
    visible['coverage']=_coverage(source.get('coverage'))
    if source.get('publishedAt'):visible['publishedAt']=source['publishedAt']
    # A legacy subtitle quote can carry timing; this API exports only the frozen citation contract.
    body={**body,'evidence':[{'segmentId':e['segmentId'],'quote':e['quote']} for e in body.get('evidence',[])]}
    return {'id':row[0],'revision':row[1],'source':visible,'body':body,'updatedAt':row[4],
            'trust':'external_untrusted','hostMemoryLayer':None,'userModified':bool(row[5])}


def _summary(row):
    source=json.loads(row[2]);body=json.loads(row[3])
    provenance=source.get('provenance') or {}
    return {'id':row[0],'revision':row[1],'title':source.get('title',''),
            'url':source.get('url',''),'provider':str(provenance.get('provider') or source.get('sourceLabel') or source.get('platform') or '')[:80],
            'publishedAt':source.get('publishedAt'),'readAt':source.get('readAt'),
            'updatedAt':row[4],'gist':body.get('encounter','')[:160],
            'evidenceCount':len(body.get('evidence',[])),
            'contentBasis':source.get('contentBasis'),'coverage':_coverage(source.get('coverage'))}


def _clip(value,limit):
    value=str(value or '')
    return value if len(value)<=limit else value[:limit-1]+'…'


def _context_entry(row,room):
    source=json.loads(row[2]);body=json.loads(row[3]);url=str(source.get('url') or '')
    title=_clip(source.get('title'),120)
    if not url:return None
    base={'id':row[0],'revision':row[1],'title':title,'url':url,
          'publishedAt':source.get('publishedAt')}
    evidence=body.get('evidence') or []
    quote=evidence[0] if evidence else None
    for cap in (240,120,80,40,20,0):
        for quote_cap in (120,80,40,0):
            item={**base,**{('understandingRevision' if key=='revision' else key):_clip(body.get(key),cap) if cap else ''
                          for key in FIELDS},
                  'contentBasis':source.get('contentBasis'),
                  'coverage':_coverage(source.get('coverage')),
                  'evidence':([{'segmentId':quote['segmentId'],'quote':quote['quote'][:quote_cap]}]
                              if quote and quote_cap else [])}
            # Keep uncertainty even when other prose must shrink to fit the host budget.
            item['missing']=_clip(body.get('missing'),min(cap or 40,80))
            text=(f"【外部见闻，未核验；ID {row[0]}；版本 {row[1]}】{title}\n"
                  f"来源：{url}；发布时间：{source.get('publishedAt') or '未知'}\n"
                  f"取得材料：{item['contentBasis']}；未覆盖：{item['missing']}\n"
                  f"事实（来源陈述）：{item['facts']}\n作者观点：{item['authorView']}\n"
                  f"推断（未核验）：{item['inference']}")
            for key,label in (('encounter','遇见'),('previousJudgment','先前判断'),
                              ('understandingRevision','认识修正'),('nextResponse','下次回应参考')):
                if item[key]:text+=f"\n{label}：{item[key]}"
            if item['evidence']:
                e=item['evidence'][0]
                text+=f"\n引文{('节选' if len(e['quote'])<len(quote['quote']) else '')} [{e['segmentId']}]：“{e['quote']}”"
            if len(text)<=room and any((item['facts'],item['authorView'],item['inference'],
                                       item['understandingRevision'],item['nextResponse'],item['evidence'])):
                return item,text
    return None


class EncounterService:
    def __init__(self,directory=None,*,store=None):
        # The caller chooses one explicit directory. No discovery of other files or accounts.
        self.store=store if store is not None else EncounterStore(directory)

    def _snapshot(self):
        with self.store.lock,self.store.connection() as db:
            db.execute('BEGIN')
            catalog=_catalog_revision(db)
            secret=db.execute("SELECT value FROM encounter_meta WHERE key='cursor_secret'").fetchone()[0]
            rows=db.execute('SELECT e.id,e.revision,e.source,e.body,e.updated,COALESCE(m.user_modified,0) '
                            'FROM encounters e LEFT JOIN encounter_modifications m ON m.id=e.id '
                            'WHERE e.deleted=0 ORDER BY e.updated DESC,e.id LIMIT 200').fetchall()
        return catalog,secret,rows

    def _cursor(self,offset,catalog,secret,query,limit):
        payload=json.dumps([offset,catalog,hashlib.sha256(query.encode()).hexdigest(),limit],separators=(',',':')).encode()
        mac=hmac.new(secret.encode(),payload,hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload+mac).decode().rstrip('=')

    def _offset(self,cursor,catalog,secret,query,limit):
        if cursor is None:return 0
        if not isinstance(cursor,str) or not 1<=len(cursor)<=512:raise BrowseError('input','分页游标无效')
        try:
            data=base64.b64decode(cursor+'='*(-len(cursor)%4),altchars=b'-_',validate=True)
            payload,mac=data[:-32],data[-32:]
            if not hmac.compare_digest(hmac.new(secret.encode(),payload,hashlib.sha256).digest(),mac):raise ValueError()
            offset,version,digest,saved_limit=json.loads(payload)
            if (type(offset) is not int or offset<1 or type(version) is not int or version!=catalog or
                digest!=hashlib.sha256(query.encode()).hexdigest() or saved_limit!=limit):raise ValueError()
            return offset
        except (ValueError,TypeError,UnicodeDecodeError,json.JSONDecodeError):
            raise BrowseError('input','分页游标无效') from None

    def _dispatch(self,command,p):
        if not isinstance(p,dict):raise BrowseError('input','参数应为对象')
        allowed={
            'encounters.list':{'query','limit','cursor'},'encounters.get':{'id'},
            'encounters.update':{'id','expectedRevision','patch'},
            'encounters.delete':{'id','expectedRevision'},
            'encounters.context':{'query','maxItems','maxChars','excludeIds'},
            'encounters.context.validate':{'catalogRevision'},
        }
        if command not in allowed or not set(p).issubset(allowed[command]):
            raise BrowseError('input','未知命令或参数')
        if command=='encounters.list':
            query=_query(p.get('query',''));limit=_integer(p.get('limit',20),1,50)
            catalog,secret,rows=self._snapshot();ranked=_rank(rows,query)
            offset=self._offset(p.get('cursor'),catalog,secret,query,limit)
            if offset>len(ranked):raise BrowseError('input','分页游标无效')
            page=ranked[offset:offset+limit]
            next_cursor=self._cursor(offset+limit,catalog,secret,query,limit) if offset+limit<len(ranked) else None
            return {'items':[_summary(row) for _,row in page],
                    'nextCursor':next_cursor,'catalogRevision':catalog}
        if command=='encounters.get':
            entry_id=_identifier(p.get('id'))
            catalog,_,rows=self._snapshot()
            for row in rows:
                if row[0]==entry_id:return {'item':_record(row),'catalogRevision':catalog}
            raise BrowseError('encounter_unavailable','见闻不存在或已删除')
        if command=='encounters.update':
            entry_id=_identifier(p.get('id'));revision=_integer(p.get('expectedRevision'),1,2**63-1)
            row=self.store.update_fields(entry_id,revision,p.get('patch'))
            record=_record((row['id'],row['revision'],json.dumps(row['source']),
                            json.dumps(row['body']),row['updatedAt'],1))
            return {'item':record,'catalogRevision':row['catalogRevision']}
        if command=='encounters.delete':
            entry_id=_identifier(p.get('id'));revision=_integer(p.get('expectedRevision'),1,2**63-1)
            result=self.store.delete_with_catalog(entry_id,revision)
            return {key:result[key] for key in ('deleted','id','revision','catalogRevision')}
        if command=='encounters.context.validate':
            prior=_integer(p.get('catalogRevision'),0,2**63-1)
            with self.store.lock,self.store.connection() as db:current=_catalog_revision(db)
            return {'current':prior==current,'catalogRevision':current}
        query=_query(p.get('query'),required=True)
        max_items=_integer(p.get('maxItems',3),1,3)
        max_chars=_integer(p.get('maxChars',1800),500,3000)
        exclude=p.get('excludeIds',[])
        if not isinstance(exclude,list) or len(exclude)>200:
            raise BrowseError('input','排除列表无效')
        excluded={_identifier(item) for item in exclude}
        catalog,_,rows=self._snapshot()
        items=[];blocks=[];used=0
        for _,row in _rank(rows,query):
            if row[0] in excluded:continue
            room=max_chars-used-(2 if blocks else 0)
            entry=_context_entry(row,room)
            if entry is None:continue
            item,block=entry;items.append(item);blocks.append(block)
            used+=len(block)+(2 if len(blocks)>1 else 0)
            if len(items)>=max_items:break
        result='\n\n'.join(blocks)
        return {'items':items,'contextText':result,'charCount':len(result),
                'catalogRevision':catalog,'trust':'external_untrusted'}

    def dispatch(self,command,params):
        try:return {'ok':True,'result':self._dispatch(command,params)}
        except BrowseError as exc:
            code={'stale_revision':'conflict','encounter_unavailable':'not_found',
                  'evidence':'input','note_format':'input'}.get(exc.code,'input')
            return {'ok':False,'error':{'code':code,'message':exc.message}}
        except (sqlite3.Error,ValueError,TypeError,KeyError):
            return {'ok':False,'error':{'code':'internal','message':'见闻服务暂不可用'}}
