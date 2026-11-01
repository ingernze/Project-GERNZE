// Trusted native/host adapter only. No URL, bearer token or pairing secret in JS.
export async function syncAgentCache({transport,cache,pairingId}){
 const info=await transport.getAgentInfo(pairingId);
 if(info?.capability!=='gernze-agent-pending-cache-candidate-v1'||info.readOnly!==true||info.approved!==false)throw Error('当前电脑不支持待核实Agent缓存');
 const binding={serverId:info.serverId,scope_id:info.scope_id};
 const packet=await transport.getAgentSnapshot(pairingId,{capability:info.capability,scope_id:info.scope_id});
 return cache.apply(packet,binding);
}
