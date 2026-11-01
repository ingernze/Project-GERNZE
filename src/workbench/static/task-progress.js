/* Shared desktop/mobile task indicator. Only determinate work displays a percent. */
(function(root){
'use strict';
function mount(host,{label='正在处理',image='progress-libao.png'}={}){
 const make=(tag,name)=>{const e=document.createElement(tag);e.className=name;return e;};
 const box=make('section','gernze-progress'),heading=make('div','gernze-progress-heading'),title=make('span','gernze-progress-title'),number=make('span','gernze-progress-number');
 const lane=make('div','gernze-progress-lane'),track=make('div','gernze-progress-track'),fill=make('span','gernze-progress-fill'),runner=make('span','gernze-progress-runner'),pet=make('img','gernze-progress-pet'),detail=make('p','gernze-progress-detail');
 pet.src=image;pet.alt='';pet.setAttribute('aria-hidden','true');pet.draggable=false;
 runner.append(pet);track.append(fill);lane.append(track,runner);heading.append(title,number);box.append(heading,lane,detail);host.append(box);
 box.setAttribute('role','progressbar');box.setAttribute('aria-valuemin','0');box.setAttribute('aria-valuemax','100');detail.setAttribute('role','status');
 let disposed=false;
 function update({state='running',value=null,steps=null,label:nextLabel=label,detail:message=''}={}){
  if(disposed)return;
  const staged=steps&&Number.isSafeInteger(steps.total)&&steps.total>0&&Number.isSafeInteger(steps.completed)&&steps.completed>=0&&steps.completed<=steps.total;
  const determined=typeof value==='number'&&Number.isFinite(value),v=staged?steps.completed/steps.total:determined?Math.max(0,Math.min(1,value)):null;
  const percent=v===null?null:Math.floor(v*100);
  box.dataset.state=state;box.dataset.mode=staged?'steps':v===null?'indeterminate':'determinate';
  title.textContent=nextLabel;number.textContent=staged?'已完成 '+steps.completed+'/'+steps.total+' 步':v===null?'':percent+'%';detail.textContent=message;detail.hidden=!message;
  box.style.setProperty('--task-progress',String(v===null?0:v));box.setAttribute('aria-label',nextLabel);box.setAttribute('aria-valuetext',[number.textContent,message||nextLabel].filter(Boolean).join(' · '));
  box.setAttribute('aria-valuemax',String(staged?steps.total:100));
  if(v===null)box.removeAttribute('aria-valuenow');else box.setAttribute('aria-valuenow',String(staged?steps.completed:percent));
  box.setAttribute('aria-busy',String(state==='running'));
 }
 update({label});
 return Object.freeze({element:box,update,setVisible(value){box.hidden=!value;},destroy(){disposed=true;box.remove();}});
}
root.GernzeTaskProgress=Object.freeze({mount});
})(typeof window==='object'?window:globalThis);
