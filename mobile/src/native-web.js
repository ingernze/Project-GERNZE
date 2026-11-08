import {registerPlugin} from '@capacitor/core';
import {createWebUse} from './web-use.mjs';

// Native search selection. Credentials are resolved only inside Android.
export function mountWeb({settings,composer,sessionId,supportsAuto=()=>false,onStop=()=>{}}){
 const bridge=registerPlugin('LibaoWeb');
 const form=document.createElement('form');form.className='panel';form.id='webConfigForm';
 form.innerHTML='<h3>公开网页搜索</h3><label for="webProvider">搜索方式</label><select id="webProvider"><option value="auto">跟随聊天连接（默认）</option><option value="none">关闭关键词搜索</option><option value="tavily">Tavily Basic</option><option value="brave">Brave Search</option></select><div id="webExternalSettings" hidden><label for="webSearchKey">该服务的搜索密钥（留空保留已有密钥）</label><input id="webSearchKey" type="password" maxlength="512" autocomplete="new-password"><button id="webDeleteKey" type="button">移除该服务密钥</button></div><button type="submit">保存搜索方式</button><p class="hint" role="status">正在读取搜索配置…</p><p class="hint">支持工具调用的聊天连接默认可以在回答需要时自动搜索，并列出来源。官方 DeepSeek 搜索沿用聊天密钥，按服务商规则计费。电脑无需在线。</p>';
 settings.append(form);
 const note=document.createElement('p');note.className='dl-web-status';note.setAttribute('role','status');note.hidden=true;composer.prepend(note);
 const show=state=>{
  note.hidden=state.status!=='pending';
  note.textContent=note.hidden?'':state.message;
 };
 const use=createWebUse({bridge,sessionId,onState:show});
 const status=form.querySelector('[role=status]'),input=form.querySelector('input');
 let disposed=false;
 const provider=form.querySelector('#webProvider');
 const external=value=>['tavily','brave'].includes(value);
 const advanced=form.querySelector('#webExternalSettings'),remove=form.querySelector('#webDeleteKey');
 let savedSelection='auto',savedKey=false,readVersion=0;
 function controls(){advanced.hidden=!external(provider.value);input.disabled=advanced.hidden;remove.disabled=provider.value!==savedSelection||!savedKey;}
 const config=async({keepChoice=false}={})=>{
  const ticket=++readVersion;
  try{
   const c=await bridge.getConfig();if(disposed||ticket!==readVersion)return;
   const selection=c.selection??c.provider;
   savedSelection=['auto','none','tavily','brave'].includes(selection)?selection:'auto';savedKey=c.keyPresent;
   if(!keepChoice)provider.value=savedSelection;
   controls();
   if(provider.value!==savedSelection){status.textContent='搜索方式尚未保存。';return;}
   status.textContent=c.provider==='deepseek'&&c.keyPresent?(supportsAuto()?'已跟随当前官方 DeepSeek 聊天连接，莉宝可按需要自动搜索。':'已跟随当前官方 DeepSeek 聊天连接，可接收明确的搜索请求。'):
    savedSelection==='none'?'关键词搜索已关闭，公开网址仍可直接读取。':
    external(savedSelection)?(c.keyPresent?'该搜索服务已配置。':'该搜索服务还没保存密钥。'):
    '当前聊天连接未提供关键词搜索。此方式支持官方 DeepSeek 连接。';
  }catch{if(!disposed&&ticket===readVersion)status.textContent='搜索配置暂时未能读取。';}
 };
 provider.onchange=()=>{input.value='';controls();status.textContent=provider.value===savedSelection?'仍使用已保存方式。':'搜索方式尚未保存。';};
 controls();
 const connectionChanged=()=>void config({keepChoice:true});
 window.addEventListener('hebao:chat-config-changed',connectionChanged);
 form.onsubmit=async e=>{e.preventDefault();const key=external(provider.value)?input.value:'';input.value='';onStop();use.cancel();try{await bridge.configure({key,provider:provider.value});await config();}catch{status.textContent=external(provider.value)?'搜索设置未保存，请检查该服务的密钥。':'搜索方式未能保存。';}};
 form.querySelector('#webDeleteKey').onclick=async()=>{input.value='';onStop();use.cancel();try{await bridge.deleteKey();await config();}catch{status.textContent='搜索密钥尚未移除。';}};
 void config();
 return Object.freeze({use,clear(){use.cancel();show({status:'idle',message:'本轮联网已停止或会话已切换。',sources:[]});},destroy(){disposed=true;window.removeEventListener('hebao:chat-config-changed',connectionChanged);use.destroy();form.remove();note.remove();}});
}
