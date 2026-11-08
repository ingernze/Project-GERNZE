import {shelfIndices,safeShelfSummaries,safeShelfWorking} from './bookshelf-use.mjs';
import protocol from '../../src/workbench/chat-protocol.json' with {type:'json'};
import {layersPrompt} from './memory-layers.mjs';
import {prepareSummary,selectSummaries,summaryPrompt,SUMMARY_CALLS_PER_SEND} from './summary-policy.mjs';
import {notePrompt} from './memory-records.mjs';
import {autoWebCommand} from './web-use.mjs';
// Local limits use JS/Java UTF-16 code units; these are NOT bytes or tokens.
// Keep in step with journal.validateSnapshot and the renderer restore guard.
export const MAX_MESSAGE_UNITS=12000;
export const STANDARD_CONTEXT_BYTES=32768;
export const DEEPSEEK_CONTEXT_BYTES=131072;
const WEB_HEADROOM_BYTES=8192;
const AUTO_WEB_GUIDE='\n可用 search_public_web 工具。在当前问题需要最新信息、外部事实或来源时自行选用。日常交流、已足够回答的问题及私人资料直接回复。只提供本条用户消息已经包含的公开关键词，可用空格组合，勿填记忆、旧对话或个人信息。收到工具材料前不能声称已查证。';
export const MAX_RESPONSE_CONTENT_UNITS=100000; // provider message.content, including JSON/fence
export const CONTEXT_SAFETY_BYTES=1024;
export const OUTPUT_BYTES_PER_TOKEN_ESTIMATE=8;
export const estimateMessageBytes=messages=>new TextEncoder().encode(JSON.stringify(messages)).length+messages.length*64;

