import {canonical,revisionNode,validateNote} from './memory-records.mjs';
const uid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const requireValue=(v,text='电脑记忆数据无效，未接回。')=>{if(!v)throw Error(text);};
export async function validateExchange(result,binding,local=null){
  requireValue(uid(binding.scope_id)&&uid(binding.serverId)&&result.serverId===binding.serverId);
  const s=result.snapshot;requireValue(s?.format==='hebao-memory-exchange'&&s.version===1&&s.scope_id===binding.scope_id&&Array.isArray(s.records)&&s.records.length<=1024&&Array.isArray(s.revisions)&&s.revisions.length<=8192);
  requireValue(new TextEncoder().encode(JSON.stringify(result)).length<=8388608);
  const nodes=new Map(),rows=new Map();
  for(const n of s.revisions){requireValue(Object.keys(n).sort().join()==='deleted,digest,id,parents,revision'&&uid(n.id)&&uid(n.revision)&&!nodes.has(n.revision)&&Array.isArray(n.parents)&&n.parents.length<=256&&n.parents.every(uid)&&new Set(n.parents).size===n.parents.length&&typeof n.deleted==='boolean'&&/^[0-9a-f]{64}$/.test(n.digest));nodes.set(n.revision,n);}
  if(local)for(const n of local.revisions)requireValue(nodes.has(n.revision)&&canonical(nodes.get(n.revision))===canonical(n),'电脑尚未收到本机的新改动，请先重新同步，未覆盖本机记忆。');
  const child=new Set(),deletedIds=new Set();
  for(const n of nodes.values()){if(n.deleted)deletedIds.add(n.id);for(const p of n.parents){if(nodes.has(p))requireValue(nodes.get(p).id===n.id);requireValue(p!==n.revision);child.add(p);}}
  // Iterative topological check (no recursion into untrusted depth).
  const indegree=new Map(),edges=new Map();for(const n of nodes.values()){indegree.set(n.revision,0);edges.set(n.revision,[]);}
  for(const n of nodes.values())for(const p of n.parents)if(nodes.has(p)){indegree.set(n.revision,indegree.get(n.revision)+1);edges.get(p).push(n.revision);}
  const queue=[...indegree].filter(([,n])=>n===0).map(([r])=>r);for(let i=0;i<queue.length;i++)for(const c of edges.get(queue[i])){indegree.set(c,indegree.get(c)-1);if(indegree.get(c)===0)queue.push(c);}requireValue(queue.length===nodes.size);
  for(const r of s.records){
    const keys=['id','revision','parent_revision','device_id','title','body','kind','event_date','chat_enabled','important','created_at','updated_at','deleted'];
    requireValue(Object.keys(r).sort().join()===keys.sort().join()&&uid(r.id)&&uid(r.revision)&&uid(r.device_id)&&(r.parent_revision===null||uid(r.parent_revision))&&typeof r.deleted==='boolean'&&!rows.has(r.revision));
    for(const t of [r.created_at,r.updated_at])requireValue(typeof t==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$/.test(t)&&Number.isFinite(Date.parse(t)));
    if(r.deleted)requireValue(r.title===''&&r.body===''&&r.kind==='other'&&r.event_date===''&&r.chat_enabled===false&&r.important===false);
    else validateNote(Object.fromEntries(['title','body','kind','event_date','chat_enabled','important'].map(k=>[k,r[k]])));
    const n=nodes.get(r.revision);requireValue(n&&n.id===r.id&&n.deleted===r.deleted&&(await revisionNode(r)).digest===n.digest);rows.set(r.revision,r);
  }
  const tips=new Map();for(const n of nodes.values())if(!child.has(n.revision)&&!n.deleted&&!deletedIds.has(n.id)){requireValue(rows.has(n.revision));if(!tips.has(n.id))tips.set(n.id,[]);tips.get(n.id).push(n.revision);}
  const liveIds=new Set([...nodes.values()].filter(n=>!deletedIds.has(n.id)).map(n=>n.id));
  let expected=[...tips.values()].filter(v=>v.length===1).map(v=>rows.get(v[0]));
  if(liveIds.size>100||expected.filter(r=>r.chat_enabled).length>6)expected=[];
  requireValue(Array.isArray(result.active_records)&&canonical(result.active_records.slice().sort((a,b)=>a.id.localeCompare(b.id)))===canonical(expected.sort((a,b)=>a.id.localeCompare(b.id))));
  requireValue(['ready','needs_decision'].includes(result.status)&&Array.isArray(result.conflicts)&&Array.isArray(result.limits)&&typeof result.fingerprint==='string');
  return result;
}
export function createWeeklySync({journal,transport,getPair,eligible=()=>true,beforeChange=()=>{},afterChange=async()=>{},onStatus=()=>{},now=()=>Date.now()}={}){
  let busy=false,disposed=false,retryAt=0;
  async function run(force=false){
    if(busy||disposed||!eligible())return false;
    if(!force&&(await journal.setting('syncEnabled'))===false)return false;
    const last=await journal.setting('lastSync')||0;
    if(!force&&(now()-last<7*86400000||now()<retryAt))return false;
    const pair=getPair();if(!pair){if(force)onStatus('先在电脑更新里配对自己的电脑。');return false;}
    busy=true;let detached=false;
    try{
      onStatus('正在连接已配对电脑…');const info=await transport.memoryInfo(pair.pairingId);
      const binding={serverId:info.serverId,scope_id:info.scope_id};requireValue(uid(binding.serverId)&&uid(binding.scope_id));
      const oldBinding=await journal.setting('syncBinding');requireValue(!oldBinding||canonical(oldBinding)===canonical(binding),'现有记忆已绑定另一台电脑，未自动混合。');
      const {epoch,...snapshot}=await journal.exportExchange(binding.scope_id);
      const result=await validateExchange(await transport.memoryExchange(pair.pairingId,snapshot),binding,snapshot);
      if(disposed||!eligible())throw Error('已回到后台或正在对话，稍后继续接回。');
      beforeChange();detached=true;await journal.applyExchange(result,epoch,binding);await afterChange();detached=false;
      onStatus(result.status==='ready'?'记忆已互通，下次在一周后连通时再同步。':'记忆已接回，有冲突的条目已隔离，请在下方选择。');return result;
    }catch(e){retryAt=now()+15*60000;onStatus(e?.message||'没连上电脑，原记忆保留，下次连通再试。');return false;}
    finally{busy=false;if(detached)await afterChange();}
  }
  return {run,destroy(){disposed=true;},get busy(){return busy;}};
}
