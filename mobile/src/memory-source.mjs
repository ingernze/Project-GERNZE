// Read-only contract for the independently built monthly bookshelf. No demo data.
export function createMemorySource(journal,{timeZone='Asia/Shanghai',layered=()=>null}={}){
  const format=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'});
  const dayOf=stamp=>{if(!stamp||!Number.isFinite(Date.parse(stamp)))return null;const p=Object.fromEntries(format.formatToParts(new Date(stamp)).map(x=>[x.type,x.value]));return `${p.year}-${p.month}-${p.day}`;};
  const check=signal=>{if(signal?.aborted)throw new DOMException('已取消','AbortError');};
  async function data(signal){
    check(signal);const [sessions,view,segments]=await Promise.all([journal.list(),journal.context(),journal.summaries?journal.summaries():[]]);check(signal);
    const days=new Map();let undatedTurns=0;
    function add(day,entry){if(!days.has(day))days.set(day,[]);days.get(day).push(entry);}
    for(const n of view.records){
      const day=dayOf(n.updated_at);if(!day)continue;
      add(day,{id:'note:'+n.id,kind:'memory',text:n.title+'\n'+n.body+(n.event_date?'\n事件日期：'+n.event_date:''),status:'active',sourceRefs:[{id:n.id,label:'主动保存的记忆'}],updatedAt:n.updated_at});
    }
    const layers=await layered();check(signal);
    const mirrored=new Set();
    for(const [tier,entries] of [[2,layers?.approved||[]],[3,layers?.working||[]]])for(const n of entries){mirrored.add(n.sourceSummaryId);const day=dayOf(n.sourceAt||n.updatedAt);if(day)add(day,{id:'layer:'+tier+':'+n.key+':'+n.revision,kind:tier===3?'summary':'memory',text:(tier===2?'第二层 · 已审核':'第三层 · 待审核')+'\n'+n.body,status:'active',sourceRefs:[{id:n.sourceSessionId||n.key,label:'第四层原文 '+((n.sourceStart??0)/2+1)+'—'+(n.sourceEnd??0)/2+'轮'}],updatedAt:n.updatedAt});}
    for(const s of segments){const day=dayOf(s.sourceAt);if(day&&s.epoch===view.epoch&&!mirrored.has(s.id)&&!layers)add(day,{id:'summary:'+s.id,kind:'summary',text:s.text,status:'active',sourceRefs:[{id:s.sessionId,label:'聊天原文 '+(s.start/2+1)+'—'+s.end/2+'轮'}],updatedAt:s.updatedAt});}
    for(const session of sessions)for(let i=0;i<session.messages.length;i+=2){
      const stamp=session.messageTimes?.[i],day=dayOf(stamp);if(!day){undatedTurns++;continue;}
      add(day,{id:`chat:${session.id}:${i/2}`,kind:'conversation',text:'你：'+session.messages[i].content+'\n\n莉宝：'+session.messages[i+1].content,status:'active',sourceRefs:[{id:session.id,label:'聊天原文'}],updatedAt:session.messageTimes[i+1]||stamp});
    }
    return {days,undatedTurns};
  }
  return Object.freeze({
    async listMonths({signal}={}){const {days}=await data(signal),months=new Map();for(const [day,entries] of days){const month=day.slice(0,7),v=months.get(month)||{month,dayCount:0,entryCount:0};v.dayCount++;v.entryCount+=entries.length;months.set(month,v);}return [...months.values()].sort((a,b)=>b.month.localeCompare(a.month));},
    async listDays({month,signal}={}){if(!/^\d{4}-\d{2}$/.test(month))throw Error('月份无效。');const {days}=await data(signal);return [...days].filter(([day])=>day.startsWith(month+'-')).sort(([a],[b])=>a.localeCompare(b)).map(([day,entries])=>({day,entryCount:entries.length,hasSummary:entries.some(e=>e.kind==='summary'),hasOriginal:entries.some(e=>e.kind==='conversation')}));},
    async loadDay({day,signal}={}){if(!/^\d{4}-\d{2}-\d{2}$/.test(day))throw Error('日期无效。');const {days}=await data(signal);return {day,entries:(days.get(day)||[]).sort((a,b)=>a.updatedAt.localeCompare(b.updatedAt)||a.id.localeCompare(b.id))};},
    async getStatus({signal}={}){const {undatedTurns}=await data(signal);return {undatedTurns,automaticSummary:typeof journal.commitSummary==='function'&&((await journal.setting('summaryEnabled'))!==false),syncEnabled:typeof journal.setting==='function'&&((await journal.setting('syncEnabled'))!==false)};}
  });
}
