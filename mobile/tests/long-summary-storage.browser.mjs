import {createChatJournal} from '../src/chat-journal.mjs';
import {pickSummary,summaryBlocked,summaryReadiness} from '../src/summary-policy.mjs';
export async function runLongSummaryStorageTests(){
  const checks=[],opened=[],names=[];const ok=(name,value)=>{if(!value)throw Error(name);checks.push(name);};
  const old=new Date(Date.now()-8*86400000).toISOString();
  async function fresh(bodies){
    const name='gernze-long-summary-'+crypto.randomUUID();names.push(name);const journal=createChatJournal({name});opened.push(journal);
    const messages=Array.from({length:9},(_,i)=>[{role:'user',content:'合成问题'+i},{role:'assistant',content:bodies[i]||'最近原文'}]).flat();
    const value={id:'synthetic',contextEpoch:0,contextStart:0,messages,messageTimes:Array(messages.length).fill(old),updatedAt:old};await journal.save(value);return {name,journal,raw:JSON.stringify(value.messages)};
  }
  const commit=async(journal,p)=>{const view=await journal.context('synthetic');ok('claim '+p.start,await journal.claimSummary(p,view.session.messages.length));ok('commit '+p.start,await journal.commitSummary({...p,text:'合成短摘要',updatedAt:new Date().toISOString()}));};
  try{
    const first=await fresh(['中'.repeat(2500),'文'.repeat(2500),'字'.repeat(2500)]);
    for(let i=0;i<3;i++){
      const view=await first.journal.context('synthetic'),p=pickSummary(view);ok('whole long pair selected '+i,p.start===i*2&&p.end===i*2+2);await commit(first.journal,p);
      const next=await first.journal.context('synthetic');ok('clock only advances at cycle completion '+i,i===2?!next.summaryCycle&&next.summaryClock>Date.parse(old):!!next.summaryCycle&&next.summaryClock===Date.parse(old));
    }
    ok('all raw text and newest six retained',JSON.stringify((await first.journal.load()).messages)===first.raw);
    const blocked=await fresh(['短合成','中'.repeat(6000),'后续未跳过']);
    const p=pickSummary(await blocked.journal.context('synthetic'));ok('only valid prefix selected',p.end===2);await commit(blocked.journal,p);
    let view=await blocked.journal.context('synthetic');ok('blocked range keeps frozen cycle and old clock',!!view.summaryCycle&&view.summaryClock===Date.parse(old)&&summaryBlocked(view));
    ok('blocked display explains budget rather than too few turns',summaryReadiness(view).includes('超过单次摘要输入预算'));
    ok('old prefix claim cannot replay',!await blocked.journal.claimSummary(p,18));
    await blocked.journal.close();const reopened=createChatJournal({name:blocked.name});opened.push(reopened);view=await reopened.context('synthetic');
    ok('reopen preserves blocked cycle and original range',summaryBlocked(view)&&!!view.summaryCycle&&view.summaryClock===Date.parse(old)&&JSON.stringify((await reopened.load()).messages)===blocked.raw);
    ok('no false summary for oversized range',(await reopened.summaries()).length===1&&pickSummary(view)===null);
    return {status:'passed',checks,indexedDB:true,realAPI:0};
  }finally{for(const journal of opened)await journal.close();for(const name of names)indexedDB.deleteDatabase(name);}
}
