const test=require('node:test'),assert=require('node:assert/strict');
const {player,sleepSchedule,inWindow}=require('../static/scene-actions.js');
const flush=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
function clock(){let time=0,id=0;const jobs=new Map();return {set(fn,ms){jobs.set(++id,{fn,at:time+ms});return id;},clear(key){jobs.delete(key);},now:()=>time,count:()=>jobs.size,async next(late=0){const pair=[...jobs].sort((a,b)=>a[1].at-b[1].at)[0];assert.ok(pair,'expected one timer');jobs.delete(pair[0]);time=pair[1].at+late;pair[1].fn();await flush();}};}
const sequence={entry:[{file:'enter',ms:100}],loop:[{file:'breathe-a',ms:110},{file:'breathe-b',ms:120}],exit:[{file:'wake',ms:130}]};
function fixture(extra={}){const c=clock(),frames=[],phases=[];const p=player({load:async x=>x,render:x=>frames.push(x),onPhase:x=>phases.push(x),setTimer:c.set,clearTimer:c.clear,now:c.now,...extra});return {c,p,frames,phases};}
test('finite actions keep manifest phase order and end with no timer',async()=>{const x=fixture();const done=x.p.play(sequence,{cycles:2});await flush();for(let n=0;n<6;n++)await x.c.next();assert.equal(await done,true);assert.deepEqual(x.frames,['enter','breathe-a','breathe-b','breathe-a','breathe-b','wake']);assert.equal(x.c.now(),690);assert.equal(x.c.count(),0);});
test('wake during entry waits for the entry seam without adding a loop',async()=>{const x=fixture();const done=x.p.play(sequence,{cycles:Infinity});await flush();assert.equal(x.p.wake(),true);await x.c.next();assert.deepEqual(x.frames,['enter','wake']);await x.c.next();assert.equal(await done,true);});
test('wake in breathing finishes current loop before exit',async()=>{const x=fixture();const done=x.p.play(sequence,{cycles:Infinity});await flush();await x.c.next();x.p.wake();await x.c.next();assert.deepEqual(x.frames,['enter','breathe-a','breathe-b']);await x.c.next();assert.equal(x.frames.at(-1),'wake');await x.c.next();assert.equal(await done,true);});
test('cancelled late image never draws over a new character',async()=>{let release;const x=fixture({load:()=>new Promise(r=>release=r)});const done=x.p.play(sequence);x.p.stop();release('late');await flush();assert.equal(await done,false);assert.deepEqual(x.frames,[]);assert.equal(x.c.count(),0);});
test('stopping resolves the old playback and removes its only timer',async()=>{const x=fixture();const done=x.p.play(sequence,{cycles:Infinity});await flush();x.p.stop();assert.equal(await done,false);assert.equal(x.c.count(),0);assert.equal(x.p.wake(),false);});
const prefs={sleep_enabled:true,sleep_window_start:'22:00',sleep_window_end:'08:00',sleep_day_mean_min:120,sleep_night_mean_min:10,sleep_min_s:30,sleep_max_s:600};
function scheduler(options={}){const c=clock();let enabled=true,started=0,wakes=0;const epoch=new Date(2026,9,16,23,0).getTime();const s=sleepSchedule({prefs,available:()=>enabled,start:()=>{started++;return true;},wake:()=>wakes++,isSleeping:()=>enabled,setTimer:c.set,clearTimer:c.clear,mono:c.now,local:()=>new Date(epoch+c.now()),random:()=>0,...options});return {c,s,enabled:x=>enabled=x,started:()=>started,wakes:()=>wakes};}
test('night window is inclusive at start and exclusive at end, including midnight',()=>{for(const [h,m,expected]of[[21,59,false],[22,0,true],[0,0,true],[7,59,true],[8,0,false]])assert.equal(inWindow(new Date(2026,9,16,h,m),prefs),expected);});
test('automatic sleep uses the original 30-second floor and starts once',async()=>{const x=scheduler();x.s.schedule();assert.equal(x.c.count(),1);await x.c.next();assert.equal(x.c.now(),30000);assert.equal(x.started(),1);assert.equal(x.c.count(),0);});
test('busy or hidden state does not accumulate missed sleep and duration starts at holding',async()=>{const x=scheduler();x.s.schedule();x.enabled(false);await x.c.next();assert.equal(x.started(),0);x.enabled(true);x.s.schedule();await x.c.next();assert.equal(x.started(),1);x.s.holding();await x.c.next();assert.equal(x.wakes(),1);assert.equal(x.c.now(),90000);});
test('cancel removes idle and wake timers, resuming samples a new wait',async()=>{const x=scheduler();x.s.schedule();x.s.holding();assert.equal(x.c.count(),2);x.s.cancel();assert.equal(x.c.count(),0);x.s.schedule();await x.c.next();assert.equal(x.started(),1);x.s.destroy();assert.equal(x.c.count(),0);});
test('changing settings keeps an already chosen wake duration',async()=>{const x=scheduler();x.s.holding();x.s.configure({...prefs,sleep_enabled:false,sleep_min_s:100,sleep_max_s:100});assert.equal(x.c.count(),1);await x.c.next();assert.equal(x.c.now(),30000);assert.equal(x.wakes(),1);});
test('large delayed callbacks resample without replaying missed sleeps',async()=>{const x=scheduler();x.s.schedule();await x.c.next(61000);assert.equal(x.started(),0);assert.equal(x.c.count(),1);await x.c.next();assert.equal(x.started(),1);x.s.destroy();});

test('next image is decoded during the current hold, including phase boundaries',async()=>{
  const loads=[],x=fixture({load:async file=>{loads.push(file);return file;}});
  const done=x.p.play(sequence,{cycles:1});await flush();
  assert.deepEqual(x.frames,['enter']);assert.deepEqual(loads,['enter','breathe-a']);
  await x.c.next();assert.deepEqual(x.frames,['enter','breathe-a']);assert.equal(loads.at(-1),'breathe-b');
  await x.c.next();assert.equal(loads.at(-1),'wake');
  await x.c.next();await x.c.next();assert.equal(await done,true);
});
test('decode latency overlaps frame holds instead of extending every frame',async()=>{
  const c=clock(),shown=[];
  const p=player({load:file=>new Promise(resolve=>c.set(()=>resolve(file),20)),render:file=>shown.push([file,c.now()]),setTimer:c.set,clearTimer:c.clear,now:c.now});
  const done=p.play(sequence,{cycles:1});await flush();
  for(let n=0;p.state()&&n<12;n++)await c.next();
  assert.equal(await done,true);assert.deepEqual(shown,[['enter',20],['breathe-a',120],['breathe-b',230],['wake',350]]);
  assert.equal(c.now(),480);assert.equal(c.count(),0);
});
test('failed speculative load is reported at the next frame and clears playback',async()=>{
  const x=fixture({load:async file=>{if(file==='breathe-a')throw Error('decode failed');return file;}});
  const done=x.p.play(sequence);const rejected=assert.rejects(done,/decode failed/);await flush();
  assert.deepEqual(x.frames,['enter']);await x.c.next();await rejected;assert.equal(x.c.count(),0);assert.equal(x.p.state(),null);
});
