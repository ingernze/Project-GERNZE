"""Paired L2/L3 exchange over the existing causal merge engine. Never transports L1/L4."""
import hashlib,json,uuid
from . import memory_merge as mm
from .conversation_store import encoded,stamp

FORMAT='gernze-layer-exchange-v1'
def identity(tier,key):
    raw=hashlib.sha256(mm.canonical([tier,key])).hexdigest()[:32]
    return str(uuid.UUID(raw[:12]+'4'+raw[13:16]+format((int(raw[16],16)&3)|8,'x')+raw[17:]))
def empty(scope):
    return {'format':FORMAT,'graph':{'format':mm.FORMAT,'version':1,'scope_id':scope,'records':[],'revisions':[]},'payloads':{},'identities':{},'projection':{}}
def prune(packet):
    g=packet['graph'];parents={p for n in g['revisions'] for p in n['parents']}
    deleted={n['id'] for n in g['revisions'] if n['deleted']}
    g['records']=[r for r in g['records'] if r['deleted'] or r['revision'] not in parents and r['id'] not in deleted]
    packet['payloads']={r['revision']:packet['payloads'][r['revision']] for r in g['records'] if not r['deleted']}
    return packet
def checked(packet,scope,core):
    if type(packet) is not dict or packet.get('format')!=FORMAT or len(mm.canonical(packet))>8388608:raise ValueError('invalid_layer_exchange')
    g=mm.validate_snapshot(packet.get('graph'),expected_scope=scope)
    payloads=packet.get('payloads');ids=packet.get('identities')
    if type(payloads) is not dict or type(ids) is not dict or len(ids)>1024:raise ValueError('invalid_layer_exchange')
    for rid,meta in ids.items():
        if type(meta) is not dict or set(meta)!={'tier','key'} or type(meta['tier']) is not int or meta['tier'] not in (2,3) or type(meta['key']) is not str or not 1<=len(meta['key'])<=220 or meta['key'] in core or identity(meta['tier'],meta['key'])!=rid:raise ValueError('layer_identity_invalid')
    for r in g['records']:
        if r['id'] not in ids:raise ValueError('layer_identity_missing')
        if r['deleted']:continue
        p=payloads.get(r['revision'])
        if type(p) is not dict or set(p)!={'tier','entry'} or p['tier']!=ids[r['id']]['tier']:raise ValueError('layer_payload_invalid')
        e=p['entry']
        if type(e) is not dict or e.get('key')!=ids[r['id']]['key'] or type(e.get('body')) is not str or not 1<=len(e['body'])<=1000 or mm.digest(p)!=r['body']:raise ValueError('layer_payload_invalid')
        mm.identifier(e.get('revision'))
        if p['tier']==3 and (type(e.get('source')) is not dict or not e['source'].get('summaryId') or not e['source'].get('sessionId')):raise ValueError('layer_source_missing')
    return {'format':FORMAT,'graph':g,'payloads':{r['revision']:payloads[r['revision']] for r in g['records'] if not r['deleted']},'identities':ids}

