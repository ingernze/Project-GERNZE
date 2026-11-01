"""Reserve the source writer slot through desktop commit; never modify source rows."""
from contextlib import contextmanager
import contextvars,json,sqlite3,threading
from .atomic import roots
from .items import SourceGate
from .summaries import SummaryStore,SummaryChat
from .source import checked_source_path,digest
from workbench.conversation_store import ChatStateError

class LeaseGate(SourceGate):
    def __init__(self,store,reader):
        super().__init__(store,reader)
        self.timeout=.4
        self._active=contextvars.ContextVar('source_reservation',default=None)
    @contextmanager
    def reservation(self):
        reader=self.reader
        if reader is None:
            yield None
            return
        path=checked_source_path(reader.root,reader.path)
        reader.validate_selection()
        if path==self.store.path:raise ValueError('Source and desktop must be distinct')
        identity=(str(path),reader.scope,reader.session_id,tuple(sorted(reader.selected.items())))
        active=self._active.get()
        if active is not None:
            if active['identity']!=identity or active['thread']!=threading.get_ident():
                raise ChatStateError('source_scope_changed','Reserved source scope changed')
            yield active['snapshot']
            return
        db=None;token=None
        try:
            # mode=rw refuses to create a missing source. Writable access is
            # required solely to reserve SQLite's existing single-writer slot.
            db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=self.timeout,isolation_level=None)
            db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION}
            db.set_authorizer(lambda op,*args:sqlite3.SQLITE_OK if op in allowed else sqlite3.SQLITE_DENY)
            if not db.execute('SELECT 1 FROM agent_sessions WHERE id=?',(reader.session_id,)).fetchone():
                raise ChatStateError('source_unavailable','Configured source session is unavailable')
            entries=[];states={}
            for key in reader.selected:
                entry,state=reader._entry(db,key);states[key]=state
                if entry is not None:entries.append(entry)
            value={'scope':reader.scope,'status':'available','entries':entries,'states':states}
            snapshot={**value,'fingerprint':digest(value)}
            token=self._active.set({'identity':identity,'thread':threading.get_ident(),'snapshot':snapshot})
        except (sqlite3.Error,OSError) as exc:
            if db is not None:
                db.close();db=None
            raise ChatStateError('source_busy_or_unavailable','Source reservation could not be acquired') from exc
        except BaseException:
            if db is not None:db.close()
            raise
        try:
            yield snapshot
        finally:
            if token is not None:self._active.reset(token)
            if db is not None:
                try:db.rollback()
                finally:db.close()
    def sync(self):
        with self.store.connection() as db:
            return json.loads(self.store._get(db,'ag_current') or '{}')

class CoordinatedStore(SummaryStore):
    @contextmanager
    def connection(self):
        gate=getattr(self,'gate',None)
        if not isinstance(gate,LeaseGate):
            with super().connection() as db:yield db
            return
        # Always acquire source before desktop. In particular, never acquire a
        # second source connection from inside the desktop commit transaction.
        with gate.reservation() as snapshot:
            with super().connection() as db:
                gate.apply(db,snapshot)
                yield db
    def _complete(self,db,request_id,*args):
        ticket=self.tracker.ticket.get()
        if ticket is None or ticket['request_id']!=request_id:
            raise ChatStateError('missing_exposure','Actual input receipt required')
        current=json.loads(self._get(db,'ag_current') or '{}')
        if any(current.get(r['scope']+':'+r['key'])!=r for r in roots(ticket['dependencies'])):
            raise ChatStateError('source_changed','Source changed before atomic answer commit')
        return super()._complete(db,request_id,*args)

class CoordinatedChat(SummaryChat):
    gate_class=LeaseGate
