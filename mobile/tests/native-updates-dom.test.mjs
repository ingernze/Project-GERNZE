import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createUpdateController} from '../src/update-controller.mjs';

const uuid='11111111-1111-4111-8111-111111111111';
const pair={pairingId:uuid,host:'192.0.2.1',port:1234,fingerprint:'a'.repeat(64)};
const release={size:100,versionName:'1.1.2',versionCode:112,packageName:'fixture',signerCertificateSha256:['f'],minSdkVersion:23,artifactId:'fixture'};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.ids=new Map();this.dataset={};this.style={setProperty:(key,value)=>this.style[key]=value};this.attributes={};this.hidden=false;this.open=false;this.listeners={};this.textContent='';}
  set innerHTML(html){this.ids.clear();for(const match of html.matchAll(/<([a-z][a-z0-9-]*)\b[^>]*\bid="([^"]+)"/g)){const child=new Element(match[1]);child.id=match[2];this.ids.set(child.id,child);}}
  querySelector(selector){return this.ids.get(selector.slice(1))||null;}
  querySelectorAll(){return [...this.ids.values()].filter(x=>['button','input'].includes(x.tag));}
  append(...nodes){this.children.push(...nodes);for(const node of nodes)node.parent=this;}
  after(node){this.parent?.append(node);}
  remove(){this.removed=true;if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}
  setAttribute(k,v){this.attributes[k]=v;}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  showModal(){this.open=true;}
  close(){this.open=false;}
}

async function harness({ready=null,appPromise=null,installerPromise=null,transportOverrides={}}={}){
  const events=new Map(),settings=new Element('section'),anchor=new Element('form');anchor.parent=settings;
  settings.id='settings';settings.ids.set('qualityForm',anchor);
  const document={createElement:tag=>new Element(tag),getElementById:id=>id==='settings'?settings:settings.children.find(x=>x.id===id)||null};
  const window={addEventListener:(name,fn)=>{const arr=events.get(name)||[];arr.push(fn);events.set(name,arr);},dispatch(name,arg={}){for(const fn of events.get(name)||[])fn(arg);}};
  const storage={raw:JSON.stringify({pair,ready}),getItem(){return this.raw;},setItem(k,v){this.raw=v;}};
  const trace={appAdded:0,appRemoved:0,installAdded:0,installRemoved:0,resumed:0,progressCallback:null,cancelled:0};
  const installer={addStateListener:()=>{trace.installAdded++;return installerPromise?.promise||Promise.resolve({remove:async()=>{trace.installRemoved++;}});},
    getInstalled:async()=>({versionName:'1.1.1',versionCode:111,packageName:'fixture',signerCertificateSha256:['f'],apiLevel:35}),
    getInstallPermission:async()=>({allowed:true}),recoverInstallState:async()=>({status:'unknown'}),
    inspect:async()=>({status:'ready',release}),discard:async()=>{},install:async()=>({status:'awaiting_user'})};
  const transport={getRelease:async()=>({release}),onProgress:async fn=>{trace.progressCallback=fn;return {remove:async()=>{}};},
    download:async()=>({status:'downloaded',downloadId:uuid}),cancel:async()=>{trace.cancelled++;return {cancelled:true};},
    ...transportOverrides};
  const context=vm.createContext({window,document,localStorage:storage,crypto:{randomUUID:()=>uuid},
    Capacitor:{isNativePlatform:()=>true,getPlatform:()=> 'android'},registerPlugin:()=>({scan:async()=>({})}),
    App:{addListener:()=>{trace.appAdded++;return appPromise?.promise||Promise.resolve({remove:async()=>{trace.appRemoved++;}});}},
    createUpdateTransport:()=>transport,updateInstaller:installer,createUpdateController,
    TextEncoder,fetch:async()=>{throw Error('no network')},console});
  const shared=readFileSync(new URL('../../src/workbench/static/task-progress.js',import.meta.url),'utf8');
  vm.runInContext(shared,context);
  const source=readFileSync(new URL('../src/native-updates.js',import.meta.url),'utf8')
    .replace(/^import .*;\s*$/gm,'').replace('export function mountUpdates','function mountUpdates');
  vm.runInContext(source+'\nthis.mountUpdates=mountUpdates;',context);
  context.mountUpdates();await tick();await tick();
  const panel=()=>document.getElementById('hebaoUpdates');
  const el=id=>panel()?.querySelector('#'+id);
  const bar=()=>el('updateProgress')?.children[0];
  return {window,document,panel,el,bar,trace,context,storage,installer,transport};
}