export function replyBudgetFor(text,origin='user'){
  // Match the current desktop's finite rule. Source roles and mixed quotes
  // cannot promote themselves into a larger output allowance.
  const direct=typeof text==='string'?text.trim():'';
  const quoted=/```|["'“”「」『』>]/.test(direct);
  const detailed=origin==='user'&&!quoted&&/^(?:请|帮我|麻烦|能否|我想请你|能不能)?(?:再)?(?:详细|深入|全面|展开)(?:地)?(?:分析|解释|说明|讲解|比较|说说)/.test(direct);
  const maxTokens=detailed?1800:700;
  // Existing window guard counts UTF-8 bytes plus framing, not model tokens.
  // This deliberately padded conversion is a heuristic, not a tokenizer or a
  // guarantee for every provider/vocabulary. Keep the extra safety gap separate.
  const outputEstimateBytes=maxTokens*OUTPUT_BYTES_PER_TOKEN_ESTIMATE;
  return Object.freeze({maxTokens,outputEstimateBytes,safetyBytes:CONTEXT_SAFETY_BYTES,
    reserveBytes:outputEstimateBytes+CONTEXT_SAFETY_BYTES,countKind:'utf8_bytes_plus_framing_estimate'});
}

// Narrow JS -> native adapter, shared by the UI and offline connection checks.
// Credentials stay native; no headers, logging, retries or model classification.
export function createNativeChatRequest(bridge){
  return async({id,messages,purpose,maxTokens,allowWebSearch})=>(await bridge.request({id,messages,
    purpose:purpose||'chat',...(maxTokens===undefined?{}:{maxTokens}),...(allowWebSearch?{allowWebSearch:true}:{})})).data;
}

// Native bridge owns credentials and the approved provider tool schema.
const fail=(message,code='chat_failed')=>Object.assign(Error(message),{code});
export function buildMessages(messages,persona,{budget=STANDARD_CONTEXT_BYTES,reserve=replyBudgetFor(Array.isArray(messages)?messages.at(-1)?.content:undefined).reserveBytes,notes=[],summaries=[],layers=null,headroom=0}={}){
  if(!Number.isSafeInteger(budget)||!Number.isSafeInteger(reserve)||budget<1||reserve<0)throw fail('上下文预算无效。','budget_exceeded');
  if(!Array.isArray(messages)||!messages.length||messages.length%2!==1)throw fail('对话轮次不完整。');
  if(typeof persona!=='string'||!persona.trim()||persona.length>8000)throw fail('人物设定未准备好。');
  const history=messages.map((m,i)=>{
    if(!m||m.role!==(i%2?'assistant':'user')||typeof m.content!=='string'||!m.content.trim()||m.content.length>MAX_MESSAGE_UNITS)throw fail('对话内容无效。');
    return {role:m.role,content:m.content};
  }).slice(-999);
  const kept=summaries.slice(),layerView=layers?{...layers,approved:[...(layers.approved||[])],working:[...(layers.working||[])]}:null;
  const outputProtocol='\n'+protocol.instruction;
  const system={role:'system',content:''},current=history.at(-1),room=budget-reserve;
  const cost=estimateMessageBytes,confirmedNotes=notePrompt(notes);
  const render=(layers,summaries)=>(layers?'第一层 · 只读核心人设：\n':'')+persona+(layers?layersPrompt(layers):'')+confirmedNotes+summaryPrompt(summaries)+outputProtocol;
  const fixed=render(layerView&&{...layerView,approved:[],working:[]},[]);
  const minimum=cost([{...system,content:fixed},current]);
  if(minimum>room)throw fail('这条消息超出当前上下文预算，请缩短后发送。','budget_exceeded');
  const inputRoom=Math.max(minimum,room-headroom);
  // Protect the latest three complete pairs before allocating optional memory.
  system.content=fixed;
  let selected=[system,current],i=history.length-3;
  for(;i>=Math.max(0,history.length-7);i-=2){
    const next=[system,...history.slice(i,i+2),...selected.slice(1)];
    if(cost(next)>inputRoom)break;
    selected=next;
  }
  system.content=render(layerView,kept);
  while(cost(selected)>inputRoom){
    if(kept.length)kept.shift();
    else if(layerView?.working.length)layerView.working.pop();
    else if(layerView?.approved.length)layerView.approved.pop();
    else break;
    system.content=render(layerView,kept);
  }
  for(;i>=0;i-=2){const next=[system,...history.slice(i,i+2),...selected.slice(1)];if(cost(next)>inputRoom)break;selected=next;}
  return selected;
}
export function normalizeReply(response){
  if(!response||typeof response!=='object')throw fail('服务没有返回有效回复。');
  const choice=response.choices?.[0];
  if(!choice||!['stop',undefined,null].includes(choice.finish_reason))throw fail('回复未完整生成，请重试。');
  let text=choice.message?.content;if(typeof text!=='string'||!text.trim()||text.length>MAX_RESPONSE_CONTENT_UNITS)throw fail('服务回复为空或超过原始内容上限（100000个UTF-16代码单元），未截断保存。','invalid_response');
  text=text.trim();const fenced=text.startsWith('```');
  if(fenced){
    if(!text.endsWith('```')||!text.includes('\n'))throw fail('回复围栏未完整结束，未保存。','invalid_response');
    text=text.slice(text.indexOf('\n')+1,text.lastIndexOf('```')).trim();
  }
  let value;try{value=JSON.parse(text);}catch{
    if(fenced||/^[{\[]/.test(text))throw fail('回复JSON损坏，未作为普通文字保存。','invalid_response');
    value={text};
  }
  if(!value||typeof value.text!=='string'||!value.text.trim())throw fail('回复格式不完整，请重试。');
  if(value.text.length>MAX_MESSAGE_UNITS)throw fail('回复超过本地正文上限（12000个UTF-16代码单元），未截断保存。','reply_too_long');
  return {reply:value.text.trim(),emotion:['normal','happy','annoyed'].includes(value.emotion)?value.emotion:'normal',action:value.action==='sway'?'sway':'none'};
}
export function createChatTransport({request,cancel=()=>{},persona,sessionId,journal,onPersistenceError=()=>{},uuid=()=>crypto.randomUUID(),timeoutMs=90000,budget=STANDARD_CONTEXT_BYTES,allowAutoWeb=false,onSummaryStatus=()=>{},memory=null,onMemoryStatus=()=>{},research=null,onResearchStatus=()=>{},shelf=null,onShelfStatus=()=>{},web=null,describeCapabilities=null}={}){
  if(research&&journal?.researchVersion!==1)throw fail('研究资料需要新版会话存储。');
  let generation=0,active=null,disposed=false,summaryJob=null;
  const abortError=()=>fail('已停止本轮回复。','cancelled');
  function stop(){web?.cancel();research?.clear();generation++;summaryJob?.controller.abort();if(active){const old=active;active=null;old.stop();}}
  async function yieldSummary(){
    const job=summaryJob;if(!job)return;job.controller.abort();let timer;
    // A cancelled native HTTP request must drain before using its single request slot.
    const drained=await Promise.race([job.done.then(()=>true),new Promise(r=>timer=setTimeout(()=>r(false),1000))]);clearTimeout(timer);
    if(!drained)throw fail('摘要请求尚在停止，请稍后重试聊天。','busy');
  }
  function startSummaries(session,ticket,epoch,mirror,historyRoom){
    if(!journal.commitSummary||disposed||ticket!==generation)return;
    const job={controller:new AbortController(),pending:null,done:null};summaryJob=job;
    const signal=job.controller.signal;
    job.done=Promise.resolve().then(async()=>{
      for(let i=0;i<SUMMARY_CALLS_PER_SEND;i++){
        if(signal.aborted||disposed||ticket!==generation||session!==sessionId())break;
        const view=await journal.context(session);
        if(signal.aborted||view.epoch!==epoch||session!==sessionId())break;
        const saved=await prepareSummary({view,journal,signal,cancel,historyRoom,onStatus:onSummaryStatus,onCommitted:s=>mirror([s]),request:payload=>{
          if(signal.aborted)throw abortError();
          const work=Promise.resolve(request(payload));job.pending=work.then(()=>{},()=>{});return work;
        }});
        if(!saved)break;
        if(!signal.aborted)onSummaryStatus('较早对话已保存为摘要；剩余积压在本次上限内继续，或留到下次发送。');
      }
    }).catch(error=>{if(!signal.aborted)onSummaryStatus(error.message||'摘要未完成，原文仍保留。');}).finally(async()=>{
      // Keep the job visible if cancellation/timeout returned before native HTTP settled.
      if(job.pending)await job.pending;
      if(summaryJob===job)summaryJob=null;
    });
  }
  return Object.freeze({
    async send({input,messages,signal,origin='user'}){
      if(disposed||signal?.aborted){research?.clear();throw abortError();}
      if(active)throw fail('上一轮还在处理中。','busy');
      if(messages?.at(-1)?.content!==input){research?.clear();throw fail('输入与会话内容不一致。');}
      const id=uuid(),session=sessionId(),ticket=++generation;if(typeof session!=='string'||!session)throw fail('会话尚未准备好。');
      let timer,abort,timeout=false,claim=null,shelfPrepared={claim:null,receipt:null,status:'not_selected'};
      const startedAt=new Date().toISOString(),controller=new AbortController();
      let requestId=id;
      const stopped=new Promise((_,reject)=>{
        abort=()=>{controller.abort();const pending=requestId;Promise.resolve().then(()=>cancel(pending)).catch(()=>{});reject(timeout?fail('请求超时，请稍后再试。','timeout'):abortError());};
        signal?.addEventListener('abort',abort,{once:true});timer=setTimeout(()=>{timeout=true;abort();},timeoutMs);
      });
      // Cancellation can arrive before the first operation races this promise.
      void stopped.catch(()=>{});
      active={id,stop:abort};
      try{
        claim=research?await Promise.race([research.claim({id,sessionId:session,input,origin}),stopped]):null;
        if(summaryJob)await Promise.race([yieldSummary(),stopped]);
        if(disposed||controller.signal.aborted||ticket!==generation)throw abortError();
        let view=journal.context?await Promise.race([journal.context(session),stopped]):{epoch:0,records:[],session:null};
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const sources=journal.shelfSources?await journal.shelfSources():[];
        const mirror=async segments=>{if(!memory)return;try{const current=journal.shelfSources?await journal.shelfSources():sources;const r=await memory.syncSummaries(safeShelfSummaries(segments,current));if(r.changed)onMemoryStatus(r);}catch(error){onMemoryStatus({error:error.message});}};
        // Recover a missed local mirror without another model request; archives stay intact.
        if(memory&&journal.summaries)await mirror((await journal.summaries()).filter(s=>s.epoch===view.epoch));
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const old=view.session;
        const researchIndices=new Set((old?.researchRanges||[]).flatMap(r=>[r.start,r.start+1]));
        const prefixMatches=old&&old.messages.length===messages.length-1&&old.messages.every((m,i)=>m.role===messages[i].role&&(researchIndices.has(i)||m.content===messages[i].content));
        const sameEpoch=(old?.contextEpoch??0)===view.epoch;
        const contextStart=sameEpoch&&(!old||prefixMatches)?(old?.contextStart??0):messages.length-1;
        const hostReply=describeCapabilities&&!claim
          ?await Promise.race([describeCapabilities({input,previousInput:messages.at(-3)?.content??'',origin}),stopped]):null;
        if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
        const replyBudget=replyBudgetFor(input,origin);
        let payload=[],prepared={receipt:null,status:'not_selected'},reply,historyRoom;
        if(hostReply)reply={reply:hostReply,emotion:'normal',action:'none'};
        else{
          const summarized=safeShelfSummaries(selectSummaries(view,input),sources);
          const covered=Math.max(contextStart,...(view.summaries||[]).filter(s=>s.epoch===view.epoch&&s.start>=contextStart).map(s=>s.end));
          const layerView=memory?await memory.context(input,{epoch:view.epoch,sessionSummaries:summarized}):null;
          if(layerView){layerView.originalStoredMessages=old?.messages.length??0;layerView.working=safeShelfWorking(layerView.working||[],sources);}
          const history=prefixMatches?[...old.messages,{role:'user',content:input}]:messages;
          const shelfHistory=shelfIndices(prefixMatches?old:null);
          const safeHistory=history.filter((m,i)=>i>=covered&&!(prefixMatches&&researchIndices.has(i))&&!shelfHistory.has(i));
          const guard=()=>{
            if(disposed||controller.signal.aborted||ticket!==generation||session!==sessionId())throw abortError();
          };
          const validate=async()=>{
            guard();
            if(shelfPrepared.claim)await shelf.validate(shelfPrepared.claim);
            if(claim)await research.validate(claim);
            guard();
          };
          const plan=web?await Promise.race([web.plan({input,origin,allowAuto:allowAutoWeb&&!claim}),stopped]):null;
          guard();
          const headroom=plan?.command||plan?.auto?WEB_HEADROOM_BYTES:0,room=budget-replyBudget.reserveBytes;
          payload=buildMessages(safeHistory,persona,{budget,reserve:replyBudget.reserveBytes,headroom,
            notes:view.records,summaries:memory?[]:summarized,layers:layerView});
          const optionalRoom=Math.max(estimateMessageBytes(payload),room-headroom);
          prepared=research?await research.prepare(claim,payload,{room:optionalRoom,measure:estimateMessageBytes}):{payload,receipt:null,status:'not_selected'};
          payload=prepared.payload;
          if(shelf&&!claim){
            const queryHistory=history.filter((m,i)=>i>=contextStart&&!(prefixMatches&&researchIndices.has(i))&&m.role==='user');
            shelfPrepared=await shelf.prepare({input,messages:queryHistory,origin},payload,{room:optionalRoom,measure:estimateMessageBytes});
            payload=shelfPrepared.payload;
          }
          historyRoom=Math.max(1,room-headroom-estimateMessageBytes([payload[0]]));
          const prepareWeb=command=>Promise.race([web.prepare({id,session,input,origin,signal:controller.signal,payload,room,measure:estimateMessageBytes,command}),stopped]);
          const ask=async(messages,tools=false)=>{
            await validate();
            guard();
            const result=await Promise.race([request({id:requestId,messages,purpose:'chat',maxTokens:replyBudget.maxTokens,signal:controller.signal,...(tools?{allowWebSearch:true}:{})}),stopped]);
            await validate();
            return result;
          };
          let webPrepared=web&&!plan.auto?await prepareWeb(plan.command):null;
          if(webPrepared)payload=webPrepared.payload;
          const hinted=plan?.auto?[{...payload[0],content:payload[0].content+AUTO_WEB_GUIDE},...payload.slice(1)]:null;
          const useTool=hinted!==null&&estimateMessageBytes(hinted)<=room;
          let raw=await ask(useTool?hinted:payload,useTool);
          const choice=raw?.choices?.[0];
          if(useTool&&(choice?.finish_reason==='tool_calls'||choice?.message?.tool_calls?.length)){
            webPrepared=await prepareWeb(autoWebCommand(raw,input)||false);
            payload=webPrepared.payload;
            requestId=id+'-final';
            raw=await ask(payload);
          }
          const normalized=normalizeReply(raw);
          reply=webPrepared?webPrepared.decorate(normalized):normalized;
        }
        if(shelfPrepared.receipt){reply.reply+='\n\n参考书架片段：'+shelfPrepared.receipt.refs.map(r=>r.title+' · '+r.id+' @'+r.revision).join('；');if(reply.reply.length>MAX_MESSAGE_UNITS)throw fail('回复与来源超过正文保存上限，未截断保存。','reply_too_long');}
        if(reply.reply.length>MAX_MESSAGE_UNITS)throw fail('回复与来源超过本地正文上限，未截断保存。','reply_too_long');
        const stamp=new Date().toISOString();
        const times=prefixMatches?(old.messageTimes??Array(messages.length-1).fill(null)):Array(messages.length-1).fill(null);
        const snapshot={id:session,messages:[...messages,{role:'assistant',content:reply.reply}],messageTimes:[...times,startedAt,stamp],contextEpoch:view.epoch,contextStart,updatedAt:stamp,lastRequestId:id};
        const shelfRanges=[...(old?.shelfRanges||[])];if(shelfPrepared.receipt)shelfRanges.push({start:messages.length-1,receipt:shelfPrepared.receipt});if(shelfRanges.length)snapshot.shelfRanges=shelfRanges;
        let persisted=true;
        const save=beforeCommit=>journal.save(snapshot,{signal:controller.signal,expectedMemoryEpoch:view.epoch,expectedSession:view.session??null,researchUse:prepared.receipt,beforeCommit});
        try{if(shelf)await shelf.commit(shelfPrepared.claim,save);else await save();}
        catch(error){if(controller.signal.aborted)throw abortError();if(error.code==='context_changed'||prepared.receipt||shelfPrepared.receipt)throw error;persisted=false;onPersistenceError(error);}
        if(disposed||signal?.aborted||ticket!==generation||session!==sessionId())throw abortError();

        if(persisted&&!hostReply)startSummaries(session,ticket,view.epoch,mirror,historyRoom);
        const contextBudget={...replyBudget,windowBytes:budget,inputLimitBytes:budget-replyBudget.reserveBytes,inputEstimateBytes:estimateMessageBytes(payload)};
        onResearchStatus(prepared.status);onShelfStatus(shelfPrepared.status);
        return {id,...reply,contextBudget,researchUse:{status:prepared.status},shelfUse:{status:shelfPrepared.status,refs:shelfPrepared.receipt?.refs}};
      }finally{research?.finish(claim);clearTimeout(timer);signal?.removeEventListener('abort',abort);if(active?.id===id)active=null;}
    },cancel:stop,destroy(){stop();disposed=true;}
  });
}
