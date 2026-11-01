import {registerPlugin} from '@capacitor/core';
import {createAgentCache} from './agent-cache.mjs';
import {syncAgentCache} from './agent-sync.mjs';
const plugin=registerPlugin('HebaoUpdateTransport');
export function createAgentSync({native=plugin,makeCache=createAgentCache}={}){
 const caches=new Map();let closed=false;
 const sync=async ({pairingId,eligible=()=>true})=>{
  if(closed||!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(pairingId)||!eligible())throw Error('回到前台后同步Agent缓存');
  let cache=caches.get(pairingId);
  if(!cache){cache=makeCache({name:'gernze-agent-pending-'+pairingId});caches.set(pairingId,cache);}
  const guarded={apply:async(packet,binding)=>{if(closed||!eligible())throw Error('同步已暂停，原缓存保留');return cache.apply(packet,binding);}};
  return syncAgentCache({pairingId,cache:guarded,transport:{getAgentInfo:id=>native.agentCacheInfo({pairingId:id}),getAgentSnapshot:(id,request)=>native.agentCacheSnapshot({pairingId:id,request})}});
 };
 sync.close=async()=>{closed=true;try{await Promise.all([...caches.values()].map(cache=>cache.close?.()));}finally{caches.clear();}};
 return sync;
}
