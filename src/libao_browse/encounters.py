"""External encounters ledger, deliberately unrelated to the four host memory layers."""
import sqlite3,json,hashlib,uuid,threading,time,unicodedata
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from .security import BrowseError,clean

FIELDS=('encounter','facts','authorView','inference','previousJudgment','revision','nextResponse','missing')
CITED_FIELDS=('facts','authorView','revision','nextResponse')
def note_contract():
    return {'requiredFields':[*FIELDS,'evidence'],'textMaxChars':1000,
            'requiredNonEmpty':['encounter','missing'],
            'evidenceRequiredWhenAnyNonEmpty':list(CITED_FIELDS),
            'evidence':{'maxItems':8,'requiredFields':['segmentId','quote'],'quoteMaxChars':300,
                        'matching':'exact_substring_of_this_read_source',
                        'metadata':'segmentId=metadata：只引用本次已取得的标题或简介原句',
                        'body':'segmentId=body：仅引用本次取得的公开文章正文或同题导言；不是视频转录',
                        'subtitles':'仅使用本次已取得的实际字幕ID；无字幕不得填写字幕引用'},
            'emptyFields':'没有对应观察、观点或认识修正就留空；四个需引文字段均空时可用evidence=[]。',
            'onSaveError':'校验失败会终止本次任务；不能自动重授权或重跑。'}

def validate_note(source,raw):
    if not isinstance(raw,dict) or set(raw)!=set(FIELDS)|{'evidence'}:raise BrowseError('note_format','note必须齐全且仅含九字段：'+','.join((*FIELDS,'evidence'))+'；不能携带工具、记忆层级或文件目标')
    body={}
    for key in FIELDS:
        value=raw[key]
        if not isinstance(value,str) or len(value)>1000:raise BrowseError('note_format','每个见闻字段最多1000字')
        body[key]=clean(value,1000)
    if not body['encounter'] or not body['missing']:raise BrowseError('note_format','请保留遇见内容和未覆盖部分')
    rows=(source.get('videoEvidence') or {}).get('segments',[])
    known={r['id']:r for r in rows}
    metadata=source.get('metadataText',source.get('text','') if source.get('contentBasis') in ('metadata','title_only') else '')
    known['metadata']={'text':source.get('title','')+'\n'+metadata}
    if source.get('contentBasis')=='public_text' and source.get('publicText',{}).get('relation')=='same_topic_only':
        known['body']={'text':source.get('text','')}
    if source.get('platform')=='web' and source.get('contentBasis')=='article_text':
        known['body']={'text':source.get('text','')}
        for row in source.get('articleEvidence',{}).get('segments',[])[:80]:
            if isinstance(row,dict) and isinstance(row.get('id'),str) and isinstance(row.get('text'),str) and row['text'] in source.get('text',''):
                known[row['id']]={'text':row['text']}
    evidence=raw['evidence']
    if not isinstance(evidence,list) or len(evidence)>8:raise BrowseError('evidence','最多引用8条已读取证据')
    checked=[]
    for e in evidence:
        if not isinstance(e,dict) or set(e)!= {'segmentId','quote'}:raise BrowseError('evidence','引用字段不符')
        key,quote=e['segmentId'],e['quote']
        if not isinstance(key,str) or not isinstance(quote,str) or not 1<=len(quote)<=300 or key not in known or quote not in known[key]['text']:raise BrowseError('evidence','引用须为本次已读来源标题/简介(metadata)或实际字幕ID中的精确原句；不能伪造来源、时间或引用')
        row=known[key];checked.append({'segmentId':key,'quote':clean(quote,300),**({'start':row['start'],'end':row['end']} if 'start' in row else {})})
    if any(body[k] for k in CITED_FIELDS) and not checked:raise BrowseError('evidence','facts、authorView、revision、nextResponse任一非空时，evidence必须附本次已读来源的精确原句；元资料用metadata，有字幕才用实际字幕ID。未知字段应留空，不编造引用。')
    return {**body,'evidence':checked}

