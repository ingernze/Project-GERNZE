import {describeChatCapabilities} from './chat-capabilities.mjs';
import {createBookshelfUse} from './bookshelf-use.mjs';
import {mountWeb} from './native-web.js';
import {createKnowledgeHost} from './knowledge-native.mjs';
import {createBookshelfSync} from './bookshelf-native.mjs';
import {mountBookshelf} from './bookshelf-cache.mjs';
import {createAgentSync} from './agent-native.mjs';
import {createResearchUse} from './research-use.mjs';
import {mountResearchCache} from './research-cache.mjs';
import {mountMemorySync} from './layer-sync.js';
import {Capacitor,registerPlugin} from '@capacitor/core';
import {createChatTransport,createNativeChatRequest,DEEPSEEK_CONTEXT_BYTES} from './chat-core.mjs';
import {createChatJournal} from './chat-journal.mjs';
import {createMemorySource} from './memory-source.mjs';
import {createLayeredMemory} from './memory-layer-store.mjs';
import {mountLayerPanel} from './memory-layer-panel.mjs';

const native=Capacitor.isNativePlatform()&&Capacitor.getPlatform()==='android';
const bridge=registerPlugin('HebaoChat');
const journal=createChatJournal();
const bookshelfSync=createBookshelfSync();
const memorySource=createMemorySource(journal,{layered:()=>layers?.chat.archive()});
let memoryPanel=null,booksHandle=null,syncPanel=null;
// Only a read interface is shared with branch 2; no raw credentials or write access.
window.HebaoMemorySource=memorySource;
let controller=null,transport=null,config=null,persona='',mounted=false,storageFailed=false,layers=null;
const failedSaves=new Set();
// The externally supplied controller consumes these options at its first mount.
window.HebaoDialogueOptions={onTurnComplete(detail){
  if(detail.mode==='live'&&failedSaves.delete(detail.id))throw Error('本轮回复尚未可靠保存。');
}};
export function mountChat(){
  if(mounted)return;const settings=document.getElementById('settings');if(!settings)return;mounted=true;
  const form=document.createElement('form');form.className='panel';form.id='chatConfigForm';
  form.innerHTML='<h3>聊天连接</h3><p id="chatProfileCount" class="hint"></p><label for="chatProfiles">当前使用的连接</label><select id="chatProfiles"></select><div class="chat-profile-actions"><button id="chatAddProfile" type="button">新增密钥</button><button id="chatCancelProfile" type="button" hidden>取消新增</button></div><label for="chatProfileName">连接名称</label><input id="chatProfileName" maxlength="48" autocomplete="off" required><label><input id="chatEnabled" type="checkbox"> 启用手机独立聊天</label><label for="chatEndpoint">完整接口地址</label><input id="chatEndpoint" type="url" maxlength="2048" spellcheck="false" autocomplete="off" required><label for="chatModel">模型名称</label><input id="chatModel" maxlength="150" spellcheck="false" autocomplete="off" required><label for="chatKey">API 密钥</label><input id="chatKey" type="password" maxlength="4096" autocomplete="new-password"><button class="primary" type="submit">保存聊天设置</button><button id="chatDeleteKey" type="button">移除密钥</button><button id="chatNewSession" type="button">开始新对话</button><label><input id="chatAutoSummary" type="checkbox" checked> 自动整理较早对话（到期或上下文吃紧，额外API用量）</label><label>摘要间隔（天，至少1天）<input id="chatSummaryDays" type="number" min="1" step="1" value="7"></label><p id="chatStatus" class="hint" role="status">正在读取手机聊天设置…</p><p class="hint">发送后才连接服务，电脑无需在线。对话原文保存在这台手机；第一层基础资料每轮加载，第四层保存原文，较早对话到期或接近上下文上限时整理成第三层，审查统一在电脑，通过后接回第二层；每次回复保存后最多额外调用2次摘要API，每次输入最多16000字节、输出最多500 token；新发送优先停止整理；同步按钮上传第三层与第四层原文，自动传输在前台连通时按你设置的间隔尝试。</p>';
  settings.append(form);const $=id=>form.querySelector('#'+id),status=message=>$('chatStatus').textContent=message;
  if(!native){form.querySelectorAll('input,button,select').forEach(el=>el.disabled=true);status('请在手机安装版填写密钥。浏览器可看页面，但这里没有连接真实聊天。');return;}
  let initialized=false,closed=false,selectionNotice=null,selectionText=null,webPanel=null;
  let creating=false,configBusy=false;
  const submit=form.querySelector('[type="submit"]');
  const knowledgeHost=createKnowledgeHost();let closeBooks=null,entryController=null;
  const shelf=createBookshelfUse({cache:bookshelfSync.cache,binding:()=>{try{const p=JSON.parse(localStorage.getItem('hebao.updates.v1')||'{}').pair;return p?.pairingId&&p?.fingerprint?JSON.stringify([p.pairingId,p.fingerprint]):'';}catch{return '';}}});
  const shelfChanged=()=>shelf.synced(),pairChanged=()=>{shelf.invalidate();transport?.cancel();};
  window.addEventListener('hebao:bookshelf-changed',shelfChanged);window.addEventListener('hebao:pairing-changed',pairChanged);
  const research=createResearchUse({cache:journal.researchCache,onChange:source=>{
    if(selectionNotice){selectionNotice.hidden=!source;selectionText.textContent=source?'已选研究摘要，仅用于下一次提问':'';}
  }});
  async function selectResearch(ref){
    if(closed||!initialized||!controller||controller.getSnapshot().pending)throw Error('请等当前回复结束后再选择研究资料。');
    await research.select({...ref,sessionId:controller.getSnapshot().id});
  }
  function detach(){webPanel?.clear();research.clear();transport?.destroy();transport=null;controller?.setTransport(null);}
  async function refreshHistory(){
    if(!controller||closed)return;const id=controller.getSnapshot().id;
    const view=await journal.context(id);if(!closed)controller.setCompressedRanges({id,ranges:view.summaries||[]});
  }
  function profileControls(){
    const ready=initialized&&!!config&&!storageFailed&&!configBusy;
    $('chatProfiles').disabled=!ready||creating;
    $('chatAddProfile').disabled=!ready||creating||config.profiles.length>=config.profileLimit;
    $('chatCancelProfile').hidden=!creating;$('chatCancelProfile').disabled=!ready;
    $('chatDeleteKey').disabled=!ready||creating||!config.keyPresent;
    submit.disabled=!ready;
  }
  function showProfile(value){
    creating=false;
    $('chatProfiles').replaceChildren(...value.profiles.map(profile=>{
      const option=document.createElement('option');option.value=profile.id;
      option.textContent=profile.name+(profile.keyPresent?' · 已保存密钥':' · 未设置密钥');return option;
    }));
    $('chatProfiles').value=value.activeId;
    $('chatProfileCount').textContent='已保存 '+value.savedCount+' 组密钥';
    $('chatProfileName').value=value.profiles.find(p=>p.id===value.activeId)?.name||'';
    $('chatEnabled').checked=value.enabled;$('chatEndpoint').value=value.endpoint;$('chatModel').value=value.model;
    $('chatKey').value='';$('chatKey').required=false;
    $('chatKey').previousElementSibling.textContent=value.keyPresent?'API 密钥（已保存，留空保留）':'API 密钥（未设置）';
    submit.textContent='保存聊天设置';profileControls();
  }
  profileControls();
  function apply(value){
    config=value;showProfile(value);
    detach();
    if(!value.configured||!persona||!controller||!initialized||storageFailed)return;
    transport=createChatTransport({persona,journal,research,shelf,...(value.webToolSupported?{allowAutoWeb:true,budget:DEEPSEEK_CONTEXT_BYTES,timeoutMs:155000}:{}),onShelfStatus:value=>{if(value==='used')status('本轮按话题参考了已缓存的普通书架片段；来源版本随回答保存。');},web:webPanel?.use,onResearchStatus:value=>{if(value==='used')status('本轮已参考所选研究摘要，原文与来源保存在书架；下次提问不再带入。');else if(value.startsWith('budget_omitted'))status('本轮空间不足，未读取或带入研究摘要；如仍需要，请重新选择。');},memory:layers.chat,onMemoryStatus:result=>{if(result.error)status('回复已保存，但第三层记忆未更新：'+result.error);else {status('较早对话已压缩为第三层记忆，等待审查。');window.dispatchEvent(new Event('hebao:working-memory-changed'));}},sessionId:()=>controller.getSnapshot().id,
      describeCapabilities:request=>describeChatCapabilities({...request,shelf,web:webPanel?.use}),
      request:createNativeChatRequest(bridge),cancel:id=>bridge.cancel({id}),
      onSummaryStatus:message=>{status(message);void refreshHistory().catch(()=>{});},
      onPersistenceError:()=>{storageFailed=true;status('本轮回复尚未保存成功。请保留当前页面，不要清除应用数据。');}});
    // Wrap to associate a persistence failure with the returned response, without retrying a paid request.
    const current=transport;
    controller.setTransport({async send(payload){if(storageFailed)throw Error('会话保存异常，请先重开莉宝检查。');let result;try{result=await current.send(payload);}finally{await refreshHistory().catch(()=>{});}if(storageFailed)failedSaves.add(result.id);else window.dispatchEvent(new Event('hebao:chat-saved'));return result;}});
  }
  function installBookEntry(){
    if(entryController===controller)return;entryController=controller;
    controller.setOpenMemory(({container,onClose})=>{
      closeBooks?.();
      container.style.display='flex';container.style.flexDirection='column';
      const tabs=document.createElement('div'),bookTab=document.createElement('button'),researchTab=document.createElement('button'),shelfTab=document.createElement('button'),knowledgeTab=document.createElement('button');
      tabs.className='dl-memory-tabs';
      const tabButtons=[bookTab,researchTab,shelfTab,knowledgeTab];
      for(const button of tabButtons)button.type='button';
      bookTab.textContent='聊天原文';researchTab.textContent='研究资料';shelfTab.textContent='分类资料';knowledgeTab.textContent='课程资料';tabs.append(...tabButtons);
      const bookContainer=document.createElement('div'),researchContainer=document.createElement('div'),shelfContainer=document.createElement('div'),knowledgeContainer=document.createElement('div');
      bookContainer.dataset.memoryLayout='mobile';
      const boxes=[bookContainer,researchContainer,shelfContainer,knowledgeContainer];
      for(const box of boxes){box.style.flex='1';box.style.minHeight='0';box.style.overflow='auto';}
      container.append(tabs,...boxes);
      let disposed=false,handle=null,shelfPanel=null,researchPanel=null,knowledgeView=null,selectedTab=0,bookView={view:'shelf'};
      const rememberBookView=event=>{bookView=event.detail;if(selectedTab!==0)event.stopPropagation();};
      bookContainer.addEventListener('memory-books:view',rememberBookView);
      const cleanup=()=>{if(disposed)return;disposed=true;bookContainer.removeEventListener('memory-books:view',rememberBookView);knowledgeView?.destroy();knowledgeView=null;researchPanel?.destroy();shelfPanel?.destroy();handle?.destroy?.();if(booksHandle===handle)booksHandle=null;for(const b of tabButtons)b.onclick=null;tabs.remove();for(const box of boxes)box.remove();if(closeBooks===cleanup)closeBooks=null;};
      closeBooks=cleanup;
      const choose=index=>{
        if(disposed)return;selectedTab=index;
        knowledgeView?.destroy();knowledgeView=null;
        for(const [i,box] of boxes.entries()){box.hidden=i!==index;tabButtons[i].setAttribute('aria-pressed',String(i===index));}
        container.dispatchEvent(new CustomEvent('memory-books:view',{bubbles:true,detail:index===0?bookView:{view:'shelf'}}));
        if(index===3)knowledgeView=knowledgeHost.mount(knowledgeContainer);
      };
      for(const [i,b] of tabButtons.entries())b.onclick=()=>choose(i);choose(0);
      // Legacy tabs keep their implementations. Their startup must not block
      // the local course tab or delay registration of the shelf cleanup.
      void (async()=>{
        try{
          shelfPanel=mountBookshelf({container:shelfContainer,cache:bookshelfSync.cache,sync:bookshelfSync});await shelfPanel.ready;
          if(disposed)return;
          if(typeof window.HebaoMemoryBooks?.mount==='function'){
            const opened=await window.HebaoMemoryBooks.mount({container:bookContainer,source:memorySource,timeZone:'Asia/Shanghai',onClose});
            if(disposed){opened?.destroy?.();return;}handle=opened;booksHandle=handle;await handle?.open?.();if(disposed)return;
          }else{const p=document.createElement('p');p.className='dl-memory-placeholder';p.textContent='记忆书架外观待接入。真实聊天记录仍保存在本机。';bookContainer.append(p);}
          researchPanel=mountResearchCache({container:researchContainer,cache:journal.researchCache,onSelect:async ref=>{await selectResearch(ref);onClose();}});
          const section=researchContainer.querySelector('section');section.style.cssText='background:#f6f1e6;color:#334f60;border:1px solid #bdc9c9;border-radius:14px;padding:16px;margin:0 6px 12px';
          const hint=section.querySelector('.hint');if(hint)hint.style.color='#657b86';await researchPanel.ready;
        }catch{if(!disposed){const p=document.createElement('p');p.className='hint';p.textContent='旧资料页暂未读取，课程资料仍可单独打开。';bookContainer.append(p);}}
      })();
      return cleanup;
    });
  }
  async function initialize(){
    if(initialized||closed)return;controller=window.HebaoDialogueController;if(!controller)return;
    installBookEntry();
    try{
      const response=await fetch('chat-persona.txt',{cache:'no-store'});if(!response.ok)throw Error('人物设定文件缺失，请更新安装包。');
      persona=await response.text();if(!persona.trim()||persona.length>8000)throw Error('人物设定文件无效。');
      const foundation=await fetch('chat-core-memory.json',{cache:'no-store'});if(!foundation.ok)throw Error('核心基础资料缺失，请更新安装包。');
      layers=createLayeredMemory({core:await foundation.json(),researchCache:journal.researchCache});
      const saved=await journal.load();if(closed)return;
      if(saved){const view=await journal.context(saved.id);if(closed)return;controller.restoreSession({id:saved.id,messages:saved.messages,compressed:view.summaries,shelfRanges:saved.shelfRanges});}
      const composer=document.querySelector('.hebao-dialogue .dl-compose');
      if(!composer)throw Error('对话输入区尚未准备好。');
      webPanel=mountWeb({settings,composer,sessionId:()=>controller.getSnapshot().id,supportsAuto:()=>config?.webToolSupported===true,onStop:()=>transport?.cancel()});
      selectionNotice=document.createElement('div');selectionNotice.className='hint';selectionNotice.hidden=true;selectionNotice.setAttribute('role','status');
      selectionText=document.createElement('span');const remove=document.createElement('button');remove.type='button';remove.textContent='取消取用';remove.onclick=()=>research.clear();selectionNotice.append(selectionText,remove);composer.prepend(selectionNotice);
      memoryPanel=mountLayerPanel({container:settings,layers,journal,onResearchSelect:selectResearch,getSessionId:()=>controller?.getSnapshot().id,beforeChange:detach,afterChange:async()=>{window.dispatchEvent(new Event('hebao:memory-changed'));try{await booksHandle?.refresh?.();}catch{}if(!closed&&config)apply(config);}});
      await memoryPanel.ready;if(closed)return;
      $('chatAutoSummary').checked=(await journal.setting('summaryEnabled'))!==false;
      $('chatSummaryDays').value=String(await journal.setting('summaryDays')??7);
      syncPanel=await mountMemorySync({bookshelfSync,agentSync:createAgentSync(),container:settings,layers,journal,beforeChange:detach,afterChange:async()=>{await memoryPanel.refresh();try{await booksHandle?.refresh?.();}catch{}if(!closed&&config)apply(config);}});
      initialized=true;const value=await bridge.getConfig();if(closed)return;apply(value);
      window.dispatchEvent(new Event('hebao:chat-config-changed'));
      status(value.configured?'聊天设置已就绪。只有你发送时才调用API。':'还没有启用聊天。填写密钥并保存后可开始。');
    }catch(error){storageFailed=true;status(error.message||'聊天初始化未完成，请重开莉宝。');}
  }
  async function changeConfig(change,message,{replaceKey=false}={}){
    if(!initialized||closed||storageFailed||configBusy)return;
    configBusy=true;profileControls();detach();
    const previous=config;
    try{
      const next=await change();if(closed)return;
      if(previous&&(previous.activeId!==next.activeId||previous.endpoint!==next.endpoint||(replaceKey&&previous.keyPresent))){
        controller.newSession();
        try{await journal.save({...controller.getSnapshot(),updatedAt:new Date().toISOString()});}catch(e){storageFailed=true;throw e;}
      }
      apply(next);window.dispatchEvent(new Event('hebao:chat-config-changed'));status(message(next));
    }catch(error){
      if(closed)return;
      status(error.message||'聊天连接未更新。');
      try{const value=await bridge.getConfig();if(!closed)apply(value);}catch{detach();}
    }finally{configBusy=false;$('chatKey').value='';profileControls();}
  }
  $('chatAddProfile').onclick=()=>{
    if(configBusy||!config||storageFailed)return;
    creating=true;
    $('chatProfileName').value='连接 '+(config.profiles.length+1);
    $('chatEnabled').checked=true;$('chatKey').value='';$('chatKey').required=true;
    $('chatKey').previousElementSibling.textContent='API 密钥（填写新密钥）';
    submit.textContent='保存并使用';profileControls();
    status('新连接保存后才会生效。');$('chatProfileName').focus();
  };
  $('chatCancelProfile').onclick=()=>{showProfile(config);status('已取消新增，仍使用原连接。');};
  $('chatProfiles').onchange=()=>{
    const profileId=$('chatProfiles').value;
    void changeConfig(()=>bridge.switchProfile({profileId}),next=>next.configured?'已切换连接并开始新对话。原聊天保留。':'已切换连接，请设置密钥并启用聊天。');
  };
  form.addEventListener('submit',event=>{
    event.preventDefault();
    const value={enabled:$('chatEnabled').checked,endpoint:$('chatEndpoint').value.trim(),model:$('chatModel').value.trim(),key:$('chatKey').value.trim(),profileName:$('chatProfileName').value.trim(),createProfile:creating};
    void changeConfig(()=>bridge.configure(value),next=>next.configured?'聊天配置已保存，发送消息时才调用。':'聊天连接已保存，目前未启用。',{replaceKey:Boolean(value.key)});
  });
  $('chatSummaryDays').onchange=async()=>{const days=Number($('chatSummaryDays').value);try{await journal.setting('summaryDays',days);status('自动摘要间隔已设为'+days+'天。');}catch(e){status(e.message);$('chatSummaryDays').value=String(await journal.setting('summaryDays')??7);}};
  $('chatAutoSummary').onchange=async()=>{transport?.cancel();try{await journal.setting('summaryEnabled',$('chatAutoSummary').checked);status('自动摘要设置已保存。');}catch(e){status(e.message);$('chatAutoSummary').checked=(await journal.setting('summaryEnabled'))!==false;}};
  $('chatDeleteKey').onclick=()=>void changeConfig(()=>bridge.deleteKey(),()=> '当前连接的密钥已移除。原聊天记录保留。');
  $('chatNewSession').onclick=async()=>{if(!initialized||storageFailed||configBusy)return;webPanel?.clear();transport?.cancel();controller.newSession();try{await journal.save({...controller.getSnapshot(),updatedAt:new Date().toISOString()});status('已开始新对话；以前的记录仍保存在手机。');}catch(e){storageFailed=true;detach();status(e.message);}};
  const stop=()=>{webPanel?.clear();research.clear();transport?.cancel();};
  window.addEventListener('hebao:page-change',e=>{if(e.detail?.page!=='dialogue'){stop();closeBooks?.();controller?.closeMemory?.();}});
  window.addEventListener('hebao:memory-changed',()=>research.clear());
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  window.addEventListener('hebao:app-active',e=>{if(e.detail===false)stop();});
  window.addEventListener('hebao:dialogue-ready',initialize,{once:true});
  window.addEventListener('pagehide',()=>{closed=true;window.removeEventListener('hebao:bookshelf-changed',shelfChanged);window.removeEventListener('hebao:pairing-changed',pairChanged);webPanel?.destroy();closeBooks?.();void knowledgeHost.destroy();detach();selectionNotice?.remove();memoryPanel?.destroy();syncPanel?.destroy();void layers?.close();void journal.close();},{once:true});
  if(window.HebaoDialogueController)void initialize();
}