class LayerSync:
    def __init__(self,chat,server_id):
        self.chat=chat;self.layers=chat.layers;self.store=chat.store;self.server_id=server_id
        self.scope=str(uuid.uuid5(uuid.UUID(server_id),'gernze-layer-memory-v1'))
        self.device=str(uuid.uuid5(uuid.UUID(server_id),'desktop'))
    def info(self):return {'serverId':self.server_id,'scope_id':self.scope,'format':FORMAT,'tiers':[2,3]}
    def _state(self,db):
        row=db.execute("SELECT value FROM lm_layer_sync_meta WHERE key='state'").fetchone()
        return json.loads(row[0]) if row else empty(self.scope)
    def _entries(self,db):
        working=self.layers._working(db);bykey={r['key']:r for r in working};out=[]
        def source(w):
            remote=db.execute('SELECT payload FROM lm_remote_sources WHERE key=? AND revision=?',(w.get('key',''),w.get('revision',''))).fetchone()
            return json.loads(remote[0]) if remote else self._source(w)
        for a in db.execute('SELECT * FROM lm_approved'):
            w=bykey.get(a['key'],{})
            remote=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',('source2:'+a['key']+':'+a['revision'],)).fetchone()
            e={'key':a['key'],'revision':a['revision'],'body':a['body'],'deleted':bool(a['deleted']),'updatedAt':a['updated_at'],'sourceRevision':a['source_revision'],'source':json.loads(remote[0]) if remote else source(w)}
            out.append((2,e))
        for w in working:
            e={'key':w['key'],'revision':w['revision'],'body':w['body'],'deleted':bool(w['reviewed_action']) or not self.layers.source_valid(db,w),'updatedAt':w['updated_at'],'createdAt':w['created_at'],'approvedBaseRevision':w['approved_base_revision'],'source':source(w)}
            out.append((3,e))
        return out
    @staticmethod
    def _source(w):
        return {'sessionId':w.get('session_id',''),'summaryId':w.get('source_summary_id',''),'epoch':w.get('source_epoch',0),'turnIds':w.get('source_turn_ids',[]),'messageIds':w.get('source_ids',[]),'at':w.get('source_at'),'anchors':w.get('source_anchors',[])}
    def _capture(self,db,state):
        projection=state.setdefault('projection',{});g=state['graph'];core={e['key'] for e in self.layers.core_loader()['entries']}
        deleted={n['id'] for n in g['revisions'] if n['deleted']}
        for tier,e in self._entries(db):
            if e['key'] in core:continue
            rid=identity(tier,e['key']);signature=mm.digest(e)
            if projection.get(rid)==signature or rid in deleted:continue
            old=[r for r in g['records'] if r['id']==rid]
            parent=old[0]['revision'] if len(old)==1 else None
            revision=e['revision']
            if any(n['revision']==revision for n in g['revisions']):revision=str(uuid.uuid4())
            payload={'tier':tier,'entry':e};is_deleted=e['deleted'];time=stamp()
            record={'id':rid,'revision':revision,'parent_revision':parent,'device_id':self.device,'title':'' if is_deleted else 'layer-'+str(tier),'body':'' if is_deleted else mm.digest(payload),'kind':'other','event_date':'','chat_enabled':False,'important':False,'created_at':'1970-01-01T00:00:00Z','updated_at':time,'deleted':is_deleted}
            g['records'].append(record);g['revisions'].append({'id':rid,'revision':revision,'parents':[parent] if parent else [],'deleted':is_deleted,'digest':mm.digest(record)})
            state['identities'][rid]={'tier':tier,'key':e['key']}
            if not is_deleted:state['payloads'][revision]=payload
            projection[rid]=signature
        return prune(state)
    def _materialize(self,db,state):
        report=mm.inspect(state['graph'],expected_scope=self.scope)
        conflict_ids={c['id'] for c in report['conflicts']}
        db.execute('DELETE FROM lm_sync_conflicts')
        for rid in conflict_ids:
            meta=state['identities'][rid];db.execute('INSERT INTO lm_sync_conflicts VALUES (?,?)',(meta['tier'],meta['key']))
        core={e['key'] for e in self.layers.core_loader()['entries']}
        for r in state['graph']['records']:
            meta=state['identities'][r['id']];key=meta['key'];tier=meta['tier']
            if key in core:raise ValueError('core_is_read_only')
            if r['deleted']:
                if tier==2:db.execute("UPDATE lm_approved SET body='',deleted=1,revision=?,updated_at=? WHERE key=?",(r['revision'],stamp(),key))
                else:
                    w=db.execute('SELECT revision FROM lm_working WHERE key=?',(key,)).fetchone()
                    if w:db.execute('INSERT OR IGNORE INTO lm_receipts VALUES (?,?,?,?,?)',(key,w[0],'sync-retired','source_invalidated',stamp()))
                continue
            if r['id'] in conflict_ids:continue
            e=state['payloads'][r['revision']]['entry'];s=e.get('source',{});updated=e.get('updatedAt') or stamp()
            if tier==2:
                db.execute('INSERT OR REPLACE INTO lm_layer_sync_meta VALUES (?,?)',('source2:'+key+':'+e['revision'],encoded(s)))
                db.execute('INSERT OR REPLACE INTO lm_approved VALUES (?,?,?,?,?,0,?)',(key,e['revision'],e['body'],e.get('sourceRevision') or e['revision'],updated,'owner-paired-review'))
            else:
                current=db.execute('SELECT revision FROM lm_working WHERE key=?',(key,)).fetchone()
                if current and current[0]==e['revision']:continue
                # Provenance is an explicit paired-host attestation, never fabricated local raw chat.
                db.execute('INSERT OR REPLACE INTO lm_remote_sources VALUES (?,?,?)',(key,e['revision'],encoded(s)))
                db.execute('INSERT OR REPLACE INTO lm_working VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(key,e['revision'],e['body'],s['summaryId'],s['sessionId'],s.get('epoch',0),encoded(s.get('turnIds',[])),encoded(s.get('messageIds',[])),s.get('at'),e.get('createdAt') or updated,updated,e.get('approvedBaseRevision')))
        state['projection']={identity(t,e['key']):mm.digest(e) for t,e in self._entries(db)}
        return report
    def exchange(self,body,*,desktop_review=False,peer_device=None):
        if type(body) is not dict or set(body)!={'snapshot'}:raise ValueError('invalid_layer_exchange')
        core={e['key'] for e in self.layers.core_loader()['entries']}
        remote=checked(body['snapshot'],self.scope,core)
        if (desktop_review or peer_device is not None) and any(m['tier']==2 for m in remote['identities'].values()):raise ValueError('approved_memory_desktop_only')
        with self.chat.guard,self.store.connection() as db:
            self.store._owner(db);local=self._capture(db,self._state(db))
            for rid,meta in remote['identities'].items():
                if rid in local['identities'] and local['identities'][rid]!=meta:raise ValueError('layer_identity_collision')
            # Entry revisions are immutable as well as graph revisions. Retain
            # their bindings after payload pruning, so old approvals cannot be
            # attached to different text/source by wrapping a new graph node.
            def bind_entry(payload):
                e=payload['entry'];name='entry:'+str(payload['tier'])+':'+e['key']+':'+e['revision']
                digest=mm.digest(payload)
                old=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',(name,)).fetchone()
                if old and old[0]!=digest:raise ValueError('layer_entry_revision_changed')
                db.execute('INSERT OR IGNORE INTO lm_layer_sync_meta VALUES (?,?)',(name,digest))
                return old is not None
            for payload in local['payloads'].values():bind_entry(payload)
            if peer_device is not None:
                from .conversation_store import uid
                uid(peer_device)
            for record in remote['graph']['records']:
                if record['deleted']:continue
                payload=remote['payloads'][record['revision']]
                known_entry=bind_entry(payload)
                if peer_device is not None and payload['tier']==3 and not known_entry:
                    e=payload['entry'];source=e['source'];start=source.get('start');end=source.get('end')
                    if (type(source.get('sessionId')) is not str or not 1<=len(source['sessionId'])<=100
                        or type(start) is not int or type(end) is not int or start<0 or start%2 or end%2
                        or not start<end<=min(start+16,200000)):
                        raise ValueError('phone_summary_source_range_required')
                    db.execute('INSERT OR REPLACE INTO lm_layer_sync_meta VALUES (?,?)',('phone3:'+e['key']+':'+e['revision'],encoded({'device':peer_device,'sessionId':source['sessionId'],'start':start,'end':end})))
            before=mm.digest(local['graph'])
            local['graph']=mm.merge(local['graph'],remote['graph'],expected_scope=self.scope)
            local['payloads'].update(remote['payloads']);local['identities'].update(remote['identities']);prune(local)
            report=self._materialize(db,local)
            if mm.digest(local['graph'])!=before:self.store._barrier(db,'layer_sync');self.chat.revision+=1;self.chat.context.cancel()
            db.execute("INSERT OR REPLACE INTO lm_layer_sync_meta VALUES ('state',?)",(encoded(local),))
            packet={k:v for k,v in local.items() if k!='projection'}
            return {'serverId':self.server_id,'packet':packet,'conflicts':report['conflicts'],'fingerprint':mm.digest(packet),'status':'needs_decision' if report['conflicts'] else 'ready'}
    def decide(self,body):
        if type(body) is not dict or set(body)!={'id','revision','fingerprint','delete'} or type(body['delete']) is not bool:raise ValueError('invalid_layer_decision')
        with self.chat.guard,self.store.connection() as db:
            self.store._owner(db);state=self._capture(db,self._state(db));packet={k:v for k,v in state.items() if k!='projection'}
            if mm.digest(packet)!=body['fingerprint']:raise ValueError('decision_needs_refresh')
            row=next((r for r in state['graph']['records'] if r['id']==body['id'] and r['revision']==body['revision']),None)
            if not row and not body['delete']:raise ValueError('decision_needs_refresh')
            note=None if body['delete'] else {k:row[k] for k in mm.NOTE_FIELDS}
            old=state['graph']
            result=mm.commit_decision(old,body['id'],expected_scope=self.scope,expected_fingerprint=mm.digest(old),device_id=self.device,revision=str(uuid.uuid4()),timestamp=stamp(),note=note,delete=body['delete'])
            state['graph']=result
            if not body['delete']:
                new=next(r for r in result['records'] if r['id']==body['id'] and not r['deleted'])
                state['payloads'][new['revision']]=state['payloads'][row['revision']]
            prune(state);report=self._materialize(db,state)
            self.store._barrier(db,'layer_conflict_decided');self.chat.revision+=1;self.chat.context.cancel()
            db.execute("INSERT OR REPLACE INTO lm_layer_sync_meta VALUES ('state',?)",(encoded(state),))
            packet={k:v for k,v in state.items() if k!='projection'}
            return {'serverId':self.server_id,'packet':packet,'conflicts':report['conflicts'],'fingerprint':mm.digest(packet),'status':'needs_decision' if report['conflicts'] else 'ready'}

    @classmethod
    def local(cls,chat):
        with chat.store.read_connection() as db:
            row=db.execute("SELECT value FROM lm_layer_sync_meta WHERE key='state'").fetchone()
        if not row:raise ValueError('还没有分层同步记录。')
        scope=json.loads(row[0])['graph']['scope_id'];uuid.UUID(scope)
        value=object.__new__(cls);value.chat=chat;value.layers=chat.layers;value.store=chat.store
        value.server_id=None;value.scope=scope;value.device=str(uuid.uuid5(uuid.UUID(scope),'desktop-review'));return value
    def conflicts(self):
        with self.chat.guard,self.store.connection() as db:
            self.store._owner(db);state=self._capture(db,self._state(db))
            db.execute("INSERT OR REPLACE INTO lm_layer_sync_meta VALUES ('state',?)",(encoded(state),))
            packet={k:v for k,v in state.items() if k!='projection'};report=mm.inspect(state['graph'],expected_scope=self.scope)
            return {'fingerprint':mm.digest(packet),'conflicts':[{'id':c['id'],'tier':state['identities'][c['id']]['tier'],'key':state['identities'][c['id']]['key'],'choices':[{'revision':r['revision'],'body':state['payloads'][r['revision']]['entry']['body']} for r in state['graph']['records'] if r['id']==c['id'] and not r['deleted']]} for c in report['conflicts']]}
