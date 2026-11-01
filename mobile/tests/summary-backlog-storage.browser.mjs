import {createChatJournal} from '../src/chat-journal.mjs';
import {pickSummary,prepareSummary} from '../src/summary-policy.mjs';
export async function runSummaryBacklogStorageTests(){
  const checks=[],names=[],opened=[],originalNow=Date.now;let now=Date.parse('2026-10-23T04:00:00Z');Date.now=()=>now;
  const ok=(name,condition)=>{if(!condition)throw Error(name);checks.push(name);};
  const reply={choices:[{message:{content:'{"text":"合成摘要"}'},finish_reason:'stop'}]};
  function fixture(){const old=new Date(now-8*86400000).toISOString();return {id:'synthetic',contextEpoch:0,contextStart:0,messages:Array.from({length:40},(_,i)=>[{role:'user',content:'合成问题'+i},{role:'assistant',content:'合成回答'+i}]).flat(),messageTimes:Array(80).fill(old),updatedAt:old};}
  const seed=(name,legacy=false)=>new Promise((resolve,reject)=>{
    const r=indexedDB.open(name,legacy?1:3);r.onupgradeneeded=()=>{for(const store of ['sessions','meta','notes','revisions',...legacy?[]:['summaries','notePending']])r.result.createObjectStore(store,store==='meta'?undefined:{keyPath:store==='revisions'?'revision':'id'});};
    r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result,tx=db.transaction(['sessions','meta'],'readwrite'),value=fixture();if(legacy){delete value.messageTimes;delete value.contextEpoch;delete value.contextStart;}tx.objectStore('sessions').put(value);tx.objectStore('meta').put(value.id,'selected');tx.oncomplete=()=>{db.close();resolve();};tx.onabort=()=>reject(tx.error);};
  });
  async function fresh(legacy=false){const name='gernze-summary-test-'+crypto.randomUUID();names.push(name);await seed(name,legacy);const journal=createChatJournal({name});opened.push(journal);return {name,journal};}
  const mutate=(name,store,key,value)=>new Promise((resolve,reject)=>{const r=indexedDB.open(name,5);r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result,tx=db.transaction(store,'readwrite');key===undefined?tx.objectStore(store).put(value):tx.objectStore(store).put(value,key);tx.oncomplete=()=>{db.close();resolve();};tx.onabort=()=>reject(tx.error);};});
  const commit=(journal,plan,options)=>journal.commitSummary({...plan,text:'合成摘要',updatedAt:new Date(now).toISOString()},options);
  try{
    const legacy=await fresh(true);ok('v1 journal upgrades without losing undated raw text',(await legacy.journal.load()).messages.length===80);ok('legacy session still schedules using updatedAt',!!pickSummary(await legacy.journal.context('synthetic')));
    const legacySaved=await legacy.journal.load();legacySaved.messageTimes=Array(80).fill(null);legacySaved.messages.push(...fixture().messages.slice(0,2));legacySaved.messageTimes.push(...Array(2).fill(new Date(now).toISOString()));legacySaved.updatedAt=new Date(now).toISOString();await legacy.journal.save(legacySaved);ok('first new reply does not postpone undated legacy backlog',!!pickSummary(await legacy.journal.context('synthetic')));
    const {name,journal}=await fresh();let v=await journal.context('synthetic'),p=pickSummary(v),source=p.sourceText;
    ok('first claim accepted',await journal.claimSummary(p,80));ok('first batch committed',await commit(journal,p));v=await journal.context('synthetic');
    ok('clock not reset while backlog remains',v.summaryClock===undefined);ok('fixed cycle persisted',v.summaryCycle.end===68);ok('next range immediately available',pickSummary(v).start===12);ok('source is exact original range',source===JSON.stringify(v.session.messages.slice(0,12)));
    ok('stale plan cannot claim again',!await journal.claimSummary(p,80));
    await journal.close();const reopened=createChatJournal({name});opened.push(reopened);v=await reopened.context('synthetic');ok('reopen keeps backlog eligible',pickSummary(v).start===12);
    let batches=1;while((p=pickSummary(await reopened.context('synthetic')))){ok('success unlocks next range '+batches,await reopened.claimSummary(p,80));ok('commit source range '+batches,await commit(reopened,p));batches++;if(batches>10)throw Error('unbounded cycle');}
    v=await reopened.context('synthetic');ok('six bounded batches finish 34 old turns',batches===6&&v.summaries.length===6);ok('cycle completed and clock reset',!v.summaryCycle&&v.summaryClock===now);ok('recent six turns untouched',v.session.messages.length===80&&Math.max(...v.summaries.map(s=>s.end))===68);
    // Two independent runtimes exercise actual transaction serialization.
    const parallel=await fresh(),other=createChatJournal({name:parallel.name});opened.push(other);const one=pickSummary(await parallel.journal.context('synthetic')),two=structuredClone(one);
    const claims=await Promise.all([parallel.journal.claimSummary(one,80),other.claimSummary(two,80)]);ok('cross-window transaction grants one claim',claims.filter(Boolean).length===1);
    const winner=claims[0]?one:two;ok('only claimed result commits',await commit(parallel.journal,winner));ok('duplicate commit rejected',!await commit(other,winner));
    const failure=await fresh();let calls=0;
    const runFailure=async()=>prepareSummary({view:await failure.journal.context('synthetic'),journal:failure.journal,request:async()=>{calls++;throw Error('synthetic offline');},cancel:()=>{}});
    await runFailure();await runFailure();ok('failed callback not immediately rebilled',calls===1);now+=86400000;await runFailure();ok('one day alone does not unlock failure',calls===1);
    const raw=await failure.journal.load();raw.messages.push(...fixture().messages.slice(0,6));raw.messageTimes.push(...Array(6).fill(new Date(now).toISOString()));await failure.journal.save(raw);await runFailure();ok('day plus six messages unlocks one retry',calls===2);
    const oldAttempt=await fresh();await mutate(oldAttempt.name,'meta','summaryAttempt:synthetic',{epoch:0,latest:80,at:now});ok('legacy attempt retains bill guard',!await oldAttempt.journal.claimSummary(pickSummary(await oldAttempt.journal.context('synthetic')),80));
    const late=await fresh();const first=pickSummary(await late.journal.context('synthetic'));await late.journal.claimSummary(first,80);now+=86400000;const appended=await late.journal.load();appended.messages.push(...fixture().messages.slice(0,6));appended.messageTimes.push(...Array(6).fill(new Date(now).toISOString()));await late.journal.save(appended);const retry=pickSummary(await late.journal.context('synthetic'));ok('same range retry accepted after backoff',await late.journal.claimSummary(retry,86));ok('old claim token cannot commit',!await commit(late.journal,first));ok('current claim token commits',await commit(late.journal,retry));
    for(const mode of ['epoch','disabled','source','abort']){
      const f=await fresh(),plan=pickSummary(await f.journal.context('synthetic'));await f.journal.claimSummary(plan,80);const controller=new AbortController();
      if(mode==='epoch')await mutate(f.name,'meta','memoryEpoch',1);
      if(mode==='disabled')await f.journal.setting('summaryEnabled',false);
      if(mode==='source'){const raw=await f.journal.load();raw.messages[0].content='已纠正的原文';await f.journal.save(raw);}
      if(mode==='abort')controller.abort();
      ok(mode+' fences late commit',!await commit(f.journal,plan,{signal:controller.signal}));ok(mode+' keeps summary store empty',(await f.journal.summaries()).length===0);
    }
    const cancel=await fresh(),controller=new AbortController();let resolve,entered;const started=new Promise(r=>entered=r);
    const pending=prepareSummary({view:await cancel.journal.context('synthetic'),journal:cancel.journal,signal:controller.signal,request:()=>{entered();return new Promise(r=>resolve=r);},cancel:()=>{}}).then(()=>false,e=>e.code==='cancelled');
    await started;controller.abort();ok('cancel settles promptly',await pending);resolve(reply);await new Promise(r=>setTimeout(r,0));ok('cancelled ignored late callback never stored',(await cancel.journal.summaries()).length===0);
    return {status:'passed',checks,realAPI:0,indexedDB:true,androidDevice:false};
  }finally{Date.now=originalNow;for(const j of opened)await j.close();for(const name of names)indexedDB.deleteDatabase(name);}
}
