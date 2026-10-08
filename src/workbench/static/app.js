(function () {
"use strict";
const {h,icon}=window.HebaoUI;
const scope=new window.HebaoRuntime.Scope();
const frame=new window.HebaoFrame(document.getElementById('app'));scope.own(()=>frame.dispose());
const registry=new window.HebaoRuntime.Registry();
for(const unregister of window.HebaoModules.register(registry))scope.own(unregister);
const preview=document.documentElement.dataset.preview==='true'||location.protocol==='file:';
// Per-tab, per-origin capability survives reload; no account/API credential.
const suppliedToken=new URLSearchParams(location.hash.slice(1)).get('session');
let token=suppliedToken;
try {
  if(suppliedToken)sessionStorage.setItem('hebao.workbench.session',suppliedToken);
  else token=sessionStorage.getItem('hebao.workbench.session');
} catch(error) { /* Restricted storage: the supplied fragment still works this visit. */ }
if(!preview)history.replaceState(null,'',location.pathname);
const empty={lessons:[],due_reviews:[],progress:{submission_count:0,learning_days:0,usage_span_days:0,first_used_at:null,last_submission_at:null}};
let state=empty; const drafts={};let toastTimer=null; let disposed=false;
const transport=async(command,params={},signal)=> {
  if(preview){
    if(command==='state.summary')return empty;
    if(['study.history','memory.list','reminder.list'].includes(command))return [];
    throw new Error('请通过 run_workbench.cmd 启动本地工作台，连接学习记录。');
  }
  if(!token)throw new Error('此页面没有本地会话，请从启动器重新打开。');
  const response=await fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({command,params}),signal});
  const result=await response.json();if(!response.ok)throw new Error(result.error || '本地服务暂时没有响应。');return result.result;
};
window.HebaoWorkbenchVoice={claimEntrance:()=>{
  if(disposed)return Promise.resolve({play:false});
  if(preview)return Promise.resolve({play:true});
  return transport('arrival.claim');
},notify:(event)=>{
  if(preview||disposed||!['workbench_open','workbench_stop'].includes(event))return Promise.resolve();
  return transport('voice.'+event).catch(()=>{});
}};
scope.own(()=>delete window.HebaoWorkbenchVoice);
function notify(text) {
  let toast=frame.overlay.querySelector('.toast');if(!toast){toast=h('div','toast');toast.role='status';frame.overlay.append(toast);}
  toast.textContent=text;clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.remove(),4200);
}
scope.own(()=>clearTimeout(toastTimer));
const details=(title,text)=>{
  const panel=h('div','details-panel');const head=h('div','details-heading');head.append(h('h2','',title));
  const close=h('button','icon-button');close.title='关闭详情';close.setAttribute('aria-label','关闭详情');close.append(icon('cross',16));
  // Node-owned listener disappears with the detail surface.
  close.addEventListener('click',()=>frame.closeDetails());head.append(close);panel.append(head,h('div','detail-text',text));frame.details(panel);
};
const header=h('header','workbench-header');const crumb=h('span','breadcrumb','工作台 / 首页');
const status=h('span','top-status');status.append(h('span','status-dot'),h('span','',preview?'独立预览':'本地工作台'));
header.append(crumb,status);const pageSlot=h('div','page-slot');frame.main.append(header,pageSlot);
const refresh=async()=>{state=await transport('state.summary');if(!disposed)renderRecent();return state;};
const host=new window.HebaoRuntime.PanelHost(registry,pageSlot,{registry,transport,preview,drafts,refresh,state:()=>state,notify,details,closeDetails:()=>frame.closeDetails(),navigate:(id,payload)=>navigate(id,payload)},error=>console.error(error));
scope.own(()=>host.dispose());
let navigationButtons=[];let recent;
let activeId=null, learningExpanded=true;
let sidebarScope=null, learningButton=null, learningTree=null, recentArea=null;
scope.own(()=>sidebarScope?.dispose());
function renderRecent() {
  if(!recent)return;recent.replaceChildren(h('div','recent-title','最近的材料'));
  if(!state.lessons.length)recent.append(h('p','foot-caption','从第一份阅读材料开始。'));
  for(const item of state.lessons.slice(0,7)) {
    const el=h('button','recent-lesson',item.title);el.title=item.title;
    el.addEventListener('click',()=>navigate('study',{lessonId:item.id}));recent.append(el);
  }
}
function renderSidebar() {
  sidebarScope?.dispose();sidebarScope=new window.HebaoRuntime.Scope();
  const listen=(target,handler)=>sidebarScope.listen(target,'click',handler);
  const side=h('div','navigation');const logo=h('div','brand-row');
  const brand=h('div','brand');const mark=h('img','brand-mark');mark.src='mark.svg';mark.alt='';
  brand.append(mark,h('span','brand-name','赫宝'));logo.append(brand);
  const toggle=h('button','nav-icon-button nav-toggle');toggle.title='收起侧栏';toggle.setAttribute('aria-label','收起侧栏');toggle.setAttribute('aria-controls','workbench-navigation');toggle.append(icon('rail',18));listen(toggle,()=>frame.toggleSidebar());logo.append(toggle);side.append(logo);
  side.id='workbench-navigation';
  const start=h('button','new-study');start.append(icon('plus',17),h('span','new-study-label','新的学习'));start.title='新的学习';listen(start,()=>navigate('study'));side.append(start);
  const list=h('nav','nav-list');list.setAttribute('aria-label','工作台模块');navigationButtons=[];
  const entries=registry.list().filter(x=>x.id!=='settings');
  const learning=entries.filter(x=>x.navigationGroup==='learning');
  learningButton=null;learningTree=null;
  const addEntry=(entry,target,child=false)=>{
    const el=h('button','nav-item'+(child?' nav-child':''));el.title=entry.title;el.dataset.moduleId=entry.id;el.append(icon(entry.icon,child?15:18),h('span','nav-title',entry.title));
    if(entry.id==='study')el.append(h('span','nav-badge','CET-6'));
    listen(el,()=>navigate(entry.id));target.append(el);navigationButtons.push(el);
  };
  let learningAdded=false;
  for(const entry of entries){
    if(entry.navigationGroup==='learning'){
      if(learningAdded)continue;learningAdded=true;
      const group=h('div','learning-group');learningButton=h('button','nav-item nav-group-button');
      learningButton.title='学习';learningButton.setAttribute('aria-controls','learning-entries');
      const chevron=h('span','group-chevron');chevron.append(icon('down',14));
      learningButton.append(icon('book',18),h('span','nav-title','学习'),chevron);
      learningTree=h('div','nav-children');learningTree.id='learning-entries';
      const inner=h('div','nav-children-inner');for(const child of learning)addEntry(child,inner,true);
      learningTree.append(inner);group.append(learningButton,learningTree);list.append(group);
      listen(learningButton,()=>{
        if(side.classList.contains('is-compact')){learningExpanded=true;frame.toggleSidebar();}
        else{learningExpanded=!learningExpanded;updateLearning();}
      });
    }else{
      if(entry.id==='extensions')list.append(h('div','nav-section','扩展'));
      addEntry(entry,list);
    }
  }side.append(list);
  recent=h('div','recent-area');recentArea=recent;side.append(recent);renderRecent();
  const foot=h('div','nav-footer');const settingsEntry=registry.modules.get('settings');
  if(settingsEntry)addEntry(settingsEntry,foot);
  const identity=h('div','sidebar-foot');const avatar=h('div','avatar');avatar.append(icon('clock',17));const text=h('div','foot-label','赫宝在这里');text.append(h('div','foot-caption','慢慢来，也没关系'));identity.append(avatar,text);foot.append(identity);side.append(foot);frame.left.replaceChildren(side);
  frame.onLayout=collapsed=>{
    side.classList.toggle('is-compact',collapsed);
    toggle.setAttribute('aria-expanded',String(!collapsed));
    toggle.title=collapsed?'展开侧栏':'收起侧栏';toggle.setAttribute('aria-label',toggle.title);
    recentArea.inert=collapsed;updateLearning();
  };frame.update();updateSelection();
}
function updateLearning() {
  if(!learningButton)return;
  const compact=frame.left.firstElementChild?.classList.contains('is-compact');
  const expanded=learningExpanded&&!compact;
  if(!expanded&&learningTree.contains(document.activeElement))learningButton.focus();
  learningButton.setAttribute('aria-expanded',String(expanded));
  learningButton.title=compact?'学习：展开阅读与进度':'学习';
  learningTree.classList.toggle('is-open',expanded);learningTree.inert=!expanded;
}
function updateSelection() {
  for(const el of navigationButtons)if(el.dataset.moduleId===activeId)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
  learningButton?.classList.toggle('has-current',registry.modules.get(activeId)?.navigationGroup==='learning');
}
function navigate(id,payload) {
  if(disposed)return;
  const entry=registry.modules.get(id);if(!entry)return;
  activeId=id;if(entry.navigationGroup==='learning'){learningExpanded=true;updateLearning();}
  crumb.textContent='工作台 / '+(entry.navigationGroup==='learning'?'学习 / ':'')+entry.title;document.title=entry.title+' · 赫宝';
  updateSelection();
  host.open(id,payload);
}
renderSidebar();scope.own(registry.subscribe(renderSidebar));
function dispose() { if(disposed)return;disposed=true;scope.dispose(); }
scope.listen(window,'pagehide',()=> {
  if(!preview&&token)fetch('/api/call',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify({command:'session.leave',params:{}}),keepalive:true}).catch(()=>{});
  dispose();
});
refresh().then(()=>navigate('study')).catch(error=>{navigate('home');notify(error.message);});
})();
