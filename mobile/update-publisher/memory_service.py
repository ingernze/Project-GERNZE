"""Narrow paired publisher endpoint. Reuse the accepted merge algorithm, not LWW."""
import threading,sqlite3,json
from contextlib import closing
from pathlib import Path
import sys

SOURCE=Path(__file__).resolve().parents[2]/'src'
if str(SOURCE) not in sys.path:sys.path.insert(0,str(SOURCE))
from workbench.owner_memory import owner_memory
from workbench import memory_merge as mm


class MemoryService:
    def __init__(self,path,server_id):
        # Do not migrate a database still owned by the older EXE writer, which
        # cannot maintain the causal graph. Updated workbench must open it first.
        path=Path(path)
        if not path.exists():raise ValueError('updated_workbench_required')
        with closing(sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)) as db:
            row=db.execute("SELECT value FROM meta WHERE key='owner_workbench_protocol'").fetchone()
            if not row or row[0]!='1':raise ValueError('updated_workbench_required')
        self.memory=owner_memory(path);self.scope=self.memory.scope;self.server_id=mm.identifier(server_id);self.lock=threading.RLock()

    def info(self):return {'scope_id':self.scope,'serverId':self.server_id,'format':mm.FORMAT,'version':1}

    def portable(self):
        path=self.memory.path.with_name('chat-sessions.sqlite3')
        if not path.exists():return
        with closing(sqlite3.connect(path)) as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lc_note_policy'").fetchone()
            if not exists:return
            active={r['id'] for r in self.memory.list()['records']}
            for rid,scope,state,refs in db.execute('SELECT note_id,scope,event_state,source_ids FROM lc_note_policy'):
                if rid in active and (scope!='global' or state!='unspecified' or json.loads(refs)):raise ValueError('nonportable_note_policy')

    def exchange(self,body):
        if type(body) is not dict or set(body)!={'snapshot'}:raise ValueError('invalid_exchange')
        remote=mm.validate_snapshot(body['snapshot'],expected_scope=self.scope)
        with self.lock,self.memory.external_gate():
            self.portable()
            plan=self.memory.preview(remote,expected_scope=self.scope)
            if plan['status']=='ready':
                result=self.memory.apply(remote,plan,expected_scope=self.scope)
                if not result['applied']:raise ValueError('snapshot_changed')
            else:self.memory.stage_conflicts(remote,plan,expected_scope=self.scope)
            return self.result()

    def result(self):
        snapshot=self.memory.export_exchange(expected_scope=self.scope);report=mm.inspect(snapshot,expected_scope=self.scope)
        return {'serverId':self.server_id,'snapshot':snapshot,'status':report['status'],'active_records':[] if report['limits'] else report['active_records'],'conflicts':report['conflicts'],'limits':report['limits'],'fingerprint':mm.digest(snapshot)}

    def decide(self,body):
        if type(body) is not dict or set(body)!={'id','fingerprint','note','delete'} or type(body['delete']) is not bool:raise ValueError('invalid_decision')
        with self.lock,self.memory.external_gate():
            self.portable()
            self.memory.decide(body['id'],expected_scope=self.scope,expected_fingerprint=body['fingerprint'],note=body['note'],delete=body['delete'],confirmed=True)
            return self.result()
