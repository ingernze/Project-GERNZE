// Retain the approved opening animation; reveal the scene after the real renderer is ready.
(()=>{
 document.addEventListener('DOMContentLoaded',async()=>{
  const splash=document.getElementById('hebaoSplash'),shell=document.querySelector('.shell');
  if(!splash)return;shell.inert=true;shell.setAttribute('aria-busy','true');
  let finishReady;
  const ready=new Promise(resolve=>{finishReady=resolve;});
  window.addEventListener('hebao:portrait-ready',finishReady,{once:true});
  window.addEventListener('hebao:portrait-error',finishReady,{once:true});
  const logo=splash.querySelector('img');
  await Promise.race([logo?.decode?.().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,1800))]);
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
   const started=performance.now();splash.classList.add('entered');
   const minimum=new Promise(resolve=>setTimeout(resolve,1500));
   // Let the opening enter before preparing textures. Do not show the old standing poster.
   setTimeout(()=>window.dispatchEvent(new Event('hebao:opening-start')),180);
   let timeout;
   const boundedReady=Promise.race([ready,new Promise(resolve=>{timeout=setTimeout(resolve,7000);})]);
   Promise.all([minimum,boundedReady]).then(()=>{
    clearTimeout(timeout);window.removeEventListener('hebao:portrait-ready',finishReady);window.removeEventListener('hebao:portrait-error',finishReady);
    window.HEBAO_SPLASH={started,exitAt:performance.now()};splash.classList.add('leaving');
    setTimeout(()=>{splash.hidden=true;shell.inert=false;shell.setAttribute('aria-busy','false');window.dispatchEvent(new Event('hebao:opened'));},400);
   });
  }));
 });
})();
