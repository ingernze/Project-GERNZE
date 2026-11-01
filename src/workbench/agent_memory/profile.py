"""A new opt-in profile, with no copying, upgrading or seeding of existing data."""
import json,sqlite3,uuid
from contextlib import closing
from pathlib import Path
from workbench.conversation_store import uid

FORMAT='gernze-agent-runtime-v1'
MARKER='agent-runtime.json'

def safe_path(value):
    path=Path(value)
    if not path.is_absolute() or path==path.parent or path.resolve()!=path:
        raise ValueError('Agent资料须使用独立、规范的绝对目录。')
    for part in (path,*path.parents):
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():
            raise ValueError('Agent资料目录不能使用链接或联接。')
    return path

def profile_id(path):
    marker=path/MARKER
    if marker.stat().st_size>4096:raise ValueError('Agent资料标记过大。')
    doc=json.loads(marker.read_text('utf-8'))
    if type(doc) is not dict or set(doc)!={'format','id'} or doc['format']!=FORMAT:
        raise ValueError('Agent资料标记无效。')
    return uid(doc['id'])

def validate_profile(value,expected_id=None):
    path=safe_path(value)
    for child in [path/MARKER,path/'workbench',path/'workbench/agent-chat-sessions.sqlite3',
                  path/'workbench/chat.json',path/'workbench/companion-memory.sqlite3']:
        safe_path(child)
    ident=profile_id(path)
    if expected_id is not None and ident!=expected_id:raise ValueError('Agent资料身份已改变。')
    return path

def prepare_profile(value):
    path=safe_path(value)
    if not (path/MARKER).exists():
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError('请选择新的空目录，不能直接升级现有桌面或研究资料。')
        path.mkdir(parents=True,exist_ok=True)
        with (path/MARKER).open('x',encoding='utf-8') as stream:
            json.dump({'format':FORMAT,'id':str(uuid.uuid4())},stream)
    validate_profile(path)
    journal=path/'workbench/agent-chat-sessions.sqlite3'
    if journal.exists():
        with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0]!=6:
                raise ValueError('Agent资料版本不兼容，未升级原库。')
    return path,profile_id(path)
