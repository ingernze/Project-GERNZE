import {Capacitor,registerPlugin} from '@capacitor/core';
import {App} from '@capacitor/app';
import {createUpdateTransport} from './update-transport.mjs';
import {updateInstaller} from './update-installer.mjs';
import {createUpdateController} from './update-controller.mjs';

const scanner=registerPlugin('HebaoPairingScanner');
export function mountUpdates(){
  const page=document.getElementById('settings');if(!page||document.getElementById('hebaoUpdates'))return;
  const panel=document.createElement('section');panel.id='hebaoUpdates';panel.className='panel';
  panel.innerHTML=`<h3>电脑更新</h3><p id="updateVersion" class="hint">读取当前版本…</p>
    <p id="updatePeer" class="hint">还没有配对电脑。</p><p id="updateStatus" role="status" aria-live="polite"></p>
    <progress id="updateProgress" max="1" value="0" hidden style="width:100%"></progress>
    <div class="update-buttons" style="display:flex;flex-wrap:wrap;gap:8px">
      <button type="button" id="updateScan">扫描电脑二维码</button><button type="button" id="updateCheck">检查更新</button>
      <button type="button" id="updateDownload" hidden>下载更新</button><button type="button" id="updateCancel" hidden>取消下载</button>
      <button type="button" id="updateInstall" class="primary" hidden>安装更新</button><button type="button" id="updatePermission" hidden>允许安装更新</button>
      <button type="button" id="updateDiscard" hidden>移除这份下载</button><button type="button" id="updateForget" hidden>解除配对</button>
    </div><p class="hint">电脑连接手机热点后，在电脑上打开更新发布窗口。第一次扫码配对，之后直接检查更新；下载时请保持莉宝在前台。</p>
    <details><summary>无法扫码时</summary><label for="updatePairFile">导入电脑生成的配对文件</label><input id="updatePairFile" type="file" accept=".json,application/json"><p class="hint">配对文件短时有效，仅用于首次连接或电脑地址变化。</p></details>
    <details id="updateLicenses"><summary>开源许可</summary><pre id="updateLicenseText" style="white-space:pre-wrap;max-height:240px;overflow:auto;font-size:11px">打开后显示。</pre></details>
    <dialog id="updateIdentity" style="max-width:90%;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:18px;padding:20px">
      <h3>确认是自己的电脑</h3><p id="updateIdentityHost"></p><p class="hint">请与电脑窗口里的身份指纹核对：</p><p id="updateIdentityHash" style="overflow-wrap:anywhere;font-family:monospace"></p>
      <button type="button" id="updateIdentityConfirm">是这台电脑</button> <button type="button" id="updateIdentityCancel">取消</button>
    </dialog>`;
  page.querySelector('#qualityForm').after(panel);
  const $=id=>panel.querySelector('#'+id);
  $('updateLicenses').addEventListener('toggle',async()=>{if(!$('updateLicenses').open||$('updateLicenseText').dataset.loaded)return;try{const response=await fetch('updates-notices.txt');if(!response.ok)throw Error();$('updateLicenseText').textContent=await response.text();$('updateLicenseText').dataset.loaded='1';}catch{$('updateLicenseText').textContent='许可文件暂未加载，可重开后查看。';}});
  const native=Capacitor.isNativePlatform()&&Capacitor.getPlatform()==='android';
  if(!native){$('updateVersion').textContent='此功能在手机安装版中使用。';$('updateStatus').textContent='电脑发布更新后，手机莉宝通过热点接收。';panel.querySelectorAll('button,input').forEach(el=>el.disabled=true);return;}
  let identityAnswer=null;
  const answer=value=>{const resolve=identityAnswer;identityAnswer=null;$('updateIdentity').close();resolve?.(value);};
  $('updateIdentityConfirm').onclick=()=>answer(true);$('updateIdentityCancel').onclick=()=>answer(false);
  $('updateIdentity').addEventListener('cancel',e=>{e.preventDefault();answer(false);});
  const controller=createUpdateController({transport:createUpdateTransport(),installer:updateInstaller,scanner,storage:localStorage,
    uuid:()=>crypto.randomUUID(),confirmPeer:peer=>new Promise(resolve=>{
      $('updateIdentityHost').textContent=`电脑地址 ${peer.host}:${peer.port}`;
      $('updateIdentityHash').textContent=peer.fingerprint.match(/.{1,4}/g).join(' ');
      identityAnswer=resolve;$('updateIdentity').showModal();
    }),onChange:state=>{
      $('updateVersion').textContent=state.installed?`当前版本 ${state.installed.versionName}`:'正在读取当前版本…';
      $('updatePeer').textContent=state.pair?`已配对电脑 ${state.pair.host}:${state.pair.port}`:'还没有配对电脑。';
      $('updateStatus').textContent=state.message;
      $('updateScan').disabled=state.busy||!!state.ready;
      $('updateCheck').disabled=state.busy||!state.pair||!!state.ready;
      $('updateDownload').hidden=state.phase!=='available';$('updateDownload').disabled=state.busy;
      $('updateCancel').hidden=state.phase!=='downloading';$('updateCancel').disabled=false;
      $('updateProgress').hidden=state.phase!=='downloading';$('updateProgress').value=state.progress;
      $('updateInstall').hidden=!state.ready;$('updateInstall').disabled=state.busy||state.phase==='awaiting_user';
      $('updatePermission').hidden=!state.ready||state.permission;$('updatePermission').disabled=state.busy;
      $('updateDiscard').hidden=!state.ready;$('updateDiscard').disabled=state.busy||state.phase==='awaiting_user';
      $('updateForget').hidden=!state.pair;$('updateForget').disabled=state.busy||!!state.ready;
      $('updatePairFile').disabled=state.busy||!!state.ready;
    }});
  for(const [id,method] of Object.entries({updateScan:'scan',updateCheck:'check',updateDownload:'download',updateCancel:'cancel',updateInstall:'install',updatePermission:'openPermission',updateDiscard:'discard',updateForget:'forget'})){
    $(id).onclick=()=>{void controller[method]().catch(()=>{});};
  }
  $('updatePairFile').onchange=async e=>{
    const file=e.target.files[0];e.target.value='';if(!file)return;
    if(file.size>8192){$('updateStatus').textContent='配对文件太大，请使用电脑刚生成的文件。';return;}
    try{await controller.importPayload(await file.text());}catch{$('updateStatus').textContent='配对没有完成。';}
  };
  void controller.init();
  let appListener;
  void App.addListener('appStateChange',e=>{if(e.isActive)void controller.resume().catch(()=>{});}).then(h=>appListener=h);
  window.addEventListener('pagehide',()=>{answer(false);void controller.destroy();void appListener?.remove();},{once:true});
}
