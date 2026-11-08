"""Local project knowledge. Work writer is separate from the app's read-only facade."""
from contextlib import contextmanager
from pathlib import Path
import hashlib,json,os,re,time,unicodedata,uuid

MAX_BODY=32000
MAX_INDEX=2_000_000
SNAPSHOT_FORMAT='gernze-project-knowledge-v1'
def uid(x):
    if type(x) is not str or str(uuid.UUID(x))!=x:raise ValueError('invalid_knowledge_id')
    return x
def sha(raw):return hashlib.sha256(raw).hexdigest()
def text(x,limit):
    if type(x) is not str or not x.strip() or '\0' in x or len(x.encode('utf-8'))>limit:raise ValueError('invalid_knowledge_text')
    return x
def packed(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def fresh():return str(uuid.uuid4())
def atomic(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)
def unlinked(path):
    for p in (path,*path.parents):
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():raise ValueError('linked_knowledge_path')
    return path
def explicit_search(value):
    if type(value) is not str or len(value)>8000:return False
    value=unicodedata.normalize('NFKC',value).strip()
    if re.search(r'不要|不必|不用|无需|别|不需要|停止|取消',value):return False
    return bool(re.match(r'^(?:(?:请|帮我|麻烦|能否|能不能)\s*)?(?:(?:搜索|检索|查找|查阅|查一下)(?:一下)?\s*(?:我的|我们(?:的)?|这个)?(?:知识库|资料库)|从(?:我的|我们(?:的)?)?(?:知识库|资料库)(?:里|中)?(?:搜索|检索|查找))',value))

class KnowledgeReader:
    """No create, update, organize or withdraw method is exposed here."""
    def __init__(self,root):
        self.root=Path(root)
        if not self.root.is_absolute():raise ValueError('absolute_knowledge_root_required')
        unlinked(self.root)
    def _load(self):
        p=unlinked(self.root/'索引.json')
        with p.open('rb') as f:raw=f.read(MAX_INDEX+1)
        if len(raw)>MAX_INDEX:raise ValueError('knowledge_index_limit')
        def unique(pairs):
            d={}
            for k,v in pairs:
                if k in d:raise ValueError('duplicate_knowledge_key')
                d[k]=v
            return d
        data=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
        if data.get('schema_version')!=1 or data.get('scope')!='current_project_work_mode':raise ValueError('unsupported_knowledge_index')
        if type(data.get('revision')) is not int or not 0<=data['revision']<=9007199254740991:raise ValueError('invalid_knowledge_revision')
        for key in ('items','courses','collections'):
            data.setdefault(key,[])
            if type(data[key]) is not list or len(data[key])>5000:raise ValueError('knowledge_index_limit')
            ids=[uid(e['id']) for e in data[key]]
            if len(ids)!=len(set(ids)):raise ValueError('duplicate_knowledge_id')
        for c in data['collections']:
            uid(c['revision']);text(c['title'],500)
            if c['category'] not in ('course','encounter','interest','expression_research'):raise ValueError('invalid_collection_category')
            if c['category']=='course':uid(c['course_id'])
            elif c['course_id'] is not None:raise ValueError('invalid_course_scope')
        return data
    @staticmethod
    def metadata(item):
        return {k:item[k] for k in ('id','revision','title','type','state','category','collection_id','course_id','origin','source_ref','body_hash','body_bytes','previous','related','related_revision','review_status','reply_use_granted','original') if k in item}
    def _eligible(self,data,item,seen=()):
        if item.get('state')!='active' or item['id'] in seen or len(seen)>16:return False
        if not item.get('related'):return True
        parent=next((e for e in data['items'] if e['id']==item['related']),None)
        return bool(parent and parent.get('revision')==item.get('related_revision') and self._eligible(data,parent,(*seen,item['id'])))
    def catalog(self):
        d=self._load();return {'library_id':d.get('library_id'),'courses':d['courses'],'revision':d['revision'],'collections':d['collections'],'entries':[self.metadata(e) for e in d['items']],'readOnly':True}
    def snapshot(self,course_ids,server_id,scope_id):
        uid(server_id);uid(scope_id)
        if type(course_ids) is not list or len(course_ids)>100:raise ValueError('invalid_download_courses')
        for ident in course_ids:uid(ident)
        if len(set(course_ids))!=len(course_ids):raise ValueError('invalid_download_courses')
        d=self._load();uid(d.get('library_id'));selected=set(course_ids)
        if not selected<={c['id'] for c in d['courses']}:raise ValueError('download_course_missing')
        fingerprint=sha(packed(d).encode('utf-8'));entries=[];total=0
        for e in d['items']:
            if e.get('type')!='knowledge_note' or e.get('category')!='course' or e.get('course_id') not in selected or not self._eligible(d,e):continue
            total+=e['body_bytes']
            if total>1_500_000 or len(entries)>=1000:raise ValueError('selected_courses_too_large')
            metadata=self.metadata(e);metadata.pop('original',None)
            entries.append({**metadata,'body':self._body(e)})
        value={'format':SNAPSHOT_FORMAT,'serverId':server_id,'scope_id':scope_id,'libraryId':d['library_id'],'sequence':d['revision'],'libraryFingerprint':fingerprint,'courses':[c for c in d['courses'] if c['id'] in selected],'collections':[c for c in d['collections'] if c['category']=='course' and c['course_id'] in selected],'entries':entries,'complete':True}
        if sha(packed(self._load()).encode('utf-8'))!=fingerprint:raise ValueError('knowledge_changed_during_export')
        value['hash']=sha(packed(value).encode('utf-8'))
        if len(packed(value).encode('utf-8'))>2_000_000:raise ValueError('selected_courses_too_large')
        return value
    def _body(self,item):
        ident,revision=uid(item['id']),uid(item['revision'])
        p=unlinked(self.root/'正文'/ident/(revision+'.md'))
        with p.open('rb') as f:raw=f.read(MAX_BODY+1)
        if len(raw)>MAX_BODY or len(raw)!=item['body_bytes'] or sha(raw)!=item['body_hash']:raise ValueError('knowledge_body_changed')
        return raw.decode('utf-8')
    def read(self,ident,revision):
        uid(ident);uid(revision);d=self._load();item=next((e for e in d['items'] if e['id']==ident),None)
        if not item or item['revision']!=revision:raise ValueError('knowledge_revision_changed')
        if item.get('type')!='knowledge_note':return {'metadata':self.metadata(item),'body':None,'detail':'既有参考记录，原报告尚未接入正文读取。'}
        if not self._eligible(d,item):raise ValueError('knowledge_unavailable')
        body=self._body(item)
        if packed(self._load())!=packed(d):raise ValueError('knowledge_changed_during_read')
        return {'metadata':self.metadata(item),'body':body,'readOnly':True}
    def search(self,*,user_text,query,course_id):
        # Host must pass the actual current user input and trusted teacher binding,
        # never fields invented by a model. No search runs on a generic teaching request.
        if not explicit_search(user_text):raise ValueError('explicit_knowledge_search_required')
        uid(course_id);text(query,300);d=self._load()
        if not any(c['id']==course_id for c in d['courses']):raise ValueError('teacher_course_unavailable')
        tokens=unicodedata.normalize('NFKC',query).casefold().split();results=[];scanned=0
        for e in d['items']:
            # Scope and state checks precede all body access, including snippets.
            if e.get('type')!='knowledge_note' or e.get('category')!='course' or e.get('course_id')!=course_id or not self._eligible(d,e):continue
            if scanned+e['body_bytes']>256000:break
            body=self._body(e);scanned+=e['body_bytes'];hay=unicodedata.normalize('NFKC',e['title']+'\n'+body).casefold()
            if all(t in hay for t in tokens):
                at=next((body.casefold().find(t) for t in tokens if t in body.casefold()),0);start=max(0,at-120)
                results.append({'metadata':self.metadata(e),'excerpt':body[start:start+1200]})
            if len(results)==5:break
        if packed(self._load())!=packed(d):raise ValueError('knowledge_changed_during_search')
        return {'course_id':course_id,'results':results,'readOnly':True,'scan_bytes':scanned,'bounded':True}

class KnowledgeWork(KnowledgeReader):
    """Only project work-mode tooling constructs this writer, never chat endpoints."""
    @contextmanager
    def _edit(self):
        import msvcrt
        self.root.mkdir(parents=True,exist_ok=True);unlinked(self.root)
        with unlinked(self.root/'.work.lock').open('a+b') as f:
            f.seek(0,2)
            if not f.tell():f.write(b'0');f.flush()
            end=time.monotonic()+5
            while True:
                try:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()>end:raise ValueError('knowledge_busy')
                    time.sleep(.1)
            try:
                d=self._load();before=d['revision'];original=packed(d);d.setdefault('library_id',fresh());yield d
                if self._load()['revision']!=before:raise ValueError('knowledge_index_changed')
                if packed(d)==original:return
                d['revision']=before+1;raw=packed(d).encode('utf-8')
                if len(raw)>MAX_INDEX:raise ValueError('knowledge_index_limit')
                atomic(self.root/'索引.json',raw)
            finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    def collection(self,title,category='course',ident=None,expected_revision=None):
        text(title,500)
        if category not in ('course','encounter','interest','expression_research'):raise ValueError('invalid_collection_category')
        with self._edit() as d:
            if ident:
                old=next((c for c in d['collections'] if c['id']==ident),None)
                if not old or old['revision']!=expected_revision:raise ValueError('collection_revision_changed')
                if old['category']!=category:raise ValueError('collection_scope_change_denied')
                old['title']=title;old['revision']=fresh();result=dict(old)
            else:
                old=next((c for c in d['collections'] if c['title']==title and c['category']==category),None)
                if old:return dict(old)
                course_id=None
                if category=='course':
                    course=next((c for c in d['courses'] if c['name']==title),None)
                    if not course:course={'id':fresh(),'name':title};d['courses'].append(course)
                    course_id=course['id']
                result={'id':fresh(),'revision':fresh(),'title':title,'category':category,'course_id':course_id};d['collections'].append(result)
        return result
    def initialize(self):
        with self._edit() as d:d['status']='work_mode_storage_ready'
        return {'library_id':d['library_id'],'items':len(d['items']),'collections':len(d['collections'])}
    def put(self,*,collection_id,title,body,origin,source_ref,ident=None,expected_revision=None,related=None,original_file=None):
        uid(collection_id);text(title,500);text(body,MAX_BODY);text(source_ref,2000)
        if origin not in ('user','gpt_work','libao_work'):raise ValueError('invalid_work_origin')
        if not ident and expected_revision is not None:raise ValueError('knowledge_revision_requires_item')
        if related:uid(related)
        original=None;original_raw=None
        if original_file is not None:
            original_path=Path(original_file)
            if original_path.suffix.lower() not in ('.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.md','.txt','.csv','.png','.jpg','.jpeg','.webp','.epub'):raise ValueError('unsupported_original_type')
            with original_path.open('rb') as f:original_raw=f.read(64*1024*1024+1)
            if len(original_raw)>64*1024*1024:raise ValueError('original_file_limit')
            original={'name':original_path.name,'sha256':sha(original_raw),'bytes':len(original_raw),'suffix':original_path.suffix.lower()}
        with self._edit() as d:
            c=next((c for c in d['collections'] if c['id']==collection_id),None)
            if not c:raise ValueError('collection_missing')
            old=next((e for e in d['items'] if e['id']==ident),None) if ident else None
            if ident and (not old or old['revision']!=expected_revision or old.get('state')!='active'):raise ValueError('knowledge_revision_changed')
            if old and (old['category']!=c['category'] or old['course_id']!=c['course_id']):raise ValueError('knowledge_scope_change_denied')
            parent=next((e for e in d['items'] if e['id']==related),None) if related else None
            if related:
                if not parent or not self._eligible(d,parent):raise ValueError('related_item_missing_or_changed')
                if parent.get('course_id') and parent['course_id']!=c['course_id']:raise ValueError('related_course_scope_denied')
                ancestor=parent;seen=set()
                while ancestor:
                    if ancestor['id']==ident or ancestor['id'] in seen:raise ValueError('cyclic_knowledge_dependency')
                    seen.add(ancestor['id']);ancestor=next((e for e in d['items'] if e['id']==ancestor.get('related')),None)
            raw=body.encode('utf-8');fingerprint=sha(raw)
            if not old:
                duplicate=next((e for e in d['items'] if self._eligible(d,e) and e.get('collection_id')==collection_id and e.get('title')==title and e.get('body_hash')==fingerprint and e.get('source_ref')==source_ref and e.get('origin')==origin and e.get('related')==related and (original is None or (e.get('original') or {}).get('sha256')==original['sha256'])),None)
                if duplicate:return {'unchanged':True,'item':self.metadata(duplicate)}
            item={'id':old['id'] if old else fresh(),'revision':fresh(),'title':title,'type':'knowledge_note','state':'active','category':c['category'],'collection_id':collection_id,'course_id':c['course_id'],'origin':origin,'source_ref':source_ref,'body_hash':fingerprint,'body_bytes':len(raw),'previous':old['revision'] if old else None,'related':related,'related_revision':parent['revision'] if parent else None,'review_status':'unverified','reply_use_granted':c['category']=='course'}
            if original is not None:
                original['path']='原始资料/'+item['id']+'/'+original['sha256']+original.pop('suffix');original.pop('suffix',None)
                destination=unlinked(self.root/original['path'])
                if destination.exists() and sha(destination.read_bytes())!=original['sha256']:raise ValueError('original_file_changed')
                if not destination.exists():atomic(destination,original_raw)
                item['original']=original
            elif old and old.get('original'):item['original']=old['original']
            atomic(unlinked(self.root/'正文'/item['id']/(item['revision']+'.md')),raw)
            atomic(unlinked(self.root/'修订'/item['id']/(item['revision']+'.json')),packed(item).encode('utf-8'))
            if old:d['items'][d['items'].index(old)]=item
            else:d['items'].append(item)
        return {'unchanged':False,'item':self.metadata(item)}
    def withdraw(self,ident,expected_revision):
        uid(ident);uid(expected_revision)
        with self._edit() as d:
            e=next((e for e in d['items'] if e['id']==ident),None)
            if not e or e['revision']!=expected_revision or e.get('state')!='active':raise ValueError('knowledge_revision_changed')
            e['previous']=e['revision'];e['revision']=fresh();e['state']='withdrawn'
            atomic(unlinked(self.root/'修订'/ident/(e['revision']+'.json')),packed(e).encode('utf-8'));result=self.metadata(e)
        return result
