"""Authenticated L2/L3 access. Never starts or takes ownership of a chat runtime."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import sys
import threading
SOURCE=Path(__file__).resolve().parents[2]/'src'
if str(SOURCE) not in sys.path:sys.path.insert(0,str(SOURCE))
from workbench.conversation_store import ConversationStore
from workbench.memory_layers import MemoryLayers,load_core
from workbench.layer_sync import LayerSync
from workbench.phone_archive import PhoneArchive

class _SyncStore:
    """Limited adapter: attach to existing schema under SQLite's writer lock.

    The actual chat owner remains unchanged. A new chat owner is observed at
    the next transaction; the epoch barrier retires in-flight replies on edits.
    No schema creation, note import, pending-turn recovery or chat startup.
    """
    def __init__(self,path):self.path=Path(path);self.guard=threading.RLock()
    @contextmanager
    def connection(self):
        with self.guard:
            db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)
            db.row_factory=sqlite3.Row
            try:
                db.execute('PRAGMA secure_delete=ON');db.execute('BEGIN IMMEDIATE')
                if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('updated_workbench_required')
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'lc_meta','lm_approved','lm_working','lm_receipts','lm_remote_sources','lm_sync_conflicts','lm_layer_sync_meta'}<=tables:raise ValueError('updated_workbench_required')
                self.owner=ConversationStore._get(db,'owner')
                self._owner(db)
                yield db
                db.commit()
            except Exception:db.rollback();raise
            finally:db.close()
    def _owner(self,db):
        if not self.owner or ConversationStore._get(db,'owner')!=self.owner:raise ValueError('runtime_changed')
    _get=staticmethod(ConversationStore._get)
    _set=staticmethod(ConversationStore._set)
    _bump=ConversationStore._bump
    _barrier=ConversationStore._barrier

class LayerService(LayerSync):
    def __init__(self,path,server_id):
        path=Path(path)
        if not path.is_file():raise ValueError('updated_workbench_required')
        store=_SyncStore(path)
        # Attaching must not run MemoryLayers.__init__ backfill/invalidation.
        layers=object.__new__(MemoryLayers);layers.store=store;layers.core_loader=load_core
        load_core()
        chat=SimpleNamespace(store=store,layers=layers,guard=store.guard,revision=0,context=SimpleNamespace(cancel=lambda:None))
        super().__init__(chat,server_id)
    def info(self):return {**super().info(),'reviewOn':'desktop','phoneRaw':'gernze-phone-raw-v1'}

    def exchange(self,body,*,peer_device=None):return super().exchange(body,desktop_review=True,peer_device=peer_device)
    def decide(self,body):raise ValueError('review_on_desktop')
