import assert from 'node:assert/strict';
import {createUpdateController} from '../src/update-controller.mjs';
const downloadId='11111111-1111-4111-8111-111111111111',pairingId='22222222-2222-4222-8222-222222222222';
const release={packageName:'com.hecate.companion',versionCode:8,versionName:'1.0.7',minSdkVersion:24,size:100,sha256:'a'.repeat(64),signerCertificateSha256:['b'.repeat(64)],artifactId:'33333333-3333-4333-8333-333333333333'};
let checks=0;
function setup(){
  const map=new Map(),calls=[],events={};let progress;let granted=false;let blockDownload;
  const installed={packageName:release.packageName,versionCode:7,versionName:'1.0.6',signerCertificateSha256:release.signerCertificateSha256,apiLevel:31};
  const fixture={calls,events,map,installed,allow:()=>granted=true,
    deferDownload:()=>new Promise(resolve=>blockDownload=resolve),finishDownload:()=>blockDownload?.({status:'downloaded',downloadId})};
  const transport={pair:async()=>{calls.push('pair');return {status:'paired',pairingId};},getRelease:async()=>({release:fixture.release||release}),
    onProgress:async f=>{progress=f;return {remove:async()=>calls.push('removed')};},
    download:async()=>{calls.push('download');progress({downloadId:'other',receivedBytes:100,totalBytes:100});progress({downloadId,receivedBytes:100,totalBytes:100});return fixture.downloadPromise||{status:'downloaded',downloadId};},
    cancel:async()=>{calls.push('cancel');return {cancelled:true};},forgetPairing:async()=>{calls.push('forget');}};
  const installer={getInstalled:async()=>installed,getInstallPermission:async()=>({allowed:granted}),recoverInstallState:async()=>fixture.recovery||{status:'unknown'},
    addStateListener:async f=>{events.install=f;return {remove:async()=>{}};},inspect:async()=>{calls.push('inspect');return {status:'ready',release};},
    install:async()=>{calls.push('install');return {status:'awaiting_user',downloadId,sessionId:1};},
    openInstallPermissionSettings:async()=>calls.push('permission'),discard:async()=>{calls.push('discard');if(fixture.discardBusy)throw Object.assign(Error(),{code:'busy'});}};
  const api=createUpdateController({transport,installer,scanner:{scan:async()=>({payload:JSON.stringify({protocol:'hebao-pair-v1',serverId:pairingId,host:'192.168.43.66',port:53319,certificateSha256:'c'.repeat(64),pairingSecret:'DO_NOT_PERSIST'})})},
    storage:{getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v)},uuid:()=>downloadId,confirmPeer:async()=>fixture.confirm!==false});
  fixture.progress=e=>progress(e);fixture.api=api;return fixture;
}
{
  const f=setup();await f.api.init();f.confirm=false;await f.api.scan();assert(!f.calls.includes('pair'));checks++;
  f.confirm=true;await f.api.scan();assert(f.api.state.pair);assert(![...f.map.values()].join('').includes('DO_NOT_PERSIST'));checks++;
  await f.api.check();assert.equal(f.api.state.phase,'available');assert(!f.calls.includes('download'));checks++;
  await f.api.download();assert.equal(f.api.state.phase,'ready');assert(f.calls.includes('inspect'));assert(!f.calls.includes('install'));checks++;
  await f.api.install();assert(!f.calls.includes('install'));assert.equal(f.api.state.phase,'error');checks++;
  await f.api.openPermission();assert(f.calls.includes('permission'));assert(!f.calls.includes('install'));checks++;
  f.allow();await f.api.install();assert.equal(f.api.state.phase,'awaiting_user');assert(f.api.state.ready);checks++;
  f.events.install({status:'installed',downloadId:'other',sessionId:2});assert(f.api.state.ready);checks++;
  f.events.install({status:'cancelled',downloadId,sessionId:1});assert(f.api.state.ready);assert.equal(f.api.state.phase,'ready');checks++;
  f.discardBusy=true;await f.api.discard();assert(f.api.state.ready);checks++;
  f.discardBusy=false;await f.api.discard();assert.equal(f.api.state.ready,null);checks++;
}
{
  const f=setup();await f.api.init();await f.api.scan();f.release={...release,packageName:'bad.package'};await f.api.check();assert.equal(f.api.state.phase,'error');assert(!f.calls.includes('download'));checks++;
}
{
  const f=setup();await f.api.init();await f.api.scan();await f.api.check();
  f.downloadPromise=f.deferDownload();const work=f.api.download();await new Promise(r=>setTimeout(r,0));await f.api.cancel();f.finishDownload();await work;
  assert(f.api.state.ready);assert(!f.calls.includes('install'));checks++;
  f.events.install({status:'installed',downloadId,sessionId:1});assert.equal(f.api.state.phase,'installed');assert.equal(f.api.state.ready,null);checks++;
}
{
  const f=setup();await f.api.init();await f.api.scan();await f.api.check();
  f.downloadPromise=f.deferDownload();const work=f.api.download();await new Promise(r=>setTimeout(r,0));
  assert.equal(f.api.state.progress,1);checks++; // Actual bytes reached the full file; do not fake 99%.
  for(const e of [{receivedBytes:50,totalBytes:100},{receivedBytes:-1,totalBytes:100},{receivedBytes:Infinity,totalBytes:100},{receivedBytes:100,totalBytes:200},{receivedBytes:101,totalBytes:100}]){
    f.progress({downloadId,...e});assert.equal(f.api.state.progress,1);checks++;
  }
  f.finishDownload();await work;assert.equal(f.api.state.phase,'ready');checks++;
}
console.log(`${checks} update orchestration scenarios passed with injected native adapters; not phone tests.`);
