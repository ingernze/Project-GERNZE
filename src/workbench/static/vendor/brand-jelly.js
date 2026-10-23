// Shared, bounded tap response. One squash/stretch/settle cycle, never a queue.
(()=>{
 function create(target,{squash,stretch,down,lift,duration}){
  let motion=null,lastTap=-Infinity,taps=0;
  function stop(){motion?.cancel();motion=null;lastTap=-Infinity;taps=0;}
  function pulse({tap=true,strength=1,time=duration}={}){
   const now=performance.now();
   if(tap){taps=now-lastTap<=600?Math.min(taps+1,4):1;lastTap=now;}
   const power=strength*(tap?1+(taps-1)*.18:1);
   // Read before cancelling so rapid taps continue from the current pose.
   const from=motion?getComputedStyle(target).transform:'none';motion?.cancel();
   const current=target.animate([
    {transform:from},
    {transform:`translateY(${down*power}px) scale(${1+squash[0]*power},${1-squash[1]*power})`,offset:.25},
    {transform:`translateY(${-lift*power}px) scale(${1-stretch[0]*power},${1+stretch[1]*power})`,offset:.6},
    {transform:'translateY(0) scale(1,1)'}
   ],{duration:time,easing:'cubic-bezier(.22,.7,.3,1)'});
   motion=current;current.finished.then(()=>{if(motion===current)motion=null;}).catch(()=>{});
  }
  return Object.freeze({pulse,stop});
 }
 window.GernzeJelly=Object.freeze({create});
 function mount(){
  const button=document.getElementById('brandPet'),logo=button?.querySelector('img');
  if(!logo||typeof logo.animate!=='function')return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const jelly=create(logo,{squash:[.16,.16],stretch:[.104,.104],down:1,lift:5,duration:500});
  let opened=Boolean(window.HEBAO_SPLASH&&document.getElementById('hebaoSplash')?.hidden),active=true,timer=0;
  const allowed=()=>opened&&active&&!document.hidden&&!reduced.matches;
  function stop(){clearTimeout(timer);timer=0;jelly.stop();}
  function schedule(){clearTimeout(timer);if(allowed())timer=setTimeout(()=>{jelly.pulse({tap:false,strength:.375,time:660});schedule();},9000+Math.random()*5000);}
  function refresh(){stop();schedule();}
  button.addEventListener('click',()=>{if(allowed())jelly.pulse();schedule();});
  window.addEventListener('hebao:opened',()=>{opened=true;schedule();},{once:true});
  window.addEventListener('hebao:app-active',event=>{active=event.detail===true;refresh();});
  document.addEventListener('visibilitychange',refresh);
  window.addEventListener('pagehide',stop);window.addEventListener('pageshow',schedule);
  reduced.addEventListener('change',refresh);schedule();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
