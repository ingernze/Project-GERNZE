import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createShakeController} from '../src/shake-controller.mjs';

function fixture(){let listener,removed=0,time=0,heard=0;const calls=[];
  const plugin={async addListener(_,fn){listener=fn;return {async remove(){removed++;}};},async setEnabled({enabled}){calls.push(enabled);return {available:true,active:enabled};}};
  const host=createShakeController({plugin,onShake:()=>heard++,clock:()=>time});
  return {host,calls,fire:()=>listener(),setTime:t=>time=t,get heard(){return heard;},get removed(){return removed;}};
}
test('foreground eligibility, cooldown, disable and destruction',async()=>{
  const f=fixture();await f.host.init();assert.deepEqual(f.calls,[false]);f.fire();assert.equal(f.heard,0);
  await f.host.setActive(true);f.fire();f.fire();assert.equal(f.heard,1);
  f.setTime(3500);f.fire();assert.equal(f.heard,2);
  await f.host.setActive(false);f.setTime(8000);f.fire();assert.equal(f.heard,2);
  await f.host.destroy();f.fire();assert.equal(f.heard,2);assert.equal(f.removed,1);
});
test('late enable result cannot trigger after the page becomes ineligible',async()=>{
  const f=fixture();await f.host.init();const a=f.host.setActive(true),b=f.host.setActive(false);await Promise.all([a,b]);f.fire();assert.equal(f.heard,0);assert.equal(f.calls.at(-1),false);await f.host.destroy();
});
test('listener that arrives after destruction is removed',async()=>{
  let finish,removed=0,enabled=0;
  const plugin={addListener:()=>new Promise(r=>finish=r),async setEnabled(){enabled++;return {available:true,active:false};}};
  const host=createShakeController({plugin,onShake:()=>assert.fail('disposed callback')});const init=host.init();await host.destroy();finish({async remove(){removed++;}});await init;assert.equal(removed,1);assert.equal(enabled,1);
});
