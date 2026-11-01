"""Attach to the existing desktop journal without creating or replacing its owner."""
from contextlib import closing,contextmanager
import contextvars,hashlib,json,sqlite3,threading,uuid
from .profile import validate_profile,profile_id
from .source import SelectedProgress
from .atomic import digest
from .coordination import LeaseGate
from .summaries import SummaryStore
from workbench.conversation_store import ChatStateError,encoded,uid

FORMAT='gernze-agent-pending-cache-candidate-v1'

def binding(ident,reader):
    return encoded({'profile':ident,'source_scope':reader.scope if reader else None,
                    'selection_hash':reader.config_hash if reader else None})

class ExportStore(SummaryStore):
    """No ConversationStore/MemoryLayers constructor, recovery, schema creation or backfill.

    Writes only freshness metadata and export sequence in the existing journal;
    never claims a chat owner, changes a pending turn, or writes source content.
    """
    def __init__(self,profile,source_config=None):
        self.profile=validate_profile(profile);self.profile_id=profile_id(self.profile)
        self.path=self.profile/'workbench/agent-chat-sessions.sqlite3'
        reader=SelectedProgress(source_config) if source_config is not None else None
        self.binding=binding(self.profile_id,reader)
        self.guard=threading.RLock()
        self._checking=contextvars.ContextVar('export_graph_check',default=frozenset())
        self._memo=contextvars.ContextVar('export_graph_memo',default=None)
        # mode=ro refuses a missing journal. It cannot initialize a profile.
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            self._schema(db)
            self.owner=self._get(db,'owner');uid(self.owner)
            self._owner(db)
        self.gate=LeaseGate(self,reader)
    @staticmethod
    def _schema(db):
        if db.execute('PRAGMA user_version').fetchone()[0]!=6:raise ValueError('updated_agent_workbench_required')
    def _owner(self,db):
        super()._owner(db)
        if self._get(db,'ag_runtime_binding')!=self.binding:
            raise ChatStateError('source_scope_changed','更新服务与桌面的Agent取用范围不一致。')
    @contextmanager
    def connection(self):
        validate_profile(self.profile,self.profile_id)
        with self.gate.reservation() as snapshot,self.guard:
            db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=1,isolation_level=None)
            db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
                self._schema(db);self._owner(db)
                self.gate.apply(db,snapshot)
                yield db
                db.commit()
            except BaseException:
                db.rollback();raise
            finally:db.close()

class PendingSnapshot:
    def __init__(self,store,server_id,pairing_id):
        self.store=store;self.server=uid(server_id)
        self.scope=str(uuid.uuid5(uuid.UUID(self.server),'agent-pending:'+uid(pairing_id)))
    def export(self):
        with self.store.connection() as db:
            self.store._owner(db)
            rows=list(db.execute('SELECT * FROM ag_summaries ORDER BY session_id,version LIMIT 65'))
            if len(rows)>64:raise ValueError('agent_cache_limit')
            records=[]
            for row in rows:
                if not self.store.summary_valid(db,row):continue
                meta=json.loads(row['exposure'])
                record={'id':row['id'],'body':row['text'],'body_hash':hashlib.sha256(row['text'].encode('utf-8')).hexdigest(),
                        'summary_seal':row['seal'],'receipt_hash':digest(meta),'roots':meta['roots'],
                        'restriction':'general','trust':'agent_pending','approved':False}
                record['revision']=digest(record);records.append(record)
            key='ag_transfer_seq:'+self.scope;sequence=int(self.store._get(db,key) or '0')+1
            if not 1<=sequence<=9007199254740991:raise ValueError('agent_sequence_limit')
            packet={'format':FORMAT,'serverId':self.server,'scope_id':self.scope,'sequence':sequence,'complete':True,'records':records}
            if len(encoded(packet).encode('utf-8'))>1048576:raise ValueError('agent_cache_limit')
            self.store._set(db,key,sequence)
            return packet
