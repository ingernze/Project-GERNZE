import {createResearchCache,mountResearchCache} from '../src/research-cache.mjs';
import {createLayeredMemory} from '../src/memory-layer-store.mjs';
import {canonical} from '../src/memory-records.mjs';
export async function run(packets){
 const checks=[];const check=(condition,label)=>{if(!condition)throw Error(label);checks.push(label);};
 const sample=packets.find(p=>p.records.some(r=>r.restriction==='study')&&p.records.some(r=>r.restriction==='general'));if(!sample)throw Error('missing Python fixture');
 const packet=n=>({...structuredClone(sample),sequence:n}),binding={serverId:sample.serverId,scope_id:sample.scope_id};
 const namespace='synthetic-research-'+crypto.randomUUID(),name=namespace+'-research-cache';let cache=createResearchCache({name});
 await cache.apply(packet(10),binding);check((await cache.list()).length===2,'Python snapshot commits metadata and general body');
 const general=sample.records.find(r=>r.restriction==='general'),course=sample.records.find(r=>r.restriction==='study');
 check((await cache.read(general.id,general.revision)).body===general.body,'general summary loads only on explicit read');
 let bodyReads=0;const oldGet=IDBObjectStore.prototype.get,oldGetAll=IDBObjectStore.prototype.getAll;
 IDBObjectStore.prototype.get=function(...args){if(this.name==='bodies')bodyReads++;return oldGet.apply(this,args);};
 IDBObjectStore.prototype.getAll=function(...args){if(this.name==='bodies')bodyReads++;return oldGetAll.apply(this,args);};
 try{await cache.list();check(bodyReads===0,'directory lists metadata without bodies');let rejected=false;try{await cache.read(course.id,course.revision);}catch{rejected=true;}check(rejected&&bodyReads===0,'course denied before body get');}
 finally{IDBObjectStore.prototype.get=oldGet;IDBObjectStore.prototype.getAll=oldGetAll;}
 await cache.close();cache=createResearchCache({name});check((await cache.list()).length===2&&(await cache.state()).sequence===10,'reopen retains metadata bodies and sequence');
 const ordinary=createLayeredMemory({core:{schemaVersion:1,entries:[]},namespace});
 const context=await ordinary.chat.context('今天学课程吗');check(context.approved.length===0&&context.working.length===0&&!JSON.stringify(context).includes(general.body),'research cache cannot enter old chat or user-fact layers');await ordinary.close();
 const clear={...packet(11),records:[]};await cache.apply(clear,binding);check((await cache.list()).length===0,'complete empty snapshot withdraws previous body and metadata');
 let rejected=false;try{await cache.apply(packet(10),binding);}catch{rejected=true;}check(rejected&&(await cache.list()).length===0,'older packet cannot resurrect withdrawn research');
 await cache.apply(packet(12),binding);const b=createResearchCache({name});
 const digest=crypto.subtle.digest.bind(crypto.subtle);let entered,release,once=true;const at=new Promise(r=>entered=r),hold=new Promise(r=>release=r);
 crypto.subtle.digest=async(...args)=>{if(once){once=false;entered();await hold;}return digest(...args);};
 try{const stale=cache.apply(packet(13),binding).then(()=>false,()=>true);await at;await b.apply(packet(14),binding);release();check(await stale,'cross-tab final compare rejects an overwritten baseline');check((await cache.state()).sequence===14,'cross-tab newer snapshot survives');}
 finally{crypto.subtle.digest=digest;await b.close();}
 const before=await cache.list(),extra=structuredClone(general);extra.id=crypto.randomUUID();extra.revision=crypto.randomUUID();const failing={...packet(15),records:[general,extra]};
 const oldPut=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(value,...args){if(this.name==='metadata'&&value.id===extra.id)throw new DOMException('synthetic quota','QuotaExceededError');return oldPut.call(this,value,...args);};
 rejected=false;try{await cache.apply(failing,binding);}catch{rejected=true;}finally{IDBObjectStore.prototype.put=oldPut;}
 check(rejected&&canonical(await cache.list())===canonical(before)&&(await cache.state()).sequence===14,'failed multi-store replacement rolls back clears bodies and sequence');
 const host=document.getElementById('host');let delayed=false,resolver;
 const facade={...cache,read:(...args)=>delayed?new Promise(r=>resolver=r):cache.read(...args)};
 const ui=mountResearchCache({container:host,cache:facade});await ui.ready;
 check(host.textContent.includes('手机未下载')&&host.querySelectorAll('button').length===2,'mobile directory provides course notice and one general read button');
 host.querySelectorAll('button')[1].click();await new Promise(r=>setTimeout(r,40));check(host.textContent.includes(general.body),'explicit summary read renders in mobile panel');
 const xss=packet(16),entry=xss.records.find(r=>r.restriction==='general');entry.revision=crypto.randomUUID();entry.body='<img src=x onerror="window.BAD=true"> 合成正文';entry.body_hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(entry.body))),b=>b.toString(16).padStart(2,'0')).join('');
 await cache.apply(xss,binding);await ui.refresh();host.querySelectorAll('button')[1].click();await new Promise(r=>setTimeout(r,40));check(host.textContent.includes('<img')&&!host.querySelector('img')&&!window.BAD,'external summary displayed as inert text');
 delayed=true;host.querySelectorAll('button')[1].click();await new Promise(r=>setTimeout(r,0));
 await cache.apply({...packet(17),records:[]},binding);await ui.refresh();resolver({...general,body:'LATE_REVOKED_BODY'});await new Promise(r=>setTimeout(r,0));check(!host.textContent.includes('LATE_REVOKED_BODY')&&!host.textContent.includes('<img'),'withdrawal clears display and suppresses a late read');
 ui.destroy();check(!host.children.length,'closing panel removes view and listeners');
 await cache.apply(packet(18),binding);const finalUI=mountResearchCache({container:host,cache});await finalUI.ready;
 host.querySelectorAll('button')[1].click();await new Promise(r=>setTimeout(r,40));await cache.close();
 // Exercise the actual sync button controller and its native-call adapter.
 const syncHost=document.createElement('div');document.body.append(syncHost);const settings=new Map([['layerSyncEnabled',false]]),requests=[];
 const syncCache=createResearchCache({name:'synthetic-sync-'+crypto.randomUUID()});let layerApplies=0;
 window.__native={cap:true,missing:false,corrupt:false,hold:null,
  async layerInfo(){if(this.hold)await this.hold;return {...binding,reviewOn:'desktop',phoneRaw:'gernze-phone-raw-v1',researchCache:this.cap?'gernze-research-cache-v1':null};},
  async layerExchange(value){requests.push(value.request);const data=packet(20+requests.length);if(this.corrupt)data.records.find(r=>r.restriction==='general').body+='BAD';return {serverId:binding.serverId,packet:{synthetic:true},conflicts:[],...(this.cap&&!this.missing?{research:data}:{})};}
 };
 await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/sync-bundle.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
 localStorage.setItem('hebao.updates.v1',JSON.stringify({pair:{pairingId:crypto.randomUUID()}}));
 const sync=await window.Stage7Sync.mountMemorySync({container:syncHost,layers:{research:syncCache,sync:{export:async()=>({packet:{synthetic:true},rowsSignature:'SYNTHETIC'}),apply:async()=>layerApplies++,conflicts:async()=>null}},journal:{list:async()=>[],setting:async function(key,value){if(arguments.length>1)settings.set(key,value);return settings.get(key);}}});
 async function click(){syncHost.querySelector('[data-now]').click();for(let i=0;i<300&&syncHost.querySelector('[data-now]').disabled;i++)await new Promise(r=>setTimeout(r,10));check(!syncHost.querySelector('[data-now]').disabled,'sync operation settles');}
 await click();check(requests[0].capabilities[0]==='gernze-research-cache-v1'&&(await syncCache.list()).length===2&&settings.get('layerLastSync')>0,'sync button negotiates and saves the research response');
 const saved=(await syncCache.state()).sequence;settings.set('layerLastSync',0);window.__native.missing=true;const applies=layerApplies;await click();
 check(layerApplies===applies&&settings.get('layerLastSync')===0&&syncHost.textContent.includes('未返回完整研究资料'),'missing negotiated payload never reports success or changes layers');
 window.__native.missing=false;window.__native.cap=false;await click();check(!requests.at(-1).capabilities&&(await syncCache.state()).sequence===saved,'older desktop uses legacy sync without research downgrade');
 window.__native.cap=true;window.__native.corrupt=true;settings.set('layerLastSync',0);await click();check((await syncCache.state()).sequence===saved&&settings.get('layerLastSync')===0,'invalid research response retains independent cache and is not marked synchronized');
 let releaseInfo;window.__native.corrupt=false;window.__native.hold=new Promise(r=>releaseInfo=r);syncHost.querySelector('[data-now]').click();await new Promise(r=>setTimeout(r,0));const sent=requests.length;sync.destroy();releaseInfo();await new Promise(r=>setTimeout(r,30));check(requests.length===sent&&!syncHost.children.length,'leaving during handshake stops before posting or applying');
 syncHost.remove();await syncCache.close();
 await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/desktop-review.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
 const desktop=document.createElement('div');document.body.append(desktop);const cleanups=[];let researchMode=true;
 const desktopScope={listen:(el,event,fn)=>{el.addEventListener(event,fn);cleanups.push(()=>el.removeEventListener(event,fn));},own:fn=>cleanups.push(fn)};
 const desktopCall=async command=>{
  if(command==='chat.layers.get')return {core:{entries:[]},approved:[],pending:[],settings:{summaryEnabled:true,summaryDays:7,reviewDays:7}};
  if(command==='chat.memory.list')return {records:[]};if(command==='chat.books.status')return {storedMessages:0,undatedEntries:0};if(command==='chat.layers.conflicts')return {conflicts:[]};
  if(command==='chat.layers.auto_review.status')return {running:false,enabled:true,progress:{state:'complete',message:'合成审查结果'},recent:[{status:'completed',at:'2026-10-26T00:00:00Z',kind:researchMode?'research':'legacy',decisions:researchMode?[{action:'supported',reason:'合成来源核对'},{action:'defer',reason:'合成保留'},{action:'reject',reason:'合成排除'}]:[{action:'approve',reason:'合成普通审批'}]}]};throw Error('unexpected '+command);
 };
 const desktopUI=window.HecateSceneMemory.mount(desktop,{scope:desktopScope,call:desktopCall,settingsOnly:true});await desktopUI.refresh();
 check(desktop.textContent.includes('研究摘要：与输入相符1条，保留待核对1条，排除1条；未写入用户事实。')&&!desktop.textContent.includes('supported ·'),'desktop renders research verdict separately from user fact approval');
 researchMode=false;await desktopUI.refresh();check(desktop.textContent.includes('写入1条，保留待审0条，排除0条'),'legacy desktop review counts retain original meaning');
 for(const cleanup of cleanups.reverse())cleanup();desktop.remove();
 return checks;
}
