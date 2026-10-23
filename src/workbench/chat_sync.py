"""Narrow host coordinator around the frozen CompanionChat prepared/epoch seam."""
import json

if __package__:
    from . import memory_merge as mm
else:
    import memory_merge as mm


class ChatMemorySync:
    def __init__(self,chat,*,fault_hook=None):
        self.chat=chat;self.memory=chat.memories;self.fault_hook=fault_hook
        if not hasattr(self.memory,'export_exchange'):raise ValueError('请先注入持久化记忆适配器。')

    def _portable(self):
        # Exchange v1 has no per-note conversation scope/source policy. Do not silently
        # broaden typed casual/technical/derived rules by transporting only 13 fields.
        active={r['id'] for r in self.chat._all_notes()}
        for record_id,p in self.chat.store.note_policies().items():
            if record_id in active and (p['scope']!='global' or p['event_state']!='unspecified' or p['source_ids']):
                mm.fail('nonportable_note_policy')

    def export_exchange(self,*,expected_scope):
        with self.chat.guard:
            self._portable()
            if self.chat.store.pending_changes():mm.fail('prepared_change_requires_review')
            return self.memory.export_exchange(expected_scope=expected_scope)

    def _finish(self,operation,metadata):
        notes=self.chat._all_notes();self._portable()
        before=dict(metadata['before_notes'])
        # Body-free policies are committed before retiring prepared. A crash at any
        # point leaves the existing global gate closed, never a half-safe chat state.
        with self.chat.store.connection() as db:
            self.chat.store._owner(db)
            for note in notes:
                old=db.execute('SELECT revision FROM lc_note_policy WHERE note_id=?',(note['id'],)).fetchone()
                if note['id'] in before and before[note['id']]!=note['revision'] or old and old['revision']!=note['revision']:
                    db.execute('INSERT OR REPLACE INTO lc_note_policy VALUES (?,?,?,?,?,?)',
                        (note['id'],note['revision'],'global','unspecified','[]',1))
        self.chat.store.finish_change(operation,None,None,self.chat._fingerprint(notes),metadata)

    def _change(self,action):
        chat=self.chat
        with chat.guard:
            self._portable()
            if chat.store.pending_changes():mm.fail('prepared_change_requires_review')
            notes=chat._sync_notes()
            metadata={'operation':'memory_sync','scope':'global','event_state':'unspecified','source_ids':[],
                      'correction':False,'before_notes':[[n['id'],n['revision']] for n in notes]}
            operation=chat.store.begin_change(None,metadata)
            chat.revision+=1;chat.context.cancel();chat.history.clear()
            # On ANY exception leave prepared, because commit/close errors can have an
            # unknown outcome. recover() is an explicit review, never guessed success.
            result=action()
            if self.fault_hook:self.fault_hook('after_notes_commit')
            self._finish(operation,metadata)
            return result

    def preview(self,remote,*,expected_scope):
        """Pure query only. For accepting a conflict use review_exchange, not this."""
        with self.chat.guard:
            self._portable()
            if self.chat.store.pending_changes():mm.fail('prepared_change_requires_review')
            return self.memory.preview(remote,expected_scope=expected_scope)

    def review_exchange(self,remote,*,expected_scope):
        """Authenticated host explicitly accepts conflicts into durable quarantine."""
        with self.chat.guard:
            plan=self.preview(remote,expected_scope=expected_scope)
            if plan['status']=='ready':return {'plan':plan,'staged':False}
            result=self._change(lambda:self.memory.stage_conflicts(remote,plan,expected_scope=expected_scope))
            return {'plan':plan,**result}

    def apply(self,remote,plan,*,expected_scope):
        # Preserve apply_plan semantics: a conflict cannot be called applied.
        with self.chat.guard:
            self.memory._scope(expected_scope);remote=self.memory._remote(remote,expected_scope)
            current=self.memory.export_exchange(expected_scope=expected_scope)
            checked=mm.apply_plan(current,remote,plan,expected_scope=expected_scope)
            if not checked['applied']:return checked
            return self._change(lambda:self.memory.apply(remote,plan,expected_scope=expected_scope))

    def decide(self,record_id,*,expected_scope,expected_fingerprint,note=None,delete=False,confirmed=False):
        with self.chat.guard:
            self.memory._scope(expected_scope)
            if confirmed is not True:mm.fail('explicit_confirmation_required')
            if self.memory.status(expected_scope=expected_scope)['fingerprint']!=expected_fingerprint:mm.fail('decision_needs_refresh')
            return self._change(lambda:self.memory.decide(record_id,expected_scope=expected_scope,
                expected_fingerprint=expected_fingerprint,note=note,delete=delete,confirmed=confirmed))

    def recover(self,operation_id,*,confirmed=False):
        if confirmed is not True:mm.fail('explicit_confirmation_required')
        with self.chat.guard:
            with self.chat.store.connection() as db:
                row=db.execute("SELECT metadata FROM lc_changes WHERE id=? AND status='prepared'",(mm.identifier(operation_id),)).fetchone()
                if not row:mm.fail('prepared_operation_not_found')
                metadata=json.loads(row[0])
                if metadata.get('operation')!='memory_sync':mm.fail('not_a_sync_operation')
            self.memory.status(expected_scope=self.memory.scope)  # Validate persisted state.
            self._finish(operation_id,metadata)
            return {'reviewed':True,'state':self.memory.status(expected_scope=self.memory.scope)}
