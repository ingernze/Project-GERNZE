"""Read-only project course snapshots inside the existing paired transport."""
from pathlib import Path
from libao_modules.security import strict_json
from .knowledge_library import KnowledgeReader,SNAPSHOT_FORMAT,unlinked,uid

def linked_reader(profile):
    path=unlinked(Path(profile)/'knowledge-workspace.json')
    if not path.is_file():return None
    with path.open('rb') as f:raw=f.read(64001)
    if len(raw)>64000:raise ValueError('invalid_knowledge_link')
    cfg=strict_json(raw.decode('utf-8'),max_bytes=64000)
    if type(cfg) is not dict or set(cfg)!={'format','workspace'} or cfg['format']!='gernze-knowledge-link-v1':raise ValueError('invalid_knowledge_link')
    return KnowledgeReader(cfg['workspace'])

class KnowledgeTransfer:
    def __init__(self,profile,server_id,scope):
        self.profile=Path(profile);self.server_id=uid(server_id);self.scope=uid(scope)
    def capability(self):
        # A missing/broken optional link must not break ordinary memory sync.
        try:
            reader=linked_reader(self.profile)
            if reader is None:return None
            data=reader._load();uid(data.get('library_id'))
            courses=data['courses']
            if len(courses)>100:raise ValueError('knowledge_course_limit')
            for c in courses:
                if type(c) is not dict or set(c)!={'id','name'}:raise ValueError('invalid_knowledge_course')
                uid(c['id'])
                if type(c['name']) is not str or not c['name'].strip() or len(c['name'].encode('utf-8'))>500:raise ValueError('invalid_knowledge_course')
            return {'format':SNAPSHOT_FORMAT,'libraryId':data['library_id'],'courses':courses}
        except (ValueError,OSError,KeyError,TypeError,UnicodeError):return None
    def exchange(self,body):
        if type(body) is not dict or set(body)!={'knowledge'}:raise ValueError('invalid_knowledge_exchange')
        req=body['knowledge']
        if type(req) is not dict or set(req)!={'format','course_ids'} or req['format']!=SNAPSHOT_FORMAT:raise ValueError('invalid_knowledge_exchange')
        try:
            reader=linked_reader(self.profile)
            if reader is None:raise ValueError('knowledge_not_connected')
            snapshot=reader.snapshot(req['course_ids'],self.server_id,self.scope)
            current=linked_reader(self.profile)
            if current is None or current.root!=reader.root:raise ValueError('knowledge_link_changed')
            return snapshot
        except (KeyError,TypeError,UnicodeError) as e:raise ValueError('invalid_knowledge_exchange') from e
