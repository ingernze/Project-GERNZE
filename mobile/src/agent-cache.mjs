import {canonical} from './memory-records.mjs';
import {createResearchCache} from './research-cache.mjs';
const FORMAT='gernze-agent-pending-cache-candidate-v1';
const check=v=>{if(!v)throw Error('Agent缓存版本或依赖无效');};
const obj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,k)=>obj(v)&&Object.keys(v).sort().join()===k.slice().sort().join();
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const hash=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('');
export async function validateAgentCache(packet,binding,previous=null){
 check(keys(packet,['format','serverId','scope_id','sequence','complete','records'])&&packet.format===FORMAT&&packet.complete===true);
 check(uuid(packet.serverId)&&uuid(packet.scope_id)&&packet.serverId===binding.serverId&&packet.scope_id===binding.scope_id);
 check(Number.isSafeInteger(packet.sequence)&&packet.sequence>0&&Array.isArray(packet.records)&&packet.records.length<=64&&new TextEncoder().encode(canonical(packet)).length<=1048576);
 if(previous)check(previous.format===FORMAT&&previous.serverId===packet.serverId&&previous.scope_id===packet.scope_id&&packet.sequence>=previous.sequence);
 const seen=new Set();
 for(const item of packet.records){
  check(keys(item,['id','revision','body','body_hash','summary_seal','receipt_hash','roots','restriction','trust','approved'])&&uuid(item.id)&&!seen.has(item.id));seen.add(item.id);
  check(item.restriction==='general'&&item.trust==='agent_pending'&&item.approved===false&&sha(item.revision)&&sha(item.body_hash)&&sha(item.summary_seal)&&sha(item.receipt_hash));
  check(typeof item.body==='string'&&item.body.trim()&&Array.from(item.body).length<=1500&&!item.body.includes('\0')&&!Array.from(item.body).some(c=>c.codePointAt(0)>=0xd800&&c.codePointAt(0)<=0xdfff)&&await hash(item.body)===item.body_hash);
  check(Array.isArray(item.roots)&&item.roots.length<=8);const roots=new Set();
  for(const r of item.roots){check(keys(r,['scope','key','revision','hash'])&&uuid(r.scope)&&uuid(r.revision)&&typeof r.key==='string'&&r.key.length>0&&r.key.length<=150&&sha(r.hash));const id=canonical([r.scope,r.key]);check(!roots.has(id));roots.add(id);}
  const {revision,...content}=item;check(await hash(canonical(content))===revision);
 }
 const fingerprint=await hash(canonical(packet));
 if(previous?.sequence===packet.sequence)check(previous.fingerprint===fingerprint);
 return {packet:structuredClone(packet),fingerprint};
}
// Existing strict IndexedDB transaction implementation, isolated database name.
// This adapter deliberately has no chat selector, L2 projector or upload method.
export function createAgentCache(options={}){return createResearchCache({...options,name:options.name||'gernze-agent-pending-candidate',validator:validateAgentCache});}
