"""Agent-derived turns never enter ordinary user-fact approval, even while sources are valid."""
import json
from .coordination import CoordinatedStore,CoordinatedChat
from workbench.memory_layers import MemoryLayers
from workbench.conversation_store import uid

class AdmissionStore(CoordinatedStore):
    def legacy_turn_allowed(self,db,ident):
        try:
            return self.eligible(db,ident) and not self.descriptors(db,ident) and json.loads(self._get(db,'ag_derived:'+ident))==[]
        except (ValueError,KeyError,TypeError):return False
    def create_layers(self,store):
        assert store is self
        return AdmissionLayers(self,**({'core_loader':self.core_loader} if self.core_loader is not None else {}))
    def source_messages(self,ids,*,session_id=None):
        if type(ids) is not list or not 1<=len(ids)<=8 or any(type(i) is not str for i in ids) or len(set(ids))!=len(ids):raise ValueError('Invalid source IDs')
        for ident in ids:uid(ident)
        with self.connection() as db:
            rows=[]
            for ident in ids:
                r=db.execute('SELECT m.*,t.status FROM lc_messages m JOIN lc_turns t ON t.id=m.turn_id WHERE m.id=?',(ident,)).fetchone()
                if not r or not r['allowed'] or r['role']!='user' or r['origin']!='user' or r['status']!='complete' or session_id and r['session_id']!=session_id or not self.legacy_turn_allowed(db,r['turn_id']):raise ValueError('Agent-derived or invalid source is not admitted to legacy memory')
                rows.append(dict(r))
            return rows

class AdmissionLayers(MemoryLayers):
    def source_valid(self,db,working):
        try:
            ids=working['source_turn_ids'];ids=json.loads(ids) if isinstance(ids,str) else ids
            return bool(ids) and all(self.store.legacy_turn_allowed(db,ident) for ident in ids) and super().source_valid(db,working)
        except (ValueError,KeyError,TypeError):return False
    def _working(self,db):
        return [w for w in super()._working(db) if self.source_valid(db,w)]
    def invalidate_sources(self,db):
        # Quarantine by eligibility, retaining legacy row bodies and evidence.
        # The parent backfill still discards invalid deferred projections.
        pass
    def decide(self,decisions,*,review_guard=None,review_commit=None):
        def guard(db):
            if type(decisions) is not list:raise ValueError('Invalid decisions')
            for decision in decisions:
                row=db.execute('SELECT * FROM lm_working WHERE key=?',(decision.get('key'),)).fetchone()
                # Always recheck, including processed/replayed receipts.
                if row is None or not self.source_valid(db,dict(row)):raise ValueError('Legacy review source not admitted')
            if review_guard is not None:review_guard(db)
        return super().decide(decisions,review_guard=guard,review_commit=review_commit)

class AdmissionChat(CoordinatedChat):pass
