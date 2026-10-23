// Local appearance choices; no account, API or memory access.
(()=>{
 const key='gernze.ui.preferences.v1',valid=value=>value==='window'||value==='study';
 let background='window';
 try{const saved=JSON.parse(localStorage.getItem(key)||'{}');if(valid(saved.background))background=saved.background;}catch{}
 document.documentElement.dataset.background=background;
 function mount(){
  const select=document.getElementById('backgroundChoice'),status=document.getElementById('backgroundStatus');
  if(select){select.value=background;select.addEventListener('change',()=>{
   if(!valid(select.value))return;background=select.value;document.documentElement.dataset.background=background;
   try{localStorage.setItem(key,JSON.stringify({background}));status.textContent='已切换，下次打开沿用这个背景。';}
   catch{status.textContent='背景已切换，本次未能保存选择。';}
  });}
  // Move existing controls without rebuilding them, including panels mounted later.
  const settings=document.getElementById('settings'),groups=new Map();
  const definitions=[
   ['appearance','外观与显示','背景、呼吸和画面清晰度'],
   ['chat','聊天连接','API、密钥和自动摘要'],
   ['memory','记忆与原文','分层记忆、审查和保存状态'],
   ['updates','电脑更新','配对、接收与安装'],
   ['interaction','人物互动','摇晃、休息和动作'],
   ['balance','DeepSeek 余额','手动刷新和自动检查'],
   ['sync','记忆互通','电脑与手机的同步设置']
  ];
  function tidySettings(){
   if(!settings)return;
   for(const panel of settings.querySelectorAll('.panel:not(details),.portrait-tools')){
    if(panel.dataset.settingsGrouped)continue;
    const key=panel.matches('#appearanceSettings,#qualityForm')?'appearance':panel.id==='chatConfigForm'?'chat':panel.id==='layeredMemorySettings'?'memory':panel.id==='hebaoUpdates'?'updates':panel.matches('#shakeControl,.portrait-tools')?'interaction':panel.querySelector('[data-refresh][type="button"]')&&panel.querySelector('[data-balance]')?'balance':panel.querySelector('#syncMemoryNow')?'sync':null;
    if(!key)continue;
    let group=groups.get(key);
    if(!group){
     const index=definitions.findIndex(d=>d[0]===key),[,title,hint]=definitions[index];
     group=document.createElement('details');group.className='settings-group';group.dataset.order=String(index);
     const summary=document.createElement('summary'),label=document.createElement('span'),small=document.createElement('small'),body=document.createElement('div');
     label.textContent=title;small.textContent=hint;summary.append(label,small);body.className='settings-group-body';group.append(summary,body);
     const next=[...settings.children].find(el=>el.matches('.settings-group')&&Number(el.dataset.order)>index)||settings.querySelector(':scope > .technical');
     settings.insertBefore(group,next);groups.set(key,group);
    }
    panel.dataset.settingsGrouped='true';group.lastElementChild.append(panel);
   }
  }
  tidySettings();
  const settingsObserver=new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches('.panel,.portrait-tools')||n.querySelector('.panel,.portrait-tools')))))tidySettings();});
  if(settings)settingsObserver.observe(settings,{childList:true,subtree:true});
  window.addEventListener('pagehide',()=>settingsObserver.disconnect(),{once:true});
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),motions=new Map();
  function stop(){for(const jelly of motions.values())jelly.stop();motions.clear();}
  document.querySelector('.bottom')?.addEventListener('click',event=>{
   const button=event.target.closest('.q-tab');if(!button||reduced.matches||document.hidden||!window.GernzeJelly)return;
   let jelly=motions.get(button);
   if(!jelly){jelly=window.GernzeJelly.create(button,{squash:[.05,.06],stretch:[.03,.04],down:1.5,lift:2.5,duration:420});motions.set(button,jelly);}
   jelly.pulse();
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  window.addEventListener('pagehide',stop);reduced.addEventListener('change',()=>{if(reduced.matches)stop();});
  window.addEventListener('hebao:app-active',event=>{if(event.detail!==true)stop();});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
