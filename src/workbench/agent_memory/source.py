"""Read only explicitly configured Agent entries; never discover account-wide conversations."""
from contextlib import closing
import hashlib,json,sqlite3
from pathlib import Path
from workbench.conversation_store import encoded,uid,ChatStateError
KINDS={'user_fact_report','project_progress','external_observation','model_self_report','uncategorized'}

def digest(value):return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()

def checked_source_path(root,path):
    root=Path(root);path=Path(path)
    if not path.is_absolute() or path.parent!=root or path==root or path.resolve()!=path:raise ValueError('Agent来源路径无效。')
    for part in (path,*path.parents):
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('Agent来源不能使用文件链接或联接。')
    return path

def load_selection(path):
    path=Path(path)
    if not path.is_absolute():raise ValueError('Agent范围配置须使用绝对路径。')
    checked_source_path(path.parent,path)
    if path.stat().st_size>32768:raise ValueError('Agent范围配置过大。')
    data=path.read_bytes()
    if len(data)>32768:raise ValueError('Agent范围配置过大。')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Agent范围配置有重复字段。')
            result[key]=value
        return result
    doc=json.loads(data,object_pairs_hook=unique)
    if type(doc) is not dict or set(doc)!={'format','path','sessionId','entries'} or doc['format']!='gernze-agent-source-v1':raise ValueError('Agent范围配置格式不支持。')
    return doc,hashlib.sha256(data).hexdigest()

class SelectedProgress:
    def __init__(self,config):
        self.config=Path(config);doc,self.config_hash=load_selection(self.config)
        if type(doc['path']) is not str:raise ValueError('Agent来源路径无效。')
        self.path=Path(doc['path']);self.root=self.path.parent
        checked_source_path(self.root,self.path)
        self.session_id=uid(doc['sessionId']);selected=doc['entries']
        if type(selected) is not dict or not 1<=len(selected)<=8:raise ValueError('请明确配置1至8条Agent来源。')
        if any(type(k) is not str or len(k)!=70 or not k.startswith('agent:') or any(c not in '0123456789abcdef' for c in k[6:]) or type(v) is not str or v not in KINDS for k,v in selected.items()):raise ValueError('Agent来源条目或类型无效。')
        self.selected=dict(selected)
        self.identity=digest(str(self.path))
        self.scope=digest({'path':str(self.path),'session':self.session_id,'selected':self.selected})
    def validate_selection(self):
        if load_selection(self.config)[1]!=self.config_hash:raise ChatStateError('source_scope_changed','Agent取用范围已变化，请关闭后重新启动。')
    def _entry(self, db, key):
        limits = db.execute('SELECT length(body),length(sources_json),deleted FROM agent_working WHERE key=?', (key,)).fetchone()
        if limits is None:
            return None, 'missing'
        if limits[2] not in (0, 1):
            return None, 'invalid_record'
        if limits[2]:
            return None, 'withdrawn'
        if limits[0] is None or not 1 <= limits[0] <= 1000 or limits[1] is None or not 1 <= limits[1] <= 4096:
            return None, 'oversized_record'
        row = dict(db.execute('SELECT * FROM agent_working WHERE key=?', (key,)).fetchone())
        try:
            if type(row['body']) is not str or not row['body'].strip():
                raise ValueError()
            uid(row['revision'])
            refs = json.loads(row['sources_json'])
            if type(refs) is not list or not 1 <= len(refs) <= 12:
                raise ValueError()
            sources = []
            seen = set()
            for ref in refs:
                if type(ref) is not dict or set(ref) != {'client', 'sessionId', 'turnId'}:
                    raise ValueError()
                turn = uid(ref['turnId'])
                if ref['client'] != 'codex' or ref['sessionId'] != self.session_id or turn in seen:
                    raise ValueError()
                seen.add(turn)
                length = db.execute('SELECT length(user_text),length(assistant_text) FROM agent_turns WHERE id=? AND session_id=?', (turn, self.session_id)).fetchone()
                if length is None or any(n is None or not 1 <= n <= 12000 for n in length):
                    raise ValueError()
                source = dict(db.execute('SELECT * FROM agent_turns WHERE id=? AND session_id=?', (turn, self.session_id)).fetchone())
                sources.append(source)
            sources.sort(key=lambda source: source['seq'])
            canonical_refs = [{'client': 'codex', 'sessionId': self.session_id, 'turnId': s['id']} for s in sources]
            if refs != canonical_refs or key != 'agent:' + digest(refs) or row['source_hash'] != digest(sources):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            return None, 'invalid_source'
        return {
            'key': key, 'revision': row['revision'], 'body': row['body'],
            'sourceRefs': refs, 'sourceHash': row['source_hash'],
            'provenance': 'agent_reported', 'approved': False, 'tier': 3,
            'contentKind': self.selected[key], 'validation': 'records_and_hash_only',
            'sources': [{'turnId': s['id'], 'sessionId': s['session_id'],
                         'provenance': 'agent_reported', 'reportedUser': s['user_text'],
                         'reportedAssistant': s['assistant_text']} for s in sources]
        }, 'valid'

    def snapshot(self):
        self.validate_selection()
        checked_source_path(self.root,self.path)
        entries = []
        states = {}
        status = 'available'
        try:
            # mode=ro will not create a missing database. Do not use immutable=1 on a live DB.
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=0.2)) as db:
                db.row_factory = sqlite3.Row
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                if not db.execute('SELECT 1 FROM agent_sessions WHERE id=?', (self.session_id,)).fetchone():
                    status = 'session_unavailable'
                else:
                    for key in self.selected:
                        entry, state = self._entry(db, key)
                        states[key] = state
                        if entry is not None:
                            entries.append(entry)
        except (sqlite3.Error, OSError):
            # No cached fallback: a partial snapshot must not leak validated-looking entries.
            entries = []
            states = {}
            status = 'unavailable'
        value = {'scope': self.scope, 'status': status, 'entries': entries, 'states': states}
        return {**value, 'fingerprint': digest(value)}

    def assert_current(self, snapshot):
        if self.snapshot()['fingerprint'] != snapshot.get('sourceFingerprint', snapshot['fingerprint']):
            raise ChatStateError('agent_progress_changed', 'Agent资料已变更，此请求作废。')