def _source_fingerprint(source):
    """Identity of captured material, never of a generated note or read attempt.

    v1 deliberately keeps content query strings: for an unknown publisher,
    removing them could merge different articles. It excludes every operational
    source field by selecting only URL, basis, and actual captured material.
    """
    url=source.get('url')
    # Legacy local title-only records had no URL. Keep exact-digest behavior
    # without claiming a stable publisher identity or making them citable links.
    if url is None:return None
    if not isinstance(url,str) or not 1<=len(url)<=1000 or '\\' in url:
        raise BrowseError('source_identity','来源链接无法形成稳定身份')
    try:
        parts=urlsplit(url.strip());port=parts.port
        host=parts.hostname
    except ValueError:
        raise BrowseError('source_identity','来源链接无法形成稳定身份') from None
    if (parts.scheme.lower() not in ('http','https') or not host or
        parts.username or parts.password or any(c.isspace() for c in url)):
        raise BrowseError('source_identity','来源链接无法形成稳定身份')
    scheme=parts.scheme.lower()
    authority=('['+host.lower()+']' if ':' in host else host.lower())
    if port is not None and port!=({'https':443,'http':80}[scheme]):authority+=':'+str(port)
    path=parts.path or '/'
    if path.endswith('/') and not path.endswith('//') and path!='/':path=path[:-1]
    query=urlencode([(key,value) for key,value in parse_qsl(parts.query,keep_blank_values=True)
                     if not (key.casefold().startswith('utm_') or key.casefold() in ('fbclid','gclid'))])
    canonical=urlunsplit((scheme,authority,path,query,''))
    def normalized(value):
        return ' '.join(unicodedata.normalize('NFC',value).split()) if isinstance(value,str) else ''
    basis=source.get('contentBasis')
    if not isinstance(basis,str) or not basis:
        raise BrowseError('source_identity','来源内容类型缺失')
    metadata=normalized(source.get('title'))+'\n'+normalized(source.get('metadataText'))
    if basis in ('article_text','public_text'):
        captured=normalized(source.get('text'))
        if not captured:raise BrowseError('source_identity','正文来源缺少实际读取内容')
        material=metadata+'\n'+captured
    elif basis=='transcript':
        rows=(source.get('videoEvidence') or {}).get('segments',[])
        captured='\n'.join(normalized(row.get('text')) for row in rows if isinstance(row,dict))
        if not captured.strip():raise BrowseError('source_identity','字幕来源缺少实际读取内容')
        material=metadata+'\n'+captured
    else:
        material=normalized(source.get('title'))+'\n'+normalized(source.get('metadataText',source.get('text')))
    if not material.strip():raise BrowseError('source_identity','没有可识别的已读来源内容')
    payload=json.dumps([canonical,source.get('platform'),basis,material],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(('source-fingerprint-v1\n'+payload).encode()).hexdigest()

def _catalog_revision(db):
    return int(db.execute("SELECT value FROM encounter_meta WHERE key='catalog_revision'").fetchone()[0])

def _bump_catalog(db):
    db.execute("UPDATE encounter_meta SET value=CAST(value AS INTEGER)+1 WHERE key='catalog_revision'")
    return _catalog_revision(db)

class EncounterStore:
    def __init__(self,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/'external-encounters.sqlite3';self.lock=threading.RLock()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS encounters(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,source TEXT NOT NULL,body TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL,digest TEXT UNIQUE)')
            db.execute('CREATE TABLE IF NOT EXISTS encounter_history(id TEXT,revision INTEGER,body TEXT,PRIMARY KEY(id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS encounter_digests(digest TEXT PRIMARY KEY,entry_id TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO encounter_digests SELECT digest,id FROM encounters WHERE digest IS NOT NULL')
            db.execute('CREATE TABLE IF NOT EXISTS encounter_source_fingerprints(fingerprint TEXT PRIMARY KEY,entry_id TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS encounter_modifications(id TEXT PRIMARY KEY,user_modified INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS encounter_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO encounter_meta VALUES ('catalog_revision','0')")
            db.execute("INSERT OR IGNORE INTO encounter_meta VALUES ('cursor_secret',?)",(uuid.uuid4().hex,))
            # Migration is an identity index rebuild, not a new encounter/edit.
            for entry_id,serialized,deleted in db.execute('SELECT id,source,deleted FROM encounters ORDER BY updated,id'):
                if deleted:continue  # old deletion scrubbed source; never invent its identity
                try:fingerprint=_source_fingerprint(json.loads(serialized))
                except (BrowseError,ValueError,TypeError,AttributeError):continue
                if fingerprint is None:continue
                db.execute('INSERT OR IGNORE INTO encounter_source_fingerprints VALUES (?,?)',(fingerprint,entry_id))
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:yield db
        finally:db.close()
    def save(self,source,raw,*,entry_id=None,expected_revision=None):
        body=validate_note(source,raw);s=json.dumps(source,ensure_ascii=False,sort_keys=True);b=json.dumps(body,ensure_ascii=False,sort_keys=True)
        digest=hashlib.sha256((s+'\n'+b).encode()).hexdigest()
        fingerprint=_source_fingerprint(source)
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if entry_id is None:
                old=db.execute('SELECT e.id,e.revision,e.deleted FROM encounter_source_fingerprints f JOIN encounters e ON e.id=f.entry_id WHERE f.fingerprint=?',(fingerprint,)).fetchone()
                if old:
                    if old[2]:raise BrowseError('deleted','这份内容已删除，重复保存不会复活')
                    return {'id':old[0],'revision':old[1],'alreadySaved':True,'hostMemoryChanged':False}
                old=db.execute('SELECT e.id,e.revision,e.deleted FROM encounter_digests d JOIN encounters e ON e.id=d.entry_id WHERE d.digest=?',(digest,)).fetchone()
                if old:
                    if old[2]:raise BrowseError('deleted','这份内容已删除，重复保存不会复活')
                    if fingerprint is not None:db.execute('INSERT OR IGNORE INTO encounter_source_fingerprints VALUES (?,?)',(fingerprint,old[0]))
                    return {'id':old[0],'revision':old[1],'alreadySaved':True,'hostMemoryChanged':False}
                if db.execute('SELECT COUNT(*) FROM encounters').fetchone()[0]>=200:raise BrowseError('ledger_full','小样最多保存200条外部见闻')
                entry_id=uuid.uuid4().hex;revision=1
                db.execute('INSERT INTO encounters VALUES (?,?,?,?,0,?,?)',(entry_id,revision,s,b,int(time.time()),digest))
                if fingerprint is not None:db.execute('INSERT INTO encounter_source_fingerprints VALUES (?,?)',(fingerprint,entry_id))
            else:
                old=db.execute('SELECT revision,source,body,deleted FROM encounters WHERE id=?',(entry_id,)).fetchone()
                if not old or old[3] or type(expected_revision) is not int or old[0]!=expected_revision or old[1]!=s:raise BrowseError('stale_revision','见闻版本已变化、被删除或来源不符，请重新打开')
                db.execute('INSERT INTO encounter_history VALUES (?,?,?)',(entry_id,old[0],old[2]));revision=old[0]+1
                db.execute('UPDATE encounters SET revision=?,body=?,updated=?,digest=? WHERE id=?',(revision,b,int(time.time()),digest,entry_id))
            db.execute('INSERT OR IGNORE INTO encounter_digests VALUES (?,?)',(digest,entry_id))
            _bump_catalog(db)
        return {'id':entry_id,'revision':revision,'hostMemoryChanged':False}
    def list(self):
        with self.lock,self.connection() as db:
            rows=db.execute('SELECT id,revision,source,body,updated FROM encounters WHERE deleted=0 ORDER BY updated DESC,id LIMIT 200').fetchall()
        return [{'id':r[0],'revision':r[1],'source':json.loads(r[2]),'body':json.loads(r[3]),'updatedAt':r[4],'trust':'external_untrusted','hostMemoryLayer':None} for r in rows]
    def get(self,entry_id):
        """One bounded active entry; caller must first enforce run membership."""
        with self.lock,self.connection() as db:
            row=db.execute('SELECT id,revision,source,body,updated FROM encounters WHERE id=? AND deleted=0',(entry_id,)).fetchone()
        if not row:raise BrowseError('encounter_unavailable','本次见闻不存在或已删除')
        source=json.loads(row[2]);body=json.loads(row[3])
        # Never return saved subtitle arrays, visual frames, or unrelated entries.
        result={key:source.get(key) for key in ('id','platform','url','title','author','contentBasis','coverage','readAt','publishedAt') if key in source}
        result['excerpt']=source.get('text','')[:2000]
        if 'publicText' in source:result['publicText']=source['publicText']
        return {'id':row[0],'revision':row[1],'source':result,'body':body,'updatedAt':row[4],
                'trust':'external_untrusted','hostMemoryLayer':None,'readOnly':True}
    def delete(self,entry_id,revision):
        self.delete_with_catalog(entry_id,revision)
        return {'deleted':True,'hostMemoryChanged':False}

    def delete_with_catalog(self,entry_id,revision):
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT revision,deleted FROM encounters WHERE id=?',(entry_id,)).fetchone()
            if not old or old[1]:raise BrowseError('encounter_unavailable','见闻不存在或已删除')
            if type(revision) is not int or old[0]!=revision:raise BrowseError('stale_revision','版本已变化或已删除')
            db.execute('UPDATE encounters SET body=?,source=?,deleted=1,revision=revision+1,updated=? WHERE id=?',('{}','{}',int(time.time()),entry_id));db.execute('DELETE FROM encounter_history WHERE id=?',(entry_id,))
            db.execute('DELETE FROM encounter_modifications WHERE id=?',(entry_id,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='encounter_reflections'").fetchone():
                db.execute('DELETE FROM encounter_reflections WHERE entry_id=?',(entry_id,))
            catalog=_bump_catalog(db)
        return {'deleted':True,'hostMemoryChanged':False,'id':entry_id,'revision':old[0]+1,'catalogRevision':catalog}

    def update_fields(self,entry_id,expected_revision,patch):
        """Host-only edit, CAS and quote validation in the same write transaction."""
        if (not isinstance(patch,dict) or not patch or
            not set(patch).issubset(FIELDS) or
            any(not isinstance(v,str) or len(v)>1000 for v in patch.values())):
            raise BrowseError('note_format','只能修改八个见闻文本字段，每项最多1000字')
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision,source,body,deleted FROM encounters WHERE id=?',(entry_id,)).fetchone()
            if not row or row[3]:raise BrowseError('encounter_unavailable','见闻不存在或已删除')
            if type(expected_revision) is not int or expected_revision!=row[0]:
                raise BrowseError('stale_revision','见闻已修订，请重新打开')
            source=json.loads(row[1]);old=json.loads(row[2])
            raw={**old,**patch,'evidence':[{'segmentId':e['segmentId'],'quote':e['quote']} for e in old['evidence']]}
            body=validate_note(source,raw)
            serialized=json.dumps(body,ensure_ascii=False,sort_keys=True)
            digest=hashlib.sha256((row[1]+'\n'+serialized).encode()).hexdigest()
            db.execute('INSERT INTO encounter_history VALUES (?,?,?)',(entry_id,row[0],row[2]))
            now=int(time.time());revision=row[0]+1
            db.execute('UPDATE encounters SET revision=?,body=?,updated=?,digest=? WHERE id=?',(revision,serialized,now,digest,entry_id))
            db.execute('INSERT OR IGNORE INTO encounter_digests VALUES (?,?)',(digest,entry_id))
            db.execute('INSERT OR IGNORE INTO encounter_modifications VALUES (?,1)',(entry_id,))
            catalog=_bump_catalog(db)
            return {'id':entry_id,'revision':revision,'source':source,'body':body,'updatedAt':now,
                    'userModified':True,'catalogRevision':catalog}
