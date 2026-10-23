"""One owner namespace in the existing notes DB; authorization stays in paired TLS."""
import uuid,threading,os
from contextlib import contextmanager
from .companion_memory import CompanionMemory
from .persistent_memory import PersistentMemory

_registry_lock=threading.Lock()
_registry={}

@contextmanager
def file_gate(path):
    # Same Windows locking primitive as the existing publisher's instance lock;
    # this gate is short lived and reentrant, covering note reads through reply commit.
    key=str(path.resolve())
    with _registry_lock:state=_registry.setdefault(key,{'lock':threading.RLock(),'depth':0})
    with state['lock']:
        if state['depth']:
            state['depth']+=1
            try:yield
            finally:state['depth']-=1
            return
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():raise ValueError('linked_memory_lock')
        stream=open(path,'a+b')
        try:
            if os.name=='nt':
                import msvcrt
                stream.seek(0,2)
                if not stream.tell():stream.write(b'0');stream.flush()
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
            state['depth']=1
            try:yield
            finally:
                state['depth']=0
                if os.name=='nt':stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        finally:stream.close()

class OwnerMemory(PersistentMemory):
    def external_gate(self):return file_gate(self.path.with_suffix('.sync-lock'))
    @contextmanager
    def connection(self):
        with self.external_gate(),super().connection() as db:yield db


def owner_memory(path,*,workbench=False):
    # Namespace and device remain stable for both workbench and publisher. They
    # are not credentials and a remote caller cannot choose either value.
    with file_gate(path.with_suffix('.sync-lock')),CompanionMemory(path).connection() as db:
        row=db.execute("SELECT value FROM meta WHERE key='owner_scope'").fetchone()
        scope=row[0] if row else str(uuid.uuid4())
        if not row:db.execute('INSERT INTO meta VALUES (?,?)',('owner_scope',scope))
        if workbench:db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('owner_workbench_protocol','1'))
        device=db.execute("SELECT value FROM meta WHERE key='device_id'").fetchone()[0]
    return OwnerMemory(path,expected_scope=scope,device_id=device)
