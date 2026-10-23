import {canonical,revisionNode} from './memory-records.mjs';
import {validateExchange} from './memory-sync-core.mjs';
const format='gernze-layer-exchange-v1';
const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(value)))),x=>x.toString(16).padStart(2,'0')).join('');
const requireValue=(v,message='分层同步数据无效，未覆盖本机记忆。')=>{if(!v)throw Error(message);};
export async function layerIdentity(tier,key){let s=(await hash([tier,key])).slice(0,32);s=s.slice(0,12)+'4'+s.slice(13,16)+((parseInt(s[16],16)&3)|8).toString(16)+s.slice(17);return s.slice(0,8)+'-'+s.slice(8,12)+'-'+s.slice(12,16)+'-'+s.slice(16,20)+'-'+s.slice(20);}
function prune(s){
 const g=s.graph,parents=new Set(g.revisions.flatMap(n=>n.parents)),deleted=new Set(g.revisions.filter(n=>n.deleted).map(n=>n.id));
 g.records=g.records.filter(r=>r.deleted||!parents.has(r.revision)&&!deleted.has(r.id));
 s.payloads=Object.fromEntries(g.records.filter(r=>!r.deleted).map(r=>[r.revision,s.payloads[r.revision]]));return s;
}
export function graphView(g){
 const parents=new Set(g.revisions.flatMap(n=>n.parents)),deleted=new Set(g.revisions.filter(n=>n.deleted).map(n=>n.id)),tips=new Map();
 for(const n of g.revisions)if(!parents.has(n.revision)&&!n.deleted&&!deleted.has(n.id)){if(!tips.has(n.id))tips.set(n.id,[]);tips.get(n.id).push(n.revision);}
 const conflicts=[...tips].filter(([,v])=>v.length!==1).map(([id])=>id);
 const active=g.records.filter(r=>!r.deleted&&!deleted.has(r.id)&&tips.get(r.id)?.length===1);
 return {active,conflicts,deleted,liveCount:tips.size};
}
async function validate(packet,binding,core,local=null){
 requireValue(packet?.format===format&&packet.graph?.scope_id===binding.scope_id&&packet.payloads&&packet.identities);
 const view=graphView(packet.graph),limited=view.liveCount>100;
 await validateExchange({serverId:binding.serverId,snapshot:packet.graph,status:view.conflicts.length?'needs_decision':'ready',active_records:limited?[]:view.active,conflicts:[],limits:limited?[{}]:[],fingerprint:'layer-graph'},binding,local?.graph);
 for(const [id,m] of Object.entries(packet.identities))requireValue([2,3].includes(m.tier)&&typeof m.key==='string'&&m.key.length<=220&&!core.has(m.key)&&await layerIdentity(m.tier,m.key)===id);
 for(const row of packet.graph.records){
  const meta=packet.identities[row.id];requireValue(meta);if(row.deleted)continue;
  const p=packet.payloads[row.revision],e=p?.entry;
  requireValue(p?.tier===meta.tier&&e?.key===meta.key&&typeof e.body==='string'&&e.body.length>0&&Array.from(e.body).length<=1000&&await hash(p)===row.body);
  if(p.tier===3)requireValue(e.source?.summaryId&&e.source?.sessionId);
 }
 return packet;
}
function workingOnly(packet){
 const value=structuredClone(packet),ids=new Set(Object.entries(value.identities).filter(([,m])=>m.tier===3).map(([id])=>id));
 value.identities=Object.fromEntries(Object.entries(value.identities).filter(([id])=>ids.has(id)));
 value.graph.records=value.graph.records.filter(r=>ids.has(r.id));value.graph.revisions=value.graph.revisions.filter(r=>ids.has(r.id));
 value.payloads=Object.fromEntries(value.graph.records.filter(r=>!r.deleted).map(r=>[r.revision,value.payloads[r.revision]]));return value;
}
export function createLayerSync({core,read,commit,project}){
 let serial=Promise.resolve();
 const gate=fn=>{const p=serial.then(fn,fn);serial=p.catch(()=>{});return p;};
 const coreKeys=new Set(core.entries.map(e=>e.key));
 async function capture(scope){
  const before=await read(),state=structuredClone(before.state)||{format,graph:{format:'hebao-memory-exchange',version:1,scope_id:scope,records:[],revisions:[]},payloads:{},identities:{},projection:{},device:crypto.randomUUID()};
  requireValue(state.graph.scope_id===scope,'分层记忆已绑定另一台电脑，未自动混合。');
  const rows=before.rows,deleted=new Set(state.graph.revisions.filter(n=>n.deleted).map(n=>n.id));
  for(const {tier,entry:e} of rows){
   if(tier===2||coreKeys.has(e.key))continue;
   const id=await layerIdentity(tier,e.key),signature=await hash(e);
   if(state.projection[id]===signature||deleted.has(id))continue;
   const previous=state.graph.records.filter(r=>r.id===id),parent=previous.length===1?previous[0].revision:null;
   let revision=e.revision;if(state.graph.revisions.some(n=>n.revision===revision))revision=crypto.randomUUID();
   const payload={tier,entry:e},gone=Boolean(e.deleted),record={id,revision,parent_revision:parent,device_id:state.device,title:gone?'':'layer-'+tier,body:gone?'':await hash(payload),kind:'other',event_date:'',chat_enabled:false,important:false,created_at:'1970-01-01T00:00:00Z',updated_at:new Date().toISOString(),deleted:gone};
   state.graph.records.push(record);state.graph.revisions.push(await revisionNode(record));state.identities[id]={tier,key:e.key};if(!gone)state.payloads[revision]=payload;state.projection[id]=signature;
  }
  prune(state);await commit({before,state});
  return {state,rowsSignature:canonical(rows)};
 }
 return Object.freeze({
  export(scope){return gate(async()=>{const {state,rowsSignature}=await capture(scope);const {projection,device,...packet}=state;return {packet:workingOnly(packet),rowsSignature};});},
  apply(result,binding,expected){return gate(async()=>{
   const before=await read(),state=before.state;requireValue(result.serverId===binding.serverId);
   const packet=await validate(result.packet,binding,coreKeys,state);
   requireValue(canonical(before.rows)===expected,'同步期间本机记忆有新改动，请重新同步。');
   const view=graphView(packet.graph);
   const projected=project(before.data,packet,view);
   const projection={};for(const {tier,entry}of projected.rows)projection[await layerIdentity(tier,entry.key)]=await hash(entry);
   await commit({before,projected,state:{...packet,device:state?.device||crypto.randomUUID(),projection,conflicts:result.conflicts,fingerprint:result.fingerprint}});
   return result;
  });},
  async conflicts(){return (await read()).state||null;}
 });
}
