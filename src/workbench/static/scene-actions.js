/* Existing manifest phases and SleepSchedule rules, adapted for the browser. */
(function(root){
'use strict';
function player({load,render,onPhase=()=>{},setTimer=setTimeout,clearTimer=clearTimeout,now=()=>performance.now()}){
  let generation=0,timer=null,resolveWait=null,current=null;
  function stop(){generation++;current=null;if(timer!==null)clearTimer(timer);timer=null;if(resolveWait){const done=resolveWait;resolveWait=null;done();}}
  async function play(sequence,{cycles=1}={}){
    stop();const version=generation;current={phase:'entry',wakeRequested:false};
    const active=()=>generation===version&&current!==null;
    const wait=ms=>new Promise(resolve=>{resolveWait=resolve;timer=setTimer(()=>{timer=null;resolveWait=null;resolve();},ms);});
    // Keep only the next decoded image ready while the current image is held.
    // Capture speculative failures immediately, but report them at their frame.
    let prepared=null;
    function preload(file){
      if(!prepared||prepared.file!==file)prepared={file,promise:new Promise(resolve=>resolve(load(file))).then(image=>({image}),error=>({error}))};
      return prepared.promise;
    }
    async function phase(name,following){
      if(!active())return false;current.phase=name;
      const frames=sequence[name];if(!Array.isArray(frames)||!frames.length)throw Error('动作帧清单不完整');
      for(let index=0;index<frames.length;index++){
        const f=frames[index];if(!Number.isInteger(f.ms)||f.ms<30||f.ms>10000)throw Error('动作帧时长无效');
        const loaded=await preload(f.file);if(!active())return false;if(loaded.error)throw loaded.error;
        prepared=null;const started=now();render(loaded.image);if(index===0)onPhase(name);
        const next=frames[index+1]||following?.();if(active()&&next)preload(next.file);
        await wait(Math.max(0,f.ms-(now()-started)));if(!active())return false;
      }
      return true;
    }
    try{
      if(!await phase('entry',()=>current.wakeRequested||cycles<=0?sequence.exit?.[0]:sequence.loop?.[0]))return false;
      for(let cycle=0;active()&&!current.wakeRequested&&cycle<cycles;cycle++)if(!await phase('loop',()=>current.wakeRequested||cycle+1>=cycles?sequence.exit?.[0]:sequence.loop?.[0]))return false;
      if(!await phase('exit'))return false;
      if(active())current=null;return true;
    }catch(error){if(active()){stop();throw error;}return false;}
  }
  return Object.freeze({play,stop,wake(){if(!current||current.phase==='exit'||current.wakeRequested)return false;current.wakeRequested=true;return true;},state:()=>current&&({...current})});
}
const minute=text=>{const [h,m]=text.split(':').map(Number);return h*60+m;};
function inWindow(date,prefs){const start=minute(prefs.sleep_window_start),end=minute(prefs.sleep_window_end),now=date.getHours()*60+date.getMinutes();return start<end?start<=now&&now<end:now>=start||now<end;}
function boundary(date,prefs){return Math.min(...['sleep_window_start','sleep_window_end'].map(key=>{const m=minute(prefs[key]),next=new Date(date);next.setHours(Math.floor(m/60),m%60,0,0);if(next<=date)next.setDate(next.getDate()+1);return next-date;}));}
function sleepSchedule({prefs,available,start,wake,isSleeping,setTimer=setTimeout,clearTimer=clearTimeout,mono=()=>performance.now(),local=()=>new Date(),random=Math.random}){
  let job=null,wakeJob=null,due=null,armed=false,closed=false,failed=false;
  function cancelIdle(reset=false){if(job!==null)clearTimer(job);job=null;if(reset)due=null;}
  function cancelWake(){if(wakeJob!==null)clearTimer(wakeJob);wakeJob=null;}
  function cancel(){cancelIdle(true);cancelWake();armed=false;}
  function schedule(){
    if(closed||failed||job!==null||!prefs.sleep_enabled||!available())return;
    const at=mono(),date=local(),high=inWindow(date,prefs),mean=prefs[high?'sleep_night_mean_min':'sleep_day_mean_min']*60000;
    if(due===null||due<=at)due=at+30000-Math.log(1-random())*(mean-30000);
    const edge=boundary(date,prefs),remaining=due-at,wait=Math.min(remaining,edge),expected=at+wait,isBoundary=edge<=remaining;
    job=setTimer(()=>{
      job=null;const current=mono(),now=local(),drift=Math.abs((now-date)-(current-at));
      if(isBoundary||inWindow(now,prefs)!==high||current-expected>60000||drift>5000){due=null;schedule();return;}
      if(!available()){due=null;return;}
      if(current+2<due){schedule();return;}
      due=null;Promise.resolve(start()).then(ok=>{if(ok===false)failed=true;}).catch(()=>{failed=true;});
    },Math.max(1,Math.ceil(wait)));
  }
  return Object.freeze({schedule,cancelIdle,cancelWake,cancel,
    configure(value){prefs={...value};cancelIdle(true);schedule();},
    holding(){if(armed||closed)return;armed=true;const seconds=prefs.sleep_min_s+Math.floor(random()*(prefs.sleep_max_s-prefs.sleep_min_s+1));wakeJob=setTimer(()=>{wakeJob=null;if(!closed&&isSleeping())wake();},seconds*1000);},
    destroy(){closed=true;cancel();}
  });
}
const api=Object.freeze({player,sleepSchedule,inWindow});
if(typeof module==='object'&&module.exports)module.exports=api;else root.HebaoSceneActions=api;
})(typeof window==='object'?window:globalThis);
