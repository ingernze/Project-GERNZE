import {createChatJournal} from '../src/chat-journal.mjs';
import {createResearchUse,hashText} from '../src/research-use.mjs';
import {createChatTransport,estimateMessageBytes} from '../src/chat-core.mjs';
import {createMemorySource} from '../src/memory-source.mjs';
import {mountResearchCache} from '../src/research-cache.mjs';
import {pickSummary} from '../src/summary-policy.mjs';
import {uploadPhoneRaw} from '../src/raw-sync.mjs';
import {canonical} from '../src/memory-records.mjs';

// Isolated browser DBs and synthetic provider replies only. Never opens user stores.
export async function run(packets){
 const checks=[],names=[],journals=[],host=document.getElementById('host');
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label);};
 const denied=async fn=>{try{await fn();return false;}catch{return true;}};
 const sample=packets.find(p=>p.records.some(r=>r.restriction==='general')&&p.records.some(r=>r.restriction==='study'));
 const general=sample.records.find(r=>r.restriction==='general'),course=sample.records.find(r=>r.restriction==='study'),binding={serverId:sample.serverId,scope_id:sample.scope_id};
 const packet=(n,records=sample.records)=>({...structuredClone(sample),sequence:n,records:structuredClone(records)});
 const pair=(q,a)=>[{role:'user',content:q},{role:'assistant',content:a}];
 const one=q=>[{role:'user',content:q}],response=text=>({choices:[{finish_reason:'stop',message:{content:JSON.stringify({text})}}]});
 const fixture=async()=>{const name='synthetic-research-use-'+crypto.randomUUID();names.push(name);const journal=createChatJournal({name});journals.push(journal);await journal.researchCache.apply(packet(1),binding);await journal.setting('summaryEnabled',false);return {name,journal,cache:journal.researchCache};};
 const select=(use,sessionId)=>use.select({id:general.id,revision:general.revision,sessionId});
 const sender=(journal,use,session,request)=>createChatTransport({journal,research:use,sessionId:()=>session,persona:'合成人设。诚实回答。',request});
 let bodyReads=0,rawReads=0;const oldGet=IDBObjectStore.prototype.get,oldGetAll=IDBObjectStore.prototype.getAll;
 IDBObjectStore.prototype.get=function(...args){if(this.name==='bodies')bodyReads++;if(this.name==='researchMessages')rawReads++;return oldGet.apply(this,args);};
 IDBObjectStore.prototype.getAll=function(...args){if(this.name==='bodies')bodyReads++;if(this.name==='researchMessages')rawReads++;return oldGetAll.apply(this,args);};
 try{
  const {name,journal,cache}=await fixture(),use=createResearchUse({cache});let payloads=[];
  const transport=sender(journal,use,'main',async p=>{payloads.push(p);return response(payloads.length===1?'RESEARCH_ONLY_REPLY':'普通回复');});
  await select(use,'main');check(bodyReads===0,'selection reads metadata only');
  check(await denied(()=>use.select({id:course.id,revision:course.revision}))&&bodyReads===0,'course selection rejected before body access');
  await select(use,'main');const result=await transport.send({input:'THIS_RESEARCH_QUESTION',messages:one('THIS_RESEARCH_QUESTION')});
  check(result.researchUse.status==='used'&&payloads.length===1&&payloads[0].messages[0].content.includes(JSON.stringify(general.body).slice(1,-1)),'actual request contains explicitly selected general summary');
  check(payloads[0].messages[0].content.includes('不是用户事实')&&bodyReads===1,'source block is low trust and body read exactly once');
  let view=await journal.context('main');check(view.session.researchRanges.length===1&&view.session.messages.every(m=>m.content===''),'ordinary session stores no research question or answer text');
  const raw=await journal.readResearchTurn('main',0);check(raw.messages[1].content==='RESEARCH_ONLY_REPLY'&&raw.receipt.source.id===general.id&&raw.receipt.request.inputHash===await hashText('THIS_RESEARCH_QUESTION'),'raw answer and complete source receipt persisted together');
  check(raw.receipt.source.raw_refs&&raw.receipt.source.parents&&raw.receipt.source.sources[0].source_versions,'receipt preserves source versions parent and original hashes');
  const readBefore=rawReads;const restored=await journal.load();await journal.list();await journal.context('main');
  check(rawReads===readBefore&&restored.messages[1].content.includes('原文书架'),'reopen-facing reads return placeholders without reading research raw');
  await transport.send({input:'NORMAL_NEXT',messages:[...raw.messages,...one('NORMAL_NEXT')]});
  check(!JSON.stringify(payloads.at(-1)).includes('RESEARCH_ONLY_REPLY')&&!JSON.stringify(payloads.at(-1)).includes('THIS_RESEARCH_QUESTION')&&!payloads.at(-1).messages[0].content.includes(JSON.stringify(general.body).slice(1,-1)),'next ordinary send excludes both research history and body');
  check(payloads.at(-1).messages.at(-1).content==='NORMAL_NEXT','current ordinary input retained verbatim');
  view=await journal.context('main');check(view.session.researchRanges.length===1&&(await journal.readResearchTurn('main',0)).messages[1].content==='RESEARCH_ONLY_REPLY','ordinary save preserves hidden original and provenance tags');
  const beforeSource=rawReads,source=createMemorySource(journal);await source.listMonths();await source.listDays({month:new Date().toISOString().slice(0,7)});await source.getStatus();
  check(rawReads===beforeSource,'month day and status enumeration never hydrate research raw');
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
  const archive=await source.loadDay({day});check(rawReads===beforeSource+1&&archive.entries.some(e=>e.text.includes('RESEARCH_ONLY_REPLY')&&e.sourceRefs[0].label.includes('不是已审用户事实')),'explicit dated archive hydrates only selected day with provenance label');
  const n=rawReads;await source.loadDay({day:'2001-01-01'});check(rawReads===n,'other-day archive does not read research raw');
  transport.destroy();await journal.close();const reopened=createChatJournal({name});journals.push(reopened);
  check((await reopened.readResearchTurn('main',0)).messages[1].content==='RESEARCH_ONLY_REPLY','research raw survives a new journal instance');
  const oldVersion=await new Promise(resolve=>{const r=indexedDB.open(name,3);r.onerror=()=>resolve(r.error.name);r.onsuccess=()=>{r.result.close();resolve('unexpected');};});check(oldVersion==='VersionError','old v3 readers are fenced after schema upgrade');

  // Old plain records survive v3->v4 without changing their content or indices.
  const legacyName='synthetic-research-legacy-'+crypto.randomUUID();names.push(legacyName);
  const plain={id:'legacy',messages:pair('OLD_PLAIN','OLD_REPLY'),messageTimes:[null,null],updatedAt:'2026-01-01T00:00:00Z'};
  await new Promise((resolve,reject)=>{const r=indexedDB.open(legacyName,3);r.onupgradeneeded=()=>{for(const [store,keyPath] of [['sessions','id'],['meta'],['notes','id'],['revisions','revision'],['summaries','id'],['notePending','revision']])r.result.createObjectStore(store,keyPath?{keyPath}:undefined);};r.onsuccess=()=>{const db=r.result,t=db.transaction(['sessions','meta'],'readwrite');t.objectStore('sessions').put(plain);t.objectStore('meta').put('legacy','selected');t.oncomplete=()=>{db.close();resolve();};};r.onerror=()=>reject(r.error);});
  const upgraded=createChatJournal({name:legacyName});journals.push(upgraded);check(canonical(await upgraded.load())===canonical(plain),'schema upgrade retains existing plain conversation exactly');

  // Budget gates happen before body access and one-shot selection is consumed.
  const b=await fixture(),bu=createResearchUse({cache:b.cache});await select(bu,'budget');let claim=await bu.claim({id:crypto.randomUUID(),sessionId:'budget',input:'q',origin:'user'}),reads=bodyReads;
  const omitted=await bu.prepare(claim,[{role:'system',content:'core'},...one('q')],{room:1,measure:estimateMessageBytes});
  check(omitted.status==='budget_omitted_before_body'&&bodyReads===reads,'budget preflight omits whole block before body read');bu.finish(claim);
  check(await bu.claim({id:crypto.randomUUID(),sessionId:'budget',input:'q',origin:'user'})===null,'budget omission consumes selection without automatic retry');
  await select(bu,'budget');check(await denied(()=>bu.claim({id:crypto.randomUUID(),sessionId:'other',input:'q',origin:'user'})),'selection cannot cross into a different session');
  await select(bu,'budget');check(await denied(()=>bu.claim({id:crypto.randomUUID(),sessionId:'budget',input:'q',origin:'model'})),'model-origin text cannot grant research access');
  await select(bu,'budget');bu.clear();check(await bu.claim({id:crypto.randomUUID(),sessionId:'budget',input:'q',origin:'user'})===null,'clear cancels pending selection');
  await select(bu,'budget');claim=await bu.claim({id:crypto.randomUUID(),sessionId:'budget',input:'q',origin:'user'});await b.cache.apply(packet(2,[]),binding);
  check(await denied(()=>bu.prepare(claim,[{role:'system',content:'core'},...one('q')],{room:32000,measure:estimateMessageBytes})),'withdrawal before request prevents body use');

  // Cache replacement during a paid request must invalidate the answer.
  const stale=await fixture(),su=createResearchUse({cache:stale.cache});await select(su,'stale');let release,entered;
  const started=new Promise(r=>entered=r),t=sender(stale.journal,su,'stale',()=>{entered();return new Promise(r=>release=r);});
  const sending=t.send({input:'q',messages:one('q')});await started;await stale.cache.apply(packet(2,[]),binding);release(response('STALE_RESEARCH'));
  check(await denied(()=>sending)&&(await stale.journal.list()).length===0,'source change during generation discards answer and commits no raw');t.destroy();
  const cancel=await fixture(),cu=createResearchUse({cache:cancel.cache});await select(cu,'cancel');let enteredCancel,resolveCancel;
  const atCancel=new Promise(r=>enteredCancel=r),ct=sender(cancel.journal,cu,'cancel',()=>{enteredCancel();return new Promise(r=>resolveCancel=r);});
  const cp=ct.send({input:'q',messages:one('q')});await atCancel;ct.cancel();check(await denied(()=>cp),'cancel stops in-flight research reply');resolveCancel(response('late'));
  check((await cancel.journal.list()).length===0&&await cu.claim({id:crypto.randomUUID(),sessionId:'cancel',input:'q',origin:'user'})===null,'cancel leaves no saved answer or reusable grant');ct.destroy();

  const atomic=await fixture(),au=createResearchUse({cache:atomic.cache});let seq=1;
  async function prepared(session){await select(au,session);const c=await au.claim({id:crypto.randomUUID(),sessionId:session,input:'atomicQ',origin:'user'});const p=await au.prepare(c,[{role:'system',content:'core'},...one('atomicQ')],{room:32000,measure:estimateMessageBytes});return {c,p,snapshot:{id:session,lastRequestId:c.request.id,messages:pair('atomicQ','atomicA'),messageTimes:['2026-10-01T00:00:00Z','2026-10-01T00:00:01Z']}};}
  let a=await prepared('atomic');await atomic.cache.apply(packet(++seq),binding);
  check(await denied(()=>atomic.journal.save(a.snapshot,{expectedSession:null,researchUse:a.p.receipt}))&&(await atomic.journal.list()).length===0,'final writer rejects changed cache snapshot before atomic commit');
  a=await prepared('quota');const put=IDBObjectStore.prototype.put;IDBObjectStore.prototype.put=function(...args){if(this.name==='sessions')throw new DOMException('synthetic','QuotaExceededError');return put.apply(this,args);};
  try{check(await denied(()=>atomic.journal.save(a.snapshot,{expectedSession:null,researchUse:a.p.receipt})),'injected session failure aborts research write');}finally{IDBObjectStore.prototype.put=put;}
  const orphan=await new Promise((resolve,reject)=>{const r=indexedDB.open(atomic.name,5);r.onsuccess=()=>{const db=r.result,tx=db.transaction('researchMessages'),q=tx.objectStore('researchMessages').getAll();tx.oncomplete=()=>{db.close();resolve(q.result);};};r.onerror=()=>reject(r.error);});
  check(orphan.length===0&&(await atomic.journal.list()).length===0,'failed writer leaves neither orphan raw nor session');
  a=await prepared('bad-hash');a.snapshot.messages[0].content='MUTATED';check(await denied(()=>atomic.journal.save(a.snapshot,{researchUse:a.p.receipt})),'request hash binds exact current user input');
  a=await prepared('course-forge');a.p.receipt.source=structuredClone(course);check(await denied(()=>atomic.journal.save(a.snapshot,{researchUse:a.p.receipt})),'forged course receipt cannot save as general research');
  a=await prepared('source-forge');a.p.receipt.source.sources[0].source_versions={};check(await denied(()=>atomic.journal.save(a.snapshot,{researchUse:a.p.receipt})),'full source descriptor checked inside writer, not only id');
  a=await prepared('signal');const abort=new AbortController();abort.abort();check(await denied(()=>atomic.journal.save(a.snapshot,{signal:abort.signal,researchUse:a.p.receipt})),'aborted save commits nothing');
  a=await prepared('race');await atomic.journal.save({id:'race',messages:pair('OTHER','TAB')});check(await denied(()=>atomic.journal.save(a.snapshot,{expectedSession:null,researchUse:a.p.receipt}))&&(await atomic.journal.context('race')).session.messages[0].content==='OTHER','concurrent session write preserved by final compare');
  a=await prepared('protected');await atomic.journal.save(a.snapshot,{expectedSession:null,researchUse:a.p.receipt});
  check(await denied(()=>atomic.journal.save({id:'protected',messages:[]})),'ordinary save cannot truncate research ranges');
  const prior=await atomic.journal.context('protected');check(await denied(()=>atomic.journal.save({...prior.session,researchRanges:[{start:0,requestId:crypto.randomUUID()}]})),'UI cannot forge or replace provenance tags');

  const long=Array.from({length:40},(_,i)=>({role:i%2?'assistant':'user',content:'old'+i}));const longView={epoch:0,summaryEnabled:true,summaryDays:1,session:{id:'long',messages:long,updatedAt:'2020-01-01T00:00:00Z',researchRanges:[{start:0,requestId:crypto.randomUUID()}]},summaries:[]};
  check(pickSummary(longView)===null&&pickSummary({...longView,session:{...longView.session,researchRanges:[]}})!==null,'old summarization excludes research sessions while ordinary summary remains eligible');
  const packetsSent=[],zero='0'.repeat(64);const sync=await uploadPhoneRaw({journal:{list:async()=>[{id:'has-research',messages:[...pair('PREFIX_Q','PREFIX_A'),...pair('HIDDEN_Q','HIDDEN_A'),...pair('LATER_Q','LATER_A')],researchRanges:[{start:2,requestId:crypto.randomUUID()}]},{id:'ordinary',messages:pair('NORMAL_SYNC','NORMAL_SYNC_A')}]},send:async p=>{
   packetsSent.push(p);let chain=p.previous;for(const turn of p.turns)chain=await hashText(canonical({previous:chain,turn}));return {format:p.format,sessionId:p.sessionId,next:p.start+p.turns.length,chain:p.turns.length?chain:zero};
  }});
  check(!sync.complete&&sync.researchDeferred===1&&sync.uploaded===2&&!JSON.stringify(packetsSent).includes('HIDDEN')&&!JSON.stringify(packetsSent).includes('LATER'),'legacy raw upload keeps stable prefix and other plain sessions, defers research tail');

  const panel=await fixture();let selections=[];const ui=mountResearchCache({container:host,cache:panel.cache,onSelect:ref=>selections.push(ref)});await ui.ready;
  const uses=[...host.querySelectorAll('button')].filter(b=>b.textContent==='用于下一次提问');uses[0].click();await Promise.resolve();
  check(uses.length===1&&selections[0].id===general.id&&!host.textContent.includes(general.body),'actual UI offers general-only one-shot selection without automatic body read');
  ui.destroy();check(!host.children.length,'closing research panel removes DOM');

  const escaped=structuredClone(general);escaped.revision=crypto.randomUUID();escaped.body='"\\\n\t\u0001 中文🙂'.repeat(80);escaped.body_hash=await hashText(escaped.body);
  const exact=await fixture();await exact.cache.apply(packet(2,[escaped]),binding);const eu=createResearchUse({cache:exact.cache});
  await eu.select({id:escaped.id,revision:escaped.revision});let ec=await eu.claim({id:crypto.randomUUID(),sessionId:'escape',input:'q',origin:'user'});
  const baseline=[{role:'system',content:'core'},...one('q')],ep=await eu.prepare(ec,baseline,{room:32768,measure:estimateMessageBytes});
  check(ep.status==='used'&&estimateMessageBytes(ep.payload)<=32768&&JSON.parse(ep.payload[0].content.slice(ep.payload[0].content.indexOf('{'))).text===escaped.body,'escaped quotes controls and Unicode preserve exact source and wire budget');eu.finish(ec);
  await eu.select({id:escaped.id,revision:escaped.revision});ec=await eu.claim({id:crypto.randomUUID(),sessionId:'escape',input:'q',origin:'user'});reads=bodyReads;
  const cut=await eu.prepare(ec,baseline,{room:estimateMessageBytes(ep.payload)-1,measure:estimateMessageBytes});check(cut.status==='budget_omitted_before_body'&&bodyReads===reads,'exact insufficient escaped wire budget gates before body read');
  const failed=await fixture(),fu=createResearchUse({cache:failed.cache});await select(fu,'failed');const ft=sender(failed.journal,fu,'failed',async()=>{throw Error('synthetic network failure');});
  check(await denied(()=>ft.send({input:'q',messages:one('q')}))&&await fu.claim({id:crypto.randomUUID(),sessionId:'failed',input:'q',origin:'user'})===null,'failed request consumes selection without a paid automatic retry');ft.destroy();
  const summaryCase=await fixture();const oldStamp='2020-01-01T00:00:00Z',ordinary={id:'summary-race',messages:long,messageTimes:long.map(()=>oldStamp),updatedAt:oldStamp};
  await summaryCase.journal.setting('summaryEnabled',true);await summaryCase.journal.setting('summaryDays',1);await summaryCase.journal.save(ordinary);const summaryView=await summaryCase.journal.context(ordinary.id),plan=pickSummary(summaryView);
  check(await summaryCase.journal.claimSummary(plan,long.length),'ordinary old summary claim accepted before research arrives');
  const ru=createResearchUse({cache:summaryCase.cache});await select(ru,ordinary.id);const rc=await ru.claim({id:crypto.randomUUID(),sessionId:ordinary.id,input:'q',origin:'user'}),rp=await ru.prepare(rc,baseline,{room:32768,measure:estimateMessageBytes});
  await summaryCase.journal.save({...ordinary,messages:[...long,...pair('q','researchA')],messageTimes:[...ordinary.messageTimes,oldStamp,oldStamp],lastRequestId:rc.request.id},{expectedSession:summaryView.session,researchUse:rp.receipt});
  check(!await summaryCase.journal.commitSummary({...plan,text:'STALE_SUMMARY',updatedAt:oldStamp})&&(await summaryCase.journal.summaries()).length===0,'in-flight old summary cannot commit after research session barrier');
  return checks;
 }finally{
  IDBObjectStore.prototype.get=oldGet;IDBObjectStore.prototype.getAll=oldGetAll;
  for(const j of journals)await j.close();
  for(const name of names)await new Promise((resolve,reject)=>{const r=indexedDB.deleteDatabase(name);r.onsuccess=resolve;r.onerror=()=>reject(r.error);r.onblocked=()=>reject(Error('synthetic cleanup blocked'));});
 }
}
