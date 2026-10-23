import {integer,uuid,requireValue,failure} from './event-contract.mjs';
// Host injects its existing HebaoUpdateTransport plugin AFTER the documented native fragments.
// This adapter cannot access addresses, tokens, certificates or arbitrary request paths.
export function createEventTransport({plugin,randomUUID=()=>crypto.randomUUID()}){
  async function request(method,args,signal){
    if(signal?.aborted)throw failure('cancelled');const requestId=uuid(randomUUID());let cancelled=false;
    const cancel=()=>{cancelled=true;try{Promise.resolve(plugin.cancelEventRequest({requestId})).catch(()=>{});}catch{}};
    signal?.addEventListener('abort',cancel,{once:true});
    try{const answer=await plugin[method]({...args,requestId});if(cancelled||signal?.aborted)throw failure('cancelled');return answer;}
    finally{signal?.removeEventListener('abort',cancel);}
  }
  return Object.freeze({
    fetch({pairingId,cursor,limit,stream_id,signal}){uuid(pairingId);integer(cursor);integer(limit,1,6);if(stream_id!==null)uuid(stream_id);return request('fetchEvents',{pairingId,cursor,limit,streamId:stream_id},signal);},
    ack({pairingId,event_ids,signal}){uuid(pairingId);requireValue(Array.isArray(event_ids)&&event_ids.length>0&&event_ids.length<=6);event_ids.forEach(uuid);return request('ackEvents',{pairingId,eventIds:event_ids},signal);}
  });
}
