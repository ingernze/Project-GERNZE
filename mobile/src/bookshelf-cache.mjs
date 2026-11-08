import {shelfGuard} from './bookshelf-use.mjs';
import {canonical} from './memory-records.mjs';
import {createResearchCache} from './research-cache.mjs';
export const BOOKSHELF_FORMAT='gernze-bookshelf-cache-v1';
const MAX=8388608,encoder=new TextEncoder();
const invalid=()=>{throw Error('分类书架不完整、已变化或超过接回上限，原书架保留。');};
const need=v=>{if(!v)invalid();};
const keys=(v,s)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join()===s.split(' ').sort().join();
const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(v);
const sha=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const int=(v,max)=>Number.isSafeInteger(v)&&v>=0&&v<=max;
const text=v=>typeof v==='string'&&!v.includes('\0')&&!Array.from(v).some(c=>c.codePointAt(0)>=0xd800&&c.codePointAt(0)<=0xdfff);
const bytes=v=>encoder.encode(v).length;
export async function shelfHash(v){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(canonical(v))))).map(b=>b.toString(16).padStart(2,'0')).join('');}
const bodyHash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(s)))).map(b=>b.toString(16).padStart(2,'0')).join('');
const bindKeys='format serverId scope_id snapshotId sequence contentFingerprint manifestHash';
function binding(m,b){need(m.format===BOOKSHELF_FORMAT&&uuid(m.serverId)&&uuid(m.scope_id)&&m.serverId===b.serverId&&m.scope_id===b.scope_id&&uuid(m.snapshotId)&&int(m.sequence,Number.MAX_SAFE_INTEGER)&&m.sequence>0&&sha(m.contentFingerprint)&&sha(m.manifestHash));}
function same(a,b){need(bindKeys.split(' ').every(k=>a[k]===b[k]));}
function previous(raw){
 if(!raw)return null;
 const parts=String(raw.fingerprint).split(':');need(parts.length===2&&uuid(parts[0])&&sha(parts[1]));
 return {serverId:raw.serverId,scope_id:raw.scope_id,sequence:raw.sequence,snapshotId:parts[0],manifestHash:parts[1]};
}
export async function validateShelfManifest(m,b,old=null){
 need(keys(m,bindKeys+' entries courseBodyPolicy complete bodyEntryCount bodyBytesTotal'));
 binding(m,b);need(m.complete===true&&m.courseBodyPolicy==='metadata_only'&&Array.isArray(m.entries)&&m.entries.length<=5000&&bytes(canonical(m))<=2097152);
 let count=0,total=0,last='';
 for(const e of m.entries){
  need(keys(e,'id revision category title review trust bodyHash bodyBytes sources courses'));
  need(uuid(e.id)&&e.id>last&&uuid(e.revision)&&['encounter','interest','course'].includes(e.category)&&text(e.title)&&Array.from(e.title).length<=1000&&['reported_reviewed','reported_verified','partial','unverified'].includes(e.review)&&['external_untrusted','agent_inferred','user_reported_unreviewed'].includes(e.trust)&&sha(e.bodyHash)&&int(e.bodyBytes,32000)&&e.bodyBytes>0);
  need(Array.isArray(e.courses)&&e.courses.length<=16&&new Set(e.courses).size===e.courses.length&&e.courses.every(uuid)&&(e.category==='course'?e.courses.length>0:e.courses.length===0));
  need(Array.isArray(e.sources)&&e.sources.length>0&&e.sources.length<=256);let sourceLast='';
  for(const s of e.sources){need(Array.isArray(s)&&s.length===2&&uuid(s[0])&&s[0]>sourceLast&&sha(s[1]));sourceLast=s[0];}
  last=e.id;if(e.category!=='course'){count++;total+=e.bodyBytes;}
 }
 need(total<=MAX&&m.bodyEntryCount===count&&m.bodyBytesTotal===total);
 need(await shelfHash({entries:m.entries,courseBodyPolicy:m.courseBodyPolicy})===m.contentFingerprint);
 const {manifestHash,...unsigned}=m;need(await shelfHash(unsigned)===manifestHash);
 if(old){need(old.serverId===m.serverId&&old.scope_id===m.scope_id&&m.sequence>=old.sequence);if(m.sequence===old.sequence)need(old.manifestHash===m.manifestHash&&old.snapshotId===m.snapshotId);}
 return m.entries.filter(e=>e.category!=='course');
}
export async function validateShelfPage(p,m,offset){
 need(keys(p,bindKeys+' offset entries next complete')&&bytes(canonical(p))<=1048576);same(p,m);
 need(p.offset===offset&&Array.isArray(p.entries)&&p.entries.length>0&&p.entries.length<=32);
 const ordinary=m.entries.filter(e=>e.category!=='course');need(offset+p.entries.length<=ordinary.length);
 for(let i=0;i<p.entries.length;i++){
  const r=p.entries[i],meta=ordinary[offset+i];need(keys(r,'id revision bodyHash bodyBytes body'));
  need(['id','revision','bodyHash','bodyBytes'].every(k=>r[k]===meta[k])&&text(r.body)&&bytes(r.body)===meta.bodyBytes&&await bodyHash(r.body)===meta.bodyHash);
 }
 const end=offset+p.entries.length;need(p.complete===(end===ordinary.length)&&p.next===(p.complete?null:end));return end;
}
async function validateTransfer(input,b,rawOld){
 input=structuredClone(input);
 need(keys(input,'manifest pages confirmation attemptId')&&Array.isArray(input.pages)&&input.pages.length<=256&&uuid(input.attemptId));
 const {manifest:m,pages,confirmation:c}=input;await validateShelfManifest(m,b,previous(rawOld));
 let offset=0,total=0;const hashes=[],bodies=new Map();
 for(const p of pages){offset=await validateShelfPage(p,m,offset);hashes.push(await shelfHash(p));for(const r of p.entries){need(!bodies.has(r.id));bodies.set(r.id,r.body);total+=r.bodyBytes;need(total<=MAX);}}
 need(offset===m.bodyEntryCount&&total===m.bodyBytesTotal&&(!offset||pages.at(-1).complete));
 need(keys(c,bindKeys+' phase count bytes pages transferDigest attemptId directoryChecked'));same(c,m);
 need(c.phase==='finalize'&&c.directoryChecked===true&&c.count===offset&&c.bytes===total&&c.pages===pages.length&&c.attemptId===input.attemptId&&c.transferDigest===await shelfHash(hashes));
 return {packet:{...m,records:m.entries.map(e=>({...e,restriction:e.category==='course'?'study':'general',body_hash:e.bodyHash,body:e.category==='course'?null:bodies.get(e.id)}))},fingerprint:m.snapshotId+':'+m.manifestHash};
}
export function createBookshelfCache(options={}){
 let gate=()=>{},applying=false;const lockName=options.name||BOOKSHELF_FORMAT;
 const cache=createResearchCache({...options,name:options.name||BOOKSHELF_FORMAT,validator:validateTransfer,beforeCommit:()=>gate()});
 return {...cache,lockName,state:async()=>{const s=await cache.state();return s?{...previous(s),receivedAt:s.receivedAt}:null;},
  async apply(packet,binding,eligible=()=>true){
   if(applying)throw Error('分类书架正在接回。');applying=true;gate=()=>need(eligible());
   try{return await shelfGuard(lockName,async()=>{gate();return cache.apply(packet,binding);});}finally{gate=()=>{};applying=false;}
  }};
}

