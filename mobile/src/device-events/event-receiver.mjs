import {MAX_ITEMS,MAX_STREAMS,MAX_LIMIT,clone,state,event,batch,uuid,integer,canonical,keys,requireValue,failure} from './event-contract.mjs';
// No timers, sockets or URLs. transport is already authenticated by the native host.
export function createEventReceiver({transport,storage,notify,pairingId=null,foreground=false,clock=Date.now,idHash=defaultHash}){
  if(pairingId!==null)uuid(pairingId);
  let peer=pairingId,active=!!foreground,dead=false,generation=0,busy=false,aborter;
  const valid=(g,p)=>!dead&&active&&generation===g&&peer===p;
  function check(g,p){requireValue(valid(g,p),'cancelled');}
  function cancel(){generation++;aborter?.abort();}
  function setForeground(value){active=!!value;if(!active)cancel();}
  function setPairing(value){if(value!==null)uuid(value);if(value!==peer){cancel();peer=value;}}
  async function locked(fn){requireValue(!dead,'cancelled');requireValue(!busy,'busy');busy=true;try{return await fn();}finally{busy=false;}}
  async function load(){try{return clone(state(await storage.load()));}catch(e){throw e.code==='storage_conflict'?e:failure('storage_failed');}}
  async function save(s,g,p){check(g,p);const previous=s.revision;s.revision++;try{state(s);await storage.commit(previous,clone(s));}catch(e){s.revision=previous;throw e.code==='storage_conflict'?e:failure('storage_failed');}check(g,p);}
  function stream(s,p){let value=s.streams.find(x=>x.peer_id===p);if(!value){requireValue(s.streams.length<MAX_STREAMS,'inbox_full');value={peer_id:p,stream_id:null,cursor:0,gap_lost_through:0,expired_count:0,items:[]};s.streams.push(value);}return value;}
  async function safeStatus(id,g,p){try{const result=await notify.lookup(id);check(g,p);requireValue(['present','absent'].includes(result),'notification_failed');return result;}catch(e){check(g,p);return 'unavailable';}}
  async function flushNotifications(s,t,g,p){
    for(const item of t.items){
      check(g,p);if(item.event.expires_at<=clock()||item.read_at!==null||item.notification==='submitted'||item.notification==='unknown')continue;
      if(item.notification==='attempting'){
        const found=await safeStatus(item.notification_id,g,p);check(g,p);
        // No evidence after a crash is NOT evidence that the user never saw it.
        item.notification=found==='present'?'submitted':'unknown';await save(s,g,p);continue;
      }
      let permission;try{permission=await notify.permission();}catch{check(g,p);item.notification='failed';await save(s,g,p);continue;}check(g,p);
      if(permission!==true){if(item.notification!=='denied'){item.notification='denied';await save(s,g,p);}continue;}
      if(item.notification_id===null){
        const rawIds=await notify.occupiedIds();check(g,p);requireValue(Array.isArray(rawIds),'notification_failed');rawIds.forEach(id=>integer(id,1,2147483647));const occupied=new Set(rawIds);
        for(const st of s.streams)for(const row of st.items)if(row.notification_id!==null)occupied.add(row.notification_id);
        // Reserve a dedicated high range; also scan all host/pending/delivered IDs.
        const start=(idHash(p+':'+item.event.event_id)>>>0)%1000000000;let id=null;
        for(let n=0;n<=occupied.size;n++){const candidate=1000000000+(start+n)%1000000000;if(!occupied.has(candidate)){id=candidate;break;}}
        requireValue(id!==null,'notification_failed');item.notification_id=id;
      }
      item.notification='attempting';await save(s,g,p);check(g,p);
      let outcome;try{outcome=await notify.submit({id:item.notification_id,peer_id:p,event:clone(item.event)},()=>valid(g,p));}
      catch{outcome={status:'unknown'};}
      check(g,p);
      requireValue(outcome&&['submitted','denied','failed','cancelled','unknown'].includes(outcome.status),'notification_failed');
      item.notification=outcome.status==='cancelled'?'pending':outcome.status;
      await save(s,g,p);
    }
  }
  async function flushAcks(s,t,g,p,signal){
    const pending=t.items.filter(x=>!x.acked).slice(0,MAX_LIMIT);if(!pending.length)return 0;
    check(g,p);const ids=pending.map(x=>x.event.event_id);
    const reply=await transport.ack({pairingId:p,event_ids:ids,signal});check(g,p);
    keys(reply,['schema','status','event_ids']);requireValue(reply&&reply.schema===1&&reply.status==='acknowledged'&&canonical(reply.event_ids)===canonical(ids),'invalid_input');
    for(const x of pending)x.acked=true;await save(s,g,p);return pending.length;
  }
  async function checkOnce(){return locked(async()=>{
    const p=peer,g=generation;requireValue(p!==null,'unpaired');check(g,p);aborter=new AbortController();
    const signal=aborter.signal,s=await load();check(g,p);const t=stream(s,p);
    const now=integer(clock(),1),before=t.items.length;t.items=t.items.filter(x=>x.event.expires_at>now);const pruned=before-t.items.length;t.expired_count+=pruned;
    // Persist maintenance before any network/notification operation. Failed writes never ACK.
    await save(s,g,p);
    await flushNotifications(s,t,g,p);const retriedAcks=await flushAcks(s,t,g,p,signal);
    check(g,p);const response=await transport.fetch({pairingId:p,cursor:t.cursor,limit:MAX_LIMIT,stream_id:t.stream_id,signal});check(g,p);
    batch(response,p,t.cursor,t.stream_id);
    const oldCursor=t.cursor;let received=0,expired=0;
    for(const row of response.events){
      event(row.event);const existing=t.items.find(x=>x.event.event_id===row.event.event_id);
      if(existing){requireValue(existing.cursor===row.cursor&&canonical(existing.event)===canonical(row.event),'event_conflict');continue;}
      // In-flight expiry is saved as a receipt too, so the remote queue can be ACKed explicitly.
      requireValue(t.items.length<MAX_ITEMS,'inbox_full');
      t.items.push({cursor:row.cursor,event:clone(row.event),received_at:integer(clock(),1),notification_id:null,notification:'pending',acked:false,read_at:null});received++;if(row.event.expires_at<=clock())expired++;
    }
    t.cursor=response.next_cursor;t.stream_id=response.stream_id;if(response.gap)t.gap_lost_through=Math.max(t.gap_lost_through,response.gap.lost_through);
    // Cursor and inbox rows are ONE durable snapshot, before notification submission or ACK.
    await save(s,g,p);await flushNotifications(s,t,g,p);const acked=await flushAcks(s,t,g,p,signal);
    return {status:'received',received,saved:received,acknowledged:acked+retriedAcks,cursor:t.cursor,previous_cursor:oldCursor,has_more:response.has_more,gap:response.gap,expired_received:expired,expired_pruned:pruned,expired_total:t.expired_count,known_gap_lost_through:t.gap_lost_through,unread:t.items.filter(x=>x.read_at===null).length};
  });}
  async function messages(){return locked(async()=>{const p=peer,g=generation;requireValue(p!==null,'unpaired');const s=await load();check(g,p);return clone(s.streams.find(x=>x.peer_id===p)?.items??[]);});}
  async function markRead(eventId){uuid(eventId);return locked(async()=>{const p=peer,g=generation;check(g,p);const s=await load(),t=stream(s,p),item=t.items.find(x=>x.event.event_id===eventId);requireValue(!!item);item.read_at=integer(clock(),1);await save(s,g,p);return {status:'read'};});}
  async function notificationTarget(id,expected=null){integer(id,1,2147483647);const p=peer,g=generation;check(g,p);const s=await load();check(g,p);const row=s.streams.find(x=>x.peer_id===p)?.items.find(x=>x.notification_id===id);return row&&row.event.expires_at>clock()&&(expected===null||(expected.peer_id===p&&expected.event_id===row.event.event_id))?clone(row.event.target):null;}
  async function retryUnknownNotification(eventId){uuid(eventId);return locked(async()=>{const p=peer,g=generation;check(g,p);const s=await load(),t=stream(s,p),item=t.items.find(x=>x.event.event_id===eventId);requireValue(item?.notification==='unknown');item.notification='pending';await save(s,g,p);return {status:'retry_enabled'};});}
  async function destroy(){dead=true;cancel();} // Caller destroys its own notification adapter/listeners separately.
  return Object.freeze({checkOnce,cancel,destroy,setForeground,setPairing,messages,markRead,notificationTarget,retryUnknownNotification});
}
function defaultHash(s){let h=2166136261;for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619);return h>>>0;}
