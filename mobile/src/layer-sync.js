import {registerPlugin} from '@capacitor/core';
import {uploadPhoneRaw} from './raw-sync.mjs';
import {uploadPhoneResearch,RESEARCH_RAW_FORMAT} from './research-raw-sync.mjs';
const native=registerPlugin('HebaoUpdateTransport');
export async function mountMemorySync({container,layers,journal,beforeChange=()=>{},afterChange=async()=>{},agentSync=null,bookshelfSync=null}){
 const section=document.createElement('section');section.className='panel';
 section.innerHTML='<h3>电脑与手机记忆互通</h3><label><input data-enabled type="checkbox"> 定期同步第三层与第四层到电脑</label><label>传输间隔（天，最短1天）<input data-days type="number" min="1" max="3650" step="1"></label><p class="hint">手机在前台，与已配对电脑连通、电脑更新窗口开启时执行。先上传第四层简版原文，再同步第三层；审查统一在电脑，第二层审核结果同步回来。第一层与密钥不传。</p><button data-now type="button">同步到电脑并接回审核结果</button><p data-status role="status"></p><div data-conflicts></div>';
 container.append(section);const $=s=>section.querySelector(s);let alive=true,active=true,busy=false,retryAt=0;
 const pair=()=>{try{return JSON.parse(localStorage.getItem('hebao.updates.v1')||'{}').pair?.pairingId;}catch{return null;}};
 const eligible=()=>alive&&active&&!document.hidden&&!window.HebaoDialogueController?.getSnapshot().pending;
 $('[data-enabled]').checked=(await journal.setting('layerSyncEnabled'))!==false;$('[data-days]').value=String(await journal.setting('layerSyncDays')||7);
 const status=text=>{if(alive)$('[data-status]').textContent=text;};
 $('[data-enabled]').onchange=()=>journal.setting('layerSyncEnabled',$('[data-enabled]').checked).catch(e=>status(e.message));
 $('[data-days]').onchange=async()=>{const n=Number($('[data-days]').value);try{await journal.setting('layerSyncDays',n);status('自动传输间隔已设为'+n+'天。');}catch(e){status(e.message);}};
 async function showConflicts(){const state=await layers.sync.conflicts();if(!alive)return;const box=$('[data-conflicts]');box.replaceChildren();if(state?.conflicts?.length){const p=document.createElement('p');p.textContent='有 '+state.conflicts.length+' 条同步冲突，已暂停用于聊天；请在电脑的记忆审查页选择版本，再同步回来。';box.append(p);}}
 async function run(force=false){
  if(busy||!eligible())return;
  if(!force&&(!$('[data-enabled]').checked||Date.now()<retryAt||Date.now()-(await journal.setting('layerLastSync')||0)<Number($('[data-days]').value||7)*86400000))return;
  const pairingId=pair();if(!pairingId){if(force)status('先在电脑更新里配对电脑。');return;}
  busy=true;$('[data-now]').disabled=true;let detached=false,agentAttempted=false,agentSuffix='',booksAttempted=false,booksSuffix='';
  async function receiveBooks(){
   if(booksAttempted||!bookshelfSync||!eligible())return booksSuffix;booksAttempted=true;
   try{await bookshelfSync({pairingId,eligible});booksSuffix='分类书架已接回或保持最新，课程仅目录。';}
   catch{booksSuffix='分类书架未接回，原书架保留；可从书架单独重试。';}
   return booksSuffix;
  }
  async function receiveAgent(){
   if(agentAttempted||!agentSync||!eligible())return agentSuffix;
   agentAttempted=true;
   try{await agentSync({pairingId,eligible});agentSuffix='另接回Agent待核实缓存，尚未用于聊天。';}
   catch{agentSuffix='Agent待核实缓存未接回，原缓存保留。';}
   return agentSuffix;
  }
  try{
   status('正在连接电脑…');const info=await native.layerInfo({pairingId}),binding={serverId:info.serverId,scope_id:info.scope_id},old=await journal.setting('layerSyncBinding');
   if(info.reviewOn!=='desktop'||info.phoneRaw!=='gernze-phone-raw-v1')throw Error('请先更新电脑端，以支持第四层原文与集中审查。');
   if(old&&JSON.stringify(old)!==JSON.stringify(binding))throw Error('分层记忆已绑定另一台电脑，未自动混合。');
   const raw=await uploadPhoneRaw({journal,eligible,onProgress:({uploaded})=>status('已上传 '+uploaded+' 轮第四层原文…'),send:async request=>{const result=await native.rawExchange({pairingId,request});if(result.serverId!==binding.serverId)throw Error('电脑身份不一致。');return result;}});
   let researchRaw=null;
   if(info.phoneResearchRaw===RESEARCH_RAW_FORMAT&&journal.researchVersion===1&&(raw.complete||raw.researchDeferred)){
    researchRaw=await uploadPhoneResearch({journal,binding,eligible,onProgress:({uploaded})=>status('已上传 '+uploaded+' 轮带来源的研究原文…'),send:async request=>{const result=await native.rawExchange({pairingId,request});if(result.serverId!==binding.serverId)throw Error('电脑身份不一致。');return result;}});
   }
   const rawComplete=raw.complete||Boolean(raw.researchDeferred&&researchRaw?.complete);
   if(!eligible())throw Error('回到前台后继续同步。');
   const before=await layers.sync.export(binding.scope_id),researchFormat=info.researchCacheV2==='gernze-research-cache-v2'?'gernze-research-cache-v2':info.researchCache==='gernze-research-cache-v1'?'gernze-research-cache-v1':null,supportsResearch=Boolean(researchFormat);
   const result=await native.layerExchange({pairingId,request:{snapshot:before.packet,...(supportsResearch?{capabilities:[researchFormat]}:{})}});
   if(supportsResearch&&(!result.research||result.research.format!==researchFormat))throw Error('电脑未返回完整研究资料，未确认研究同步。');
   if(!eligible())throw Error('回到前台后继续接回。');beforeChange();detached=true;
   await layers.sync.apply(result,binding,before.rowsSignature);
   if(supportsResearch)await layers.research.apply(result.research,binding);
   await journal.setting('layerSyncBinding',binding);
   await receiveAgent();await receiveBooks();
   retryAt=rawComplete?0:Date.now()+15*60000;if(rawComplete)await journal.setting('layerLastSync',Date.now());
   status(rawComplete?'已同步第三层与第四层，并接回电脑审核结果。'+(researchRaw?.total?'研究原文与来源已独立归档，不作为用户事实。':'')+(supportsResearch?'另接回研究目录；课程正文仍留电脑。':'')+(result.conflicts.length?'有冲突，请在电脑处理。':''):raw.researchDeferred?(info.phoneResearchRaw===RESEARCH_RAW_FORMAT?'普通记忆已同步；研究对话原文尚未传完，保留在手机。':'普通记忆已同步；电脑尚不支持带来源研究原文，相关内容保留手机。'):'已传一批原文并同步记忆；还有原文待传，下次同步会从已确认的位置继续。');
   if(agentSuffix||booksSuffix)status($('[data-status]').textContent+agentSuffix+booksSuffix);
   window.dispatchEvent(new Event('hebao:memory-changed'));
  }catch(e){retryAt=Date.now()+15*60000;const extra=(await receiveAgent())+(await receiveBooks());status((e.message||'暂未连接电脑，原资料保留。')+(extra?' 普通记忆同步未完成。'+extra:''));}
  finally{if(detached)await afterChange();busy=false;if(alive)$('[data-now]').disabled=false;await showConflicts();}
 }
 $('[data-now]').onclick=()=>void run(true);const resume=()=>{if(!document.hidden)void run();},app=e=>{active=e.detail!==false;if(active)void run();};
 document.addEventListener('visibilitychange',resume);window.addEventListener('online',resume);window.addEventListener('hebao:app-active',app);
 const timer=setInterval(()=>void run(),60000);await showConflicts();void run();
 return {destroy(){alive=false;void Promise.resolve(bookshelfSync?.close?.()).catch(()=>{});void Promise.resolve(agentSync?.close?.()).catch(()=>{});clearInterval(timer);document.removeEventListener('visibilitychange',resume);window.removeEventListener('online',resume);window.removeEventListener('hebao:app-active',app);section.remove();}};
}
