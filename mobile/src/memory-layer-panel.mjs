import {summaryReadiness} from './summary-policy.mjs';
export function mountLayerPanel({container,layers,journal=null,getSessionId=()=>null}={}){
 const root=document.createElement('section');root.className='panel';root.id='layeredMemorySettings';
 root.innerHTML='<h3>记忆与聊天原文</h3><p class="hint">手机保存第四层原文，聊天时按设定周期整理成第三层。通过“同步到电脑”上传，由电脑AI按设定间隔自动对照原文审查，无需在手机逐条批准；通过后的第二层再同步回来。电脑工作台未运行或API未配置时保留待审。</p><p data-state role="status"></p><button type="button" data-refresh>刷新保存状态</button><details><summary>第一层 · 核心与基础资料（只读）</summary><p>随个人版本提供，回答时加载；聊天API不能修改。</p><div data-core></div></details><details><summary>第二层 · 电脑已审核记忆（只读）</summary><div data-approved></div></details><details><summary>第三层 · 压缩记忆与待审查</summary><p>审查、纠正、排除和冲突选择统一在电脑进行。手机不接收审查JSON，也不能直接批准或撤回第二层。</p><p data-summary-state></p><div data-working></div></details><details><summary>第四层 · 聊天原文</summary><p>压缩不删除原文；同步上传纯文字、时间和来源编号，不传图片、录音、API密钥或第一层。</p><p data-raw-state></p><div data-raw-preview></div></details><details data-legacy-box hidden><summary>本机旧审查记录（只读保留）</summary><p>以前在手机审查的本机版本保留在这里；当前聊天使用电脑接回的第二层，不自动把旧记录当作新审批。</p><div data-legacy></div></details>';
 container.append(root);const $=s=>root.querySelector(s);let closed=false;
 function show(box,entries,empty){box.replaceChildren();if(!entries.length){const p=document.createElement('p');p.textContent=empty;box.append(p);return;}for(const e of entries){const row=document.createElement('article'),title=document.createElement('strong'),body=document.createElement('p');title.textContent=e.key;body.textContent=e.deleted?'已撤回':e.body;row.append(title,body);if(Number.isSafeInteger(e.sourceStart)){const p=document.createElement('small');p.textContent='来源：第四层第'+(e.sourceStart/2+1)+'—'+e.sourceEnd/2+'轮';row.append(p);}box.append(row);}}
 async function refresh(){
  const [view,sessions,summary]=await Promise.all([layers.review.list(),journal?journal.list():[],journal?journal.context(getSessionId()):null]);if(closed)return;
  show($('[data-core]'),view.core.entries,'此构建没有个人基础资料；人物设定仍会加载。');show($('[data-approved]'),view.approved.filter(e=>!e.deleted&&!e.syncConflict),'尚未接回电脑审核通过的记忆。');show($('[data-working]'),view.pending,'暂无待审摘要；第四层原文仍独立保存。');
  const stored=sessions.filter(s=>s.messages.length),turns=stored.reduce((n,s)=>n+s.messages.length/2,0),last=stored.sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt))[0];
  $('[data-state]').textContent='第一层 '+view.core.entries.length+' 条；电脑已审 '+view.approved.filter(e=>!e.deleted&&!e.syncConflict).length+' 条；第三层待审 '+view.pending.length+' 条；第四层 '+turns+' 轮原文。';
  $('[data-summary-state]').textContent=summary?summaryReadiness(summary):'此入口未提供压缩状态。';$('[data-raw-state]').textContent=stored.length+' 段会话，共 '+turns+' 轮原文。可手动同步到电脑，或按设置的间隔在前台连通时自动传输。';
  const preview=$('[data-raw-preview]');preview.replaceChildren();if(last)for(const m of last.messages.slice(-6)){const p=document.createElement('p');p.style.whiteSpace='pre-wrap';p.textContent=(m.role==='user'?'你：':'莉宝：')+m.content.slice(0,400)+(m.content.length>400?'…':'');preview.append(p);}
  $('[data-legacy-box]').hidden=!view.legacyApproved?.length;show($('[data-legacy]'),view.legacyApproved||[],'没有旧本机审批。');
 }
 const changed=()=>{if(!closed)void refresh().catch(e=>$('[data-state]').textContent=e.message);};$('[data-refresh]').onclick=changed;
 for(const name of ['hebao:working-memory-changed','hebao:chat-saved','hebao:memory-changed'])window.addEventListener(name,changed);
 const page=e=>{if(e.detail?.page==='settings')changed();};window.addEventListener('hebao:page-change',page);const ready=refresh().catch(e=>$('[data-state]').textContent=e.message);
 return {ready,refresh,destroy(){closed=true;for(const name of ['hebao:working-memory-changed','hebao:chat-saved','hebao:memory-changed'])window.removeEventListener(name,changed);window.removeEventListener('hebao:page-change',page);root.remove();}};
}