test('restored complete package shows 100%, a check failure does not show completed download',async()=>{
  const h=await harness({ready:{downloadId:uuid,release}});
  assert.equal(h.el('updateProgress').hidden,false);
  assert.equal(h.bar().children[0].children[1].textContent,'100%');
  assert.equal(h.bar().attributes['aria-valuenow'],'100');
  h.window.dispatch('pagehide');await tick();
  const failed=await harness({transportOverrides:{getRelease:async()=>{throw Object.assign(Error(),{code:'unreachable'});}}});
  await failed.el('updateCheck').onclick();await tick();
  assert.equal(failed.el('updateProgress').hidden,true);
  assert.match(failed.el('updateStatus').textContent,/没有连上电脑/);
  failed.window.dispatch('pagehide');
});

test('download bytes stay at their real completion while verification is pending; teardown',async()=>{
  const download=deferred(),inspection=deferred();const h=await harness({transportOverrides:{download:()=>download.promise}});h.installer.inspect=()=>inspection.promise;
  await h.el('updateCheck').onclick();await tick();
  h.el('updateDownload').onclick();await tick();
  h.trace.progressCallback({downloadId:uuid,totalBytes:100,receivedBytes:60});
  await tick();assert.equal(h.bar().children[0].children[1].textContent,'60%');
  download.resolve({status:'downloaded',downloadId:uuid});await tick();
  assert.equal(h.bar().dataset.mode,'determinate'); // Transfer finished; package checking is separate.
  assert.equal(h.bar().children[0].children[1].textContent,'100%');
  assert.equal(h.bar().dataset.state,'running');
  assert.match(h.bar().children[2].textContent,/检查安装包/);
  inspection.resolve({status:'ready',release});await tick();await tick();
  assert.equal(h.bar().children[0].children[1].textContent,'100%');
  h.window.dispatch('pagehide');await tick();
  assert.equal(h.panel(),null);assert.equal(h.trace.appRemoved,1);assert.equal(h.trace.installRemoved,1);
});

test('pagehide before asynchronous listener registration releases both; persisted page remounts one panel',async()=>{
  const app=deferred(),install=deferred();const h=await harness({appPromise:app,installerPromise:install});
  h.window.dispatch('pagehide');
  app.resolve({remove:async()=>{h.trace.appRemoved++;}});
  install.resolve({remove:async()=>{h.trace.installRemoved++;}});
  await tick();await tick();
  assert.equal(h.trace.appRemoved,1);assert.equal(h.trace.installRemoved,1);
  assert.equal(h.panel(),null);
  const entry=readFileSync(new URL('../src/native-entry.js',import.meta.url),'utf8');
  vm.runInContext(entry.split('\n').find(line=>line.startsWith("window.addEventListener('pageshow'")),h.context);
  h.window.dispatch('pageshow',{persisted:true});await tick();await tick();
  assert.equal(h.document.getElementById('hebaoUpdates')?.id,'hebaoUpdates');
  h.context.mountUpdates();assert.equal(h.document.getElementById('settings').children.length,1);
  assert.equal(h.trace.appAdded,2);assert.equal(h.trace.installAdded,2);
  assert.equal(h.trace.appRemoved,1);assert.equal(h.trace.installRemoved,1);
  h.window.dispatch('pagehide');await tick();
  assert.equal(h.trace.appRemoved,2);assert.equal(h.trace.installRemoved,2);
});

test('cancel while native progress subscription is pending drops late bytes and leaves no live panel',async()=>{
  const subscription=deferred();let late;
  const h=await harness({transportOverrides:{onProgress:fn=>{late=fn;return subscription.promise;}}});
  h.el('updateCheck').onclick();await tick();h.el('updateDownload').onclick();await tick();
  h.el('updateCancel').onclick();await tick();
  subscription.resolve({remove:async()=>{}});await tick();await tick();
  assert.equal(h.el('updateProgress').hidden,true);
  assert.match(h.el('updateStatus').textContent,/已取消/);
  h.window.dispatch('pagehide');late({downloadId:uuid,totalBytes:100,receivedBytes:100});await tick();
  assert.equal(h.panel(),null);
});

test('review steps remain actual completed counts; unknown work has no percentage',async()=>{
  const h=await harness(),host=new Element(),bar=h.window.GernzeTaskProgress.mount(host);
  bar.update({steps:{completed:2,total:5},state:'running',detail:'等待模型审查'});
  assert.equal(bar.element.children[0].children[1].textContent,'已完成 2/5 步');
  assert.equal(bar.element.style['--task-progress'],'0.4');
  assert.equal(bar.element.attributes['aria-valuemax'],'5');
  assert.equal(bar.element.attributes['aria-valuenow'],'2');
  bar.update({steps:{completed:2,total:5},state:'error',detail:'审查未完成'});
  assert.equal(bar.element.style['--task-progress'],'0.4');
  bar.update({state:'running',detail:'等待实际进度'});
  assert.equal(bar.element.children[0].children[1].textContent,'');
  assert.equal(bar.element.style['--task-progress'],'0');
  assert.equal(bar.element.attributes['aria-valuenow'],undefined);
  bar.destroy();h.window.dispatch('pagehide');
});
