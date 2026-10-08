const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(){
 const window=new EventTarget(),document=new EventTarget();document.hidden=false;
 document.getElementById=()=>({});document.querySelector=()=>({});
 let resolve,reject;const claim=new Promise((a,b)=>{resolve=a;reject=b;});
 const events=[],plays=[];let cancels=0;
 window.HebaoWorkbenchVoice={claimEntrance:()=>claim,notify:e=>events.push(e)};
 window.HebaoArrivalV23={play:o=>plays.push(o),cancel:()=>cancels++};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/arrival_bootstrap.js'),'utf8'),{window,document});
 return {window,document,events,plays,resolve,reject,cancels:()=>cancels};
}
const flush=()=>new Promise(r=>setImmediate(r));
test('first allowance retains media cue and skip stops voice',async()=>{
 const s=setup();assert.equal(s.plays.length,0);s.resolve({play:true});await flush();
 assert.equal(s.plays.length,1);assert.equal(s.plays[0].cueAt,2.1);
 s.plays[0].onCue();assert.equal(s.events.at(-1),'workbench_open');
 s.plays[0].onFinish('skipped');assert.equal(s.events.at(-1),'workbench_stop');
});
test('reopened page creates no video and no welcome',async()=>{
 const s=setup();s.resolve({play:false});await flush();assert.equal(s.plays.length,0);assert.deepEqual(s.events,[]);
});
test('page closed while claim pending cannot play later',async()=>{
 const s=setup();s.window.dispatchEvent(new Event('pagehide'));s.resolve({play:true});await flush();assert.equal(s.plays.length,0);assert.equal(s.cancels(),1);assert(!s.events.includes('workbench_open'));
});
test('claim failure does not fall back to replay',async()=>{
 const s=setup();s.reject(Error('service unavailable'));await flush();assert.equal(s.plays.length,0);assert.deepEqual(s.events,[]);
});