export function mountBookshelf({container,cache,sync}){
 const section=document.createElement('section');section.className='panel';section.style.cssText='background:#f6f1e6;color:#334f60;padding:16px;border-radius:14px;margin:6px';
 const title=document.createElement('h3');title.textContent='分类资料';
 const hint=document.createElement('p');hint.className='hint';hint.textContent='普通资料按话题只读取材 · 课程仅目录';
 const now=document.createElement('button');now.type='button';now.textContent='从电脑接回分类资料';
 const status=document.createElement('p');status.role='status';const progressHost=document.createElement('div');
 const progress=window.GernzeTaskProgress?.mount(progressHost,{label:'分类书架接回'});
 const tabs=document.createElement('div'),list=document.createElement('div');section.append(title,hint,now,status,progressHost,tabs,list);container.append(section);
 let alive=true,version=0,category='encounter',limit=30;
 const reading=window.GernzeReadingTools?.createSession({host:section});
 const labels={encounter:'见闻',interest:'兴趣专题',course:'课程目录'};
 async function refresh(){reading?.suspend();const n=++version;try{
  const rows=await cache.list(),state=await cache.state();if(!alive||n!==version)return;
  status.textContent=state?'最后接回：'+new Date(state.receivedAt).toLocaleString('zh-CN')+' · '+rows.length+'份资料':'尚未接回完整分类书架。';
  tabs.replaceChildren();for(const [key,label] of Object.entries(labels)){const b=document.createElement('button');b.type='button';const categoryRows=rows.filter(r=>r.category===key);b.textContent=label+' '+(window.GernzeShelfCollections?window.GernzeShelfCollections.partition(categoryRows).rootCount+'个专题':categoryRows.length);b.setAttribute('aria-pressed',String(key===category));b.onclick=()=>{category=key;limit=30;void refresh();};tabs.append(b);}
  list.replaceChildren();const renderCard=r=>{
   const card=document.createElement('article'),h=document.createElement('h4'),note=document.createElement('p');h.textContent=r.title;note.textContent='外部资料 · '+(r.review==='unverified'?'未核实':'保留交付方核验说明，不等于已审记忆');card.append(h,note);
   if(r.category==='course'){const p=document.createElement('p');p.textContent='课程正文仍在电脑，手机未下载。';card.append(p);}
   else {
    const b=document.createElement('button');b.type='button';b.textContent='查看内容';let reader=null,pending=false,ticket=0,unwatch=null;
    const current=()=>alive&&n===version&&window.GernzeReadingTools?.visible(card);
    const close=()=>{ticket++;pending=false;unwatch?.();unwatch=null;reader?.destroy();reader=null;b.textContent='查看内容';b.removeAttribute('aria-busy');};
    b.onclick=async()=>{
     if(reader||pending){close();b.focus({preventScroll:true});return;}
     if(!reading){status.textContent='阅读组件未加载，请重新打开书架。';return;}
     if(!current())return;const own=++ticket;pending=true;unwatch=reading.watch(card,close);b.textContent='取消读取';b.setAttribute('aria-busy','true');
     try{const value=await cache.read(r.id,r.revision);if(own!==ticket||!current())return;
      if(value?.id!==r.id||value?.revision!==r.revision||typeof value.body!=='string')throw Error('changed');
      unwatch?.();unwatch=null;
      reader=reading.mount(card,{id:r.id,revision:r.revision,body:value.body,metadata:{title:r.title,trust:value.trust,review:value.review,sources:value.sources},current,onClose:()=>{close();if(current())b.focus({preventScroll:true});}});b.textContent='收起内容';
     }catch{if(own===ticket&&current()){b.textContent='查看内容';status.textContent='资料暂未读取或已变化；可重试，或重新接回分类资料。';}}
     finally{if(own===ticket){pending=false;unwatch?.();unwatch=null;b.removeAttribute('aria-busy');}}
    };card.append(b);
   }
   return card;
  };
  if(window.GernzeShelfCollections){window.GernzeShelfCollections.render(list,rows.filter(r=>r.category===category),{createCard:renderCard,current:()=>alive&&n===version});return;}
  for(const r of rows.filter(r=>r.category===category).slice(0,limit))list.append(renderCard(r));
  if(rows.filter(r=>r.category===category).length>limit){const more=document.createElement('button');more.type='button';more.textContent='再看30份';more.onclick=()=>{limit+=30;void refresh();};list.append(more);}
 }catch{if(alive)status.textContent='分类书架暂未读取，请重新打开。';}}
 now.onclick=async()=>{now.disabled=true;try{await sync({onProgress:p=>{if(!alive)return;status.textContent=p.detail;progress?.update(p);}});if(alive)await refresh();}catch(e){if(alive){status.textContent=e.message||'分类资料未接回，原书架保留。';progress?.update({state:'error',detail:status.textContent});}}finally{if(alive)now.disabled=false;}};
 const changed=()=>{reading?.clear();void refresh();};
 const invalidate=()=>{reading?.clear();version++;};
 const page=e=>{if(e.detail?.page!=='dialogue')invalidate();};
 const background=e=>{if(e.detail===false)reading?.suspend();};
 const visibility=()=>{if(document.hidden)reading?.suspend();};
 const pairChanged=()=>{invalidate();list.replaceChildren();status.textContent='配对已变化，请关闭并重新打开分类书架；原缓存不自动混合。';};
 window.addEventListener('hebao:bookshelf-changed',changed);window.addEventListener('hebao:pairing-changed',pairChanged);window.addEventListener('hebao:page-change',page);window.addEventListener('hebao:app-active',background);window.addEventListener('pagehide',invalidate);document.addEventListener('visibilitychange',visibility);
 return {ready:refresh(),destroy(){alive=false;version++;window.removeEventListener('hebao:bookshelf-changed',changed);window.removeEventListener('hebao:pairing-changed',pairChanged);window.removeEventListener('hebao:page-change',page);window.removeEventListener('hebao:app-active',background);window.removeEventListener('pagehide',invalidate);document.removeEventListener('visibilitychange',visibility);reading?.destroy();progress?.destroy?.();section.remove();}};
}
