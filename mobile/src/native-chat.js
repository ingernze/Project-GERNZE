import {mountMemorySync} from './layer-sync.js';
import {Capacitor,registerPlugin} from '@capacitor/core';
import {createChatTransport} from './chat-core.mjs';
import {createChatJournal} from './chat-journal.mjs';
import {createMemorySource} from './memory-source.mjs';
import {createLayeredMemory} from './memory-layer-store.mjs';
import {mountLayerPanel} from './memory-layer-panel.mjs';

const native=Capacitor.isNativePlatform()&&Capacitor.getPlatform()==='android';
const bridge=registerPlugin('HebaoChat');
const journal=createChatJournal();
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
  form.innerHTML='<h3>聊天连接</h3><label><input id="chatEnabled" type="checkbox"> 启用手机独立聊天</label><label for="chatEndpoint">完整接口地址</label><input id="chatEndpoint" type="url" maxlength="2048" spellcheck="false" autocomplete="off" required><label for="chatModel">模型名称</label><input id="chatModel" maxlength="150" spellcheck="false" autocomplete="off" required><label for="chatKey">API 密钥（留空保留原密钥）</label><input id="chatKey" type="password" maxlength="4096" autocomplete="new-password"><button class="primary" type="submit">保存聊天设置</button><button id="chatDeleteKey" type="button">移除密钥</button><button id="chatNewSession" type="button">开始新对话</button><label><input id="chatAutoSummary" type="checkbox" checked> 自动整理较早对话（额外API用量）</label><label>摘要间隔（天，至少1天）<input id="chatSummaryDays" type="number" min="1" step="1" value="7"></label><p id="chatStatus" class="hint" role="status">正在读取手机聊天设置…</p><p class="hint">发送后才连接服务，电脑无需在线。对话原文保存在这台手机；第一层基础资料每轮加载，第四层保存原文，较早对话按摘要间隔压缩成第三层，审查统一在电脑，通过后接回第二层；摘要会额外调用一次当前API；同步按钮上传第三层与第四层原文，自动传输在前台连通时按你设置的间隔尝试。</p>';
  settings.append(form);const $=id=>form.querySelector('#'+id),status=message=>$('chatStatus').textContent=message;
  if(!native){form.querySelectorAll('input,button').forEach(el=>el.disabled=true);status('请在手机安装版填写密钥。浏览器可看页面，但这里没有连接真实聊天。');return;}
  let initialized=false,closed=false;
  function detach(){transport?.destroy();transport=null;controller?.setTransport(null);}
  async function refreshHistory(){
    if(!controller||closed)return;const id=controller.getSnapshot().id;
    const view=await journal.context(id);if(!closed)controller.setCompressedRanges({id,ranges:view.summaries||[]});
  }
  function apply(value){
    config=value;$('chatEnabled').checked=value.enabled;$('chatEndpoint').value=value.endpoint;$('chatModel').value=value.model;$('chatKey').value='';$('chatDeleteKey').disabled=!value.keyPresent;
    detach();
    if(!value.configured||!persona||!controller||!initialized||storageFailed)return;
    transport=createChatTransport({persona,journal,memory:layers.chat,onMemoryStatus:result=>{if(result.error)status('回复已保存，但第三层记忆未更新：'+result.error);else {status('较早对话已压缩为第三层记忆，等待审查。');window.dispatchEvent(new Event('hebao:working-memory-changed'));}},sessionId:()=>controller.getSnapshot().id,
      request:async({id,messages,purpose})=>(await bridge.request({id,messages,purpose:purpose||'chat'})).data,cancel:id=>bridge.cancel({id}),
      onSummaryStatus:message=>{status(message);void refreshHistory().catch(()=>{});},
      onPersistenceError:()=>{storageFailed=true;status('本轮回复尚未保存成功。请保留当前页面，不要清除应用数据。');}});
    // Wrap to associate a persistence failure with the returned response, without retrying a paid request.
    const current=transport;
    controller.setTransport({async send(payload){if(storageFailed)throw Error('会话保存异常，请先重开莉宝检查。');let result;try{result=await current.send(payload);}finally{await refreshHistory().catch(()=>{});}if(storageFailed)failedSaves.add(result.id);else window.dispatchEvent(new Event('hebao:chat-saved'));return result;}});
  }
  async function initialize(){
    if(initialized||closed)return;controller=window.HebaoDialogueController;if(!controller)return;
    try{
      const response=await fetch('chat-persona.txt',{cache:'no-store'});if(!response.ok)throw Error('人物设定文件缺失，请更新安装包。');
      persona=await response.text();if(!persona.trim()||persona.length>8000)throw Error('人物设定文件无效。');
      const foundation=await fetch('chat-core-memory.json',{cache:'no-store'});if(!foundation.ok)throw Error('核心基础资料缺失，请更新安装包。');
      layers=createLayeredMemory({core:await foundation.json()});
      const saved=await journal.load();if(closed)return;
      if(saved){const view=await journal.context(saved.id);if(closed)return;controller.restoreSession({id:saved.id,messages:saved.messages,compressed:view.summaries});}
      controller.setOpenMemory(async({container,onClose})=>{
        if(typeof window.HebaoMemoryBooks?.mount!=='function'){
          const p=document.createElement('p');p.className='dl-memory-placeholder';
          p.textContent='记忆书架外观待接入。已保存记忆可在设置里查看和纠正；真实聊天记录仍保存在本机。';container.append(p);return ()=>p.remove();
        }
        const handle=await window.HebaoMemoryBooks.mount({container,source:memorySource,timeZone:'Asia/Shanghai',onClose});booksHandle=handle;
        await handle?.open?.();return ()=>{if(booksHandle===handle)booksHandle=null;handle?.destroy?.();};
      });
      memoryPanel=mountLayerPanel({container:settings,layers,journal,getSessionId:()=>controller?.getSnapshot().id,beforeChange:detach,afterChange:async()=>{window.dispatchEvent(new Event('hebao:memory-changed'));try{await booksHandle?.refresh?.();}catch{}if(!closed&&config)apply(config);}});
      await memoryPanel.ready;if(closed)return;
      $('chatAutoSummary').checked=(await journal.setting('summaryEnabled'))!==false;
      $('chatSummaryDays').value=String(await journal.setting('summaryDays')??7);
      syncPanel=await mountMemorySync({container:settings,layers,journal,beforeChange:detach,afterChange:async()=>{await memoryPanel.refresh();try{await booksHandle?.refresh?.();}catch{}if(!closed&&config)apply(config);}});
      initialized=true;const value=await bridge.getConfig();if(closed)return;apply(value);
      status(value.configured?'聊天设置已就绪。只有你发送时才调用API。':'还没有启用聊天。填写密钥并保存后可开始。');
    }catch(error){storageFailed=true;status(error.message||'聊天初始化未完成，请重开莉宝。');}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(!initialized||closed||storageFailed){status('会话或人设尚未准备好，未启用聊天。');return;}
    const oldEndpoint=config?.endpoint;detach();const button=form.querySelector('[type="submit"]');button.disabled=true;
    try{
      const next=await bridge.configure({enabled:$('chatEnabled').checked,endpoint:$('chatEndpoint').value.trim(),model:$('chatModel').value.trim(),key:$('chatKey').value.trim()});
      if(oldEndpoint&&oldEndpoint!==next.endpoint){controller.newSession();try{await journal.save({...controller.getSnapshot(),updatedAt:new Date().toISOString()});}catch(e){storageFailed=true;throw e;}}
      apply(next);window.dispatchEvent(new Event('hebao:chat-config-changed'));status(next.configured?'聊天配置已保存，未发送测试消息。':'聊天已关闭，点击人物的本地回应仍可使用。');
    }catch(error){status(error.message||'配置未保存。');try{apply(await bridge.getConfig());}catch{detach();}}
    finally{$('chatKey').value='';button.disabled=false;}
  });
  $('chatSummaryDays').onchange=async()=>{const days=Number($('chatSummaryDays').value);try{await journal.setting('summaryDays',days);status('自动摘要间隔已设为'+days+'天。');}catch(e){status(e.message);$('chatSummaryDays').value=String(await journal.setting('summaryDays')??7);}};
  $('chatAutoSummary').onchange=async()=>{transport?.cancel();try{await journal.setting('summaryEnabled',$('chatAutoSummary').checked);status('自动摘要设置已保存。');}catch(e){status(e.message);$('chatAutoSummary').checked=(await journal.setting('summaryEnabled'))!==false;}};
  $('chatDeleteKey').onclick=async()=>{detach();try{apply(await bridge.deleteKey());window.dispatchEvent(new Event('hebao:chat-config-changed'));status('密钥已移除，聊天已关闭。原聊天记录保留。');}catch(e){status(e.message||'密钥尚未移除。');}};
  $('chatNewSession').onclick=async()=>{if(!initialized||storageFailed)return;transport?.cancel();controller.newSession();try{await journal.save({...controller.getSnapshot(),updatedAt:new Date().toISOString()});status('已开始新对话；以前的记录仍保存在手机。');}catch(e){storageFailed=true;detach();status(e.message);}};
  const stop=()=>transport?.cancel();
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  window.addEventListener('hebao:app-active',e=>{if(e.detail===false)stop();});
  window.addEventListener('hebao:dialogue-ready',initialize,{once:true});
  window.addEventListener('pagehide',()=>{closed=true;detach();memoryPanel?.destroy();syncPanel?.destroy();void layers?.close();void journal.close();},{once:true});
  if(window.HebaoDialogueController)void initialize();
}
