import {Capacitor,registerPlugin} from '@capacitor/core';

const bridge=registerPlugin('HebaoChat');
export function mountBalance(){
  const settings=document.getElementById('settings');if(!settings)return;
  const box=document.createElement('section');box.className='panel';
  box.innerHTML='<h3>DeepSeek 余额</h3><p data-balance role="status">点击刷新，读取当前账户余额。</p><button type="button" data-refresh>刷新余额</button><label><input type="checkbox" data-auto> 前台自动检查（15分钟一次）</label><p class="hint">仅支持 DeepSeek 官方接口。显示账户金额，不是剩余对话次数。</p>';
  settings.append(box);const button=box.querySelector('[data-refresh]'),status=box.querySelector('[data-balance]'),auto=box.querySelector('[data-auto]');
  if(!Capacitor.isNativePlatform()||Capacitor.getPlatform()!=='android'){button.disabled=true;auto.disabled=true;status.textContent='请在手机安装版查询余额。';return;}
  const key='hebao.balance.auto.v1';try{auto.checked=localStorage.getItem(key)!=='false';}catch{auto.checked=true;}
  let pending=false,generation=0,last=0,active=true,alive=true;
  const foreground=()=>alive&&active&&!document.hidden;
  async function refresh(manual=false){
    if(pending||!foreground()||(!manual&&(!auto.checked||Date.now()-last<900000)))return;
    const current=generation;pending=true;button.disabled=true;last=Date.now();
    try{
      const config=await bridge.getConfig();if(current!==generation)return;
      if(!config.balanceSupported){status.textContent=config.keyPresent?'当前接口不支持 DeepSeek 官方余额查询。':'请先保存聊天设置中的 API 密钥。';return;}
      status.textContent='正在查询余额…';const result=await bridge.getBalance();if(current!==generation||!foreground())return;
      status.textContent=result.balances.map(r=>`${r.currency} 余额 ${r.total}（赠送 ${r.granted}，充值 ${r.paid}）`).join('；')+(result.available?'':' · 当前账户不可用')+' · '+new Date().toLocaleTimeString('zh-CN');
    }catch(e){if(current===generation&&foreground())status.textContent=e.message||'查询未完成，请点击刷新重试。';}
    finally{pending=false;if(alive)button.disabled=false;}
  }
  button.onclick=()=>void refresh(true);
  auto.onchange=()=>{try{localStorage.setItem(key,String(auto.checked));}catch{}if(auto.checked)void refresh();};
  function invalidate(){generation++;last=0;status.textContent='配置已更新，请刷新余额。';void bridge.cancelBalance().catch(()=>{});}
  function resume(){if(!foreground()){generation++;void bridge.cancelBalance().catch(()=>{});}else void refresh();}
  const app=e=>{active=e.detail!==false;resume();};
  window.addEventListener('hebao:chat-config-changed',invalidate);window.addEventListener('hebao:app-active',app);document.addEventListener('visibilitychange',resume);
  const timer=setInterval(()=>void refresh(),900000);void refresh();
  window.addEventListener('pagehide',()=>{alive=false;generation++;clearInterval(timer);void bridge.cancelBalance().catch(()=>{});window.removeEventListener('hebao:chat-config-changed',invalidate);window.removeEventListener('hebao:app-active',app);document.removeEventListener('visibilitychange',resume);},{once:true});
}
