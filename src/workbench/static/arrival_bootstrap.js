/* Optional local-media entrance. Owns no data or recurring tasks. */
(function () {
 'use strict';
 const app=document.getElementById('app');
 const header=document.querySelector('.workbench-header');
 if(!app||!header||!window.HebaoArrivalV23)return;
 let disposed=false;
 function visibility(){if(document.hidden)window.HebaoWorkbenchVoice?.notify('workbench_stop');}
 document.addEventListener('visibilitychange',visibility);
 function play(){
  if(disposed)return;
  window.HebaoWorkbenchVoice?.notify('workbench_stop');
  // V23: watch lands at source 1.8s + the approved 0.3s opening offset.
  window.HebaoArrivalV23.play({app,source:'/arrival_v23.webm',cueAt:2.1,onCue:()=>{
   if(!disposed&&!document.hidden)window.HebaoWorkbenchVoice?.notify('workbench_open');
  },onFinish:(reason)=>{
   if(!disposed&&reason!=='ended')window.HebaoWorkbenchVoice?.notify('workbench_stop');
  }});
 }
 function dispose(){
  if(disposed)return;disposed=true;
  window.HebaoWorkbenchVoice?.notify('workbench_stop');
  document.removeEventListener('visibilitychange',visibility);
  window.HebaoArrivalV23.cancel();
 }
 window.addEventListener('pagehide',dispose,{once:true});
 // Claim from the desktop process, not browser storage or the page lifetime.
 // Skip, reload or failure still consume this launch's allowance.
 window.HebaoWorkbenchVoice?.claimEntrance().then(result=>{
  if(result.play&&!disposed)play();
 }).catch(()=>{ /* A missing session must never cause an unapproved replay. */ });
})();
