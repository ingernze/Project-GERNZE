"""Opt-in, local bookshelf publication ingestion; no watcher, model or HTTP writer.

Preview hosts and explicitly opted-in daily hosts attach this service. The receipt pins the
source directory, namespace and course grants; text inside reports grants none.
"""
from collections import defaultdict
from pathlib import Path, PurePosixPath
import hashlib
import threading

from libao_modules.security import local_path, strict_json
from .research_catalog import packed, uid
from .research_import import FORMAT, ResearchImporter, validate


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(path):
    path=local_path(path)
    if not path.is_absolute():raise ValueError('absolute_path_required')
    for part in (path,*path.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('linked_publication_path')
    return path


def read_bytes(path,limit):
    safe_path(path)
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('publication_limit')
    return raw


def decode(raw,limit):
    return strict_json(raw.decode('utf-8'),max_bytes=limit)


class Publication:
    """Read only explicitly listed files, then recheck the exact snapshot."""
    def __init__(self,source):
        self.root=safe_path(Path(source));self.files={};self.total=0

    def read(self,name,limit):
        p=PurePosixPath(name)
        if not name or '\\' in name or ':' in name or p.is_absolute() or any(x in ('','..','.') for x in name.split('/')):
            raise ValueError('invalid_publication_relative_path')
        path=self.root.joinpath(*p.parts)
        raw=read_bytes(path,limit)
        if name not in self.files:
            self.total+=len(raw)
            if self.total>32_000_000 or len(self.files)>=2048:raise ValueError('publication_limit')
        self.files[name]=(sha(raw),limit)
        return raw

    def check_current(self):
        for name,(digest,limit) in self.files.items():
            if sha(read_bytes(self.root.joinpath(*PurePosixPath(name).parts),limit))!=digest:
                raise ValueError('publication_changed')


class ResearchShelfSync:
    def __init__(self,profile,profile_id,database):
        self.receipt=Path(profile)/'bookshelf-receipt.json';self.profile_id=profile_id
        self.importer=ResearchImporter(database);self.lock=threading.RLock()
        self.fingerprint=None;self.last_success=None

    def refresh(self):
        with self.lock:
            try:
                if not self.receipt.exists():return {'state':'disabled'}
                receipt_raw=read_bytes(self.receipt,64000);config=decode(receipt_raw,64000)
                if config.get('automaticSync') is not True:return {'state':'disabled'}
                if config.get('format')!='gernze-bookshelf-receipt-v1' or config.get('profileId')!=self.profile_id or config.get('sourceKind')!='saved_reports_not_original_webpages':
                    raise ValueError('unapproved_publication')
                namespace=uid(config['namespace']);courses=config['courseMapping']
                if type(courses) is not dict or len(courses)>100:raise ValueError('invalid_course_grants')
                grants={key:uid(value['suggested_uuid']) for key,value in courses.items()}
                publication=Publication(config['source'])
                map_raw=publication.read('宿主映射清单.json',2_000_000)
                index_raw=publication.read('分类索引.json',16_000_000)
                fingerprint=(sha(receipt_raw),sha(map_raw),sha(index_raw))
                if fingerprint==self.fingerprint:
                    return {**self.last_success,'state':'current'}
                mapping=decode(map_raw,2_000_000);index=decode(index_raw,16_000_000)
                batches,active_ids=self.prepare(publication,mapping,index,namespace,grants)
                def current():
                    if read_bytes(self.receipt,64000)!=receipt_raw:raise ValueError('host_grants_changed')
                    publication.check_current()
                result=self.importer.apply_bundle(batches,namespace=namespace,active_ids=active_ids,check_current=current)
                self.fingerprint=fingerprint
                self.last_success={'state':'updated','message':'分类资料已更新。','result':result}
                return dict(self.last_success)
            except Exception:
                # Never expose arbitrary paths/report/provider text to the UI.
                # The import transaction has rolled back; existing books stay.
                return {'state':'waiting','message':'分类资料尚未更新：资料包不完整、修订不连续或分类需要核对。保留原书架，下次打开时重试。'}

    def prepare(self,publication,mapping,index,namespace,grants):
        if mapping.get('format')!='libao-reading-shelf-host-map-v1' or index.get('format')!='libao-reading-shelf-v1' or mapping.get('namespace')!=namespace or index.get('namespace')!=namespace or mapping.get('authoritative_packet_list_only') is not True:
            raise ValueError('invalid_publication_format')
        specs=mapping['packets'];entries=index['items'];exports=index['exports']
        if type(specs) is not list or len(specs)>128 or type(entries) is not list or len(entries)>5000 or type(exports) is not list or len(exports)>10000:
            raise ValueError('publication_limit')
        if type(index.get('item_count')) is not int or index['item_count']!=len(entries) or type(index.get('import_item_count')) is not int or index['import_item_count']!=len(exports):
            raise ValueError('incomplete_publication_counts')
        logical={};exported={};fragments=defaultdict(list)
        for item in entries:
            ident=uid(item['id'])
            if ident in logical:raise ValueError('duplicate_logical_item')
            if type(item['importable']) is not bool:raise ValueError('invalid_importable')
            logical[ident]=item
        for item in exports:
            if item['id'] in exported:raise ValueError('duplicate_fragment')
            exported[item['id']]=item
        previous={}
        if self.importer.catalog.path.exists():
            with self.importer.catalog.connection() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='rc_import_items'").fetchone():
                    previous={r['external_id']:dict(r) for r in db.execute('SELECT * FROM rc_import_items WHERE namespace=?',(namespace,))}
        batches=[];active=set();packet_names=set()
        for spec in specs:
            name=spec['packet'];keys=spec['course_keys'];category=spec['category']
            if name in packet_names or not name.startswith('导入候选/') or type(keys) is not list or keys!=sorted(set(keys)) or any(k not in grants for k in keys) or category not in ('encounter','interest','course') or (category=='course')!=bool(keys) or spec['source_kind']!='companion':
                raise ValueError('unapproved_publication_scope')
            packet_names.add(name);scopes=tuple(grants[k] for k in keys)
            raw=publication.read(name,4_000_000)
            if sha(raw)!=spec['sha256']:raise ValueError('packet_hash_mismatch')
            packet=decode(raw,4_000_000);ns,validated=validate(packet)
            if ns!=namespace or len(validated)!=spec['item_count']:raise ValueError('invalid_packet_members')
            for item,_,_ in validated:
                ident=item['id'];e=exported[ident];source=logical[e['item_id']]
                if ident in active or not source['importable'] or source['lifecycle']!='active' or e['packet']!=name or e['revision']!=item['revision'] or e['previous']!=item['previous'] or e['category']!=category or source['category']!=category or sorted(e['course_keys'])!=keys or sorted(source['course_keys'])!=keys:
                    raise ValueError('fragment_index_mismatch')
                stable={k:v for k,v in item.items() if k not in ('revision','previous')}
                if sha(packed(stable).encode('utf-8'))!=e['content_hash'] or item['body']!=item['source_text']:
                    raise ValueError('fragment_content_mismatch')
                offset=source['source']['char_start_in_decoded_file']
                fragments[e['item_id']].append((e['part'],e['char_start']-offset,e['char_end_exclusive']-offset,item['body']))
                old=previous.get(ident)
                if not old or old['external_revision']!=item['revision']:
                    chain=[];target=old['external_revision'] if old else None;parent=item['previous'];seen={item['revision']}
                    while parent!=target:
                        if parent is None or parent in seen or len(chain)>=32:raise ValueError('missing_revision_history')
                        seen.add(uid(parent))
                        history=PurePosixPath(e['history'])
                        if len(history.parts)!=4 or history.parts[:2]!=('修订历史','导入项') or history.name!=item['revision']+'.json':raise ValueError('invalid_history_path')
                        uid(history.parts[2])
                        hp=decode(publication.read(str(history.parent/(parent+'.json')),4_000_000),4_000_000)
                        hns,hitems=validate(hp)
                        if hns!=namespace or len(hitems)!=1 or hitems[0][0]['id']!=ident or hitems[0][0]['revision']!=parent:raise ValueError('history_item_mismatch')
                        chain.append(hp);parent=hitems[0][0]['previous']
                    for hp in reversed(chain):batches.append({'packet':hp,'category':category,'courses':scopes,'source_kind':'companion'})
                active.add(ident)
            batches.append({'packet':packet,'category':category,'courses':scopes,'source_kind':'companion'})
        if active!=set(exported) or set(fragments)!={k for k,v in logical.items() if v['importable']}:
            raise ValueError('incomplete_publication')
        for ident,parts in fragments.items():
            position=0
            for number,(part,start,end,body) in enumerate(sorted(parts),1):
                if type(part) is not int or part!=number or start!=position or end-start!=len(body):raise ValueError('fragment_gap')
                position=end
            if ''.join(p[3] for p in sorted(parts))!=logical[ident]['body']:raise ValueError('body_reconstruction_failed')
        return batches,active
