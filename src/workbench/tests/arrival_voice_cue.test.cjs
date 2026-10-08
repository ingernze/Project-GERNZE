'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function setup(frameSupport=true){
 const videos=[],timers=new Map();let seq=0;
 class Element extends EventTarget{
  constructor(tag){super();this.tag=tag;this.children=[];this.classList={add(){}};this.inert=false;this.isConnected=true;this.paused=true;this.currentTime=0;this.frames=new Map();}
  append(...items){for(const item of items){this.children.push(item);item.parent=this;}}
  closest(){return null;}setAttribute(){}removeAttribute(){}load(){}focus(){document.activeElement=this;}
  contains(node){return this===node||this.children.some(c=>c.contains(node));}
  remove(){this.isConnected=false;if(this.parent)this.parent.children=this.parent.children.filter(c=>c!==this);}
  play(){this.paused=false;this.dispatchEvent(new Event('playing'));return Promise.resolve();}
  pause(){this.paused=true;}
  requestVideoFrameCallback(fn){this.frames.set(++seq,fn);return seq;}
  cancelVideoFrameCallback(id){this.frames.delete(id);}
  present(time){this.currentTime=time;const jobs=[...this.frames.values()];this.frames.clear();for(const fn of jobs)fn(0,{mediaTime:time});}
 }
 const document=new EventTarget();document.body=new Element('body');document.activeElement=document.body;document.hidden=false;const app=new Element('app');document.getElementById=()=>app;
 document.createElement=tag=>{const el=new Element(tag);if(tag==='video'){videos.push(el);if(!frameSupport){el.requestVideoFrameCallback=undefined;el.cancelVideoFrameCallback=undefined;}}return el;};
 const window={};const context=vm.createContext({window,document,Number,Boolean,setTimeout:fn=>{timers.set(++seq,fn);return seq;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/arrival.js'),'utf8'),context);
 return {api:window.HebaoArrivalV23,document,app,videos,timers};
}
test('voice follows presented media time despite startup delay, emits once, and stops scheduling after its cue',()=>{
 const s=setup(),calls=[];s.api.play({cueAt:2.1,onCue:x=>calls.push(x.mediaTime)});const v=s.videos[0];
 v.present(0);v.present(1.5);v.present(2.0666667);assert.deepEqual(calls,[]);
 v.present(2.1);assert.deepEqual(calls,[2.1]);assert.equal(v.frames.size,0);
 v.present(3.9);v.dispatchEvent(new Event('ended'));assert.deepEqual(calls,[2.1]);assert.equal(s.document.body.children.length,0);assert.equal(s.app.inert,false);assert.equal(s.timers.size,0);
});
test('pause and hidden frames cannot emit; returning resumes the pending cue without a second voice',()=>{
 const s=setup(),calls=[];s.api.play({cueAt:2.1,onCue:x=>calls.push(x.mediaTime)});const v=s.videos[0];
 s.document.hidden=true;s.document.dispatchEvent(new Event('visibilitychange'));v.present(2.2);assert.deepEqual(calls,[]);assert.equal(v.paused,true);
 s.document.hidden=false;s.document.dispatchEvent(new Event('visibilitychange'));v.present(2.2);assert.deepEqual(calls,[2.2]);
 s.document.hidden=true;s.document.dispatchEvent(new Event('visibilitychange'));s.document.hidden=false;s.document.dispatchEvent(new Event('visibilitychange'));v.present(2.5);assert.deepEqual(calls,[2.2]);s.api.cancel();
});
test('skip, failure, and replay cancel pending old callbacks; each fresh replay has its own cue',()=>{
 const s=setup(),calls=[],ended=[];s.api.play({cueAt:2.1,onCue:()=>calls.push('old'),onFinish:r=>ended.push(r)});const old=s.videos[0],stale=[...old.frames.values()][0];
 s.api.play({cueAt:2.1,onCue:()=>calls.push('new')});stale(0,{mediaTime:2.2});assert.deepEqual(calls,[]);assert.equal(old.frames.size,0);assert.deepEqual(ended,['cancelled']);
 s.videos[1].present(2.1);assert.deepEqual(calls,['new']);s.api.cancel();
 for(const event of ['error','skip']){
  s.api.play({cueAt:2.1,onCue:()=>calls.push('late')});const v=s.videos.at(-1);
  if(event==='error')v.dispatchEvent(new Event('error'));else s.document.body.children.at(-1).children[2].dispatchEvent(new Event('click'));
  v.present(2.5);assert.equal(v.frames.size,0);assert.equal(s.timers.size,0);
 }
 assert.deepEqual(calls,['new']);assert.equal(s.api.isActive(),false);
});
test('older browsers use media timeupdate, ignore paused or early events, and release their listener',()=>{
 const s=setup(false),calls=[];s.api.play({cueAt:2.1,onCue:x=>calls.push(x.mediaTime)});const v=s.videos[0];
 v.currentTime=2;v.dispatchEvent(new Event('timeupdate'));assert.deepEqual(calls,[]);
 v.pause();v.currentTime=2.5;v.dispatchEvent(new Event('timeupdate'));assert.deepEqual(calls,[]);
 v.play();assert.deepEqual(calls,[2.5]);v.dispatchEvent(new Event('timeupdate'));assert.deepEqual(calls,[2.5]);s.api.cancel();v.currentTime=3.5;v.dispatchEvent(new Event('timeupdate'));assert.deepEqual(calls,[2.5]);
});
