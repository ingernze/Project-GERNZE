import {Capacitor,registerPlugin} from '@capacitor/core';
import {createShakeController} from './shake-controller.mjs';

export function mountShake(){
  const settings=document.getElementById('settings');if(!settings||document.getElementById('shakeControl'))return;
  const panel=document.createElement('section');panel.className='panel';panel.id='shakeControl';
  panel.innerHTML='<h3>人物互动</h3><label style="display:flex;align-items:center;gap:10px"><input id="shakeEnabled" type="checkbox" style="width:20px;min-height:20px">明显摇晃手机时回应</label><p id="shakeHint" class="hint">仅在陪伴页前台检测，切页、锁屏和后台会停止；不影响手指拖动。</p>';
  settings.querySelector('#qualityForm').after(panel);
  const toggle=panel.querySelector('input'),hint=panel.querySelector('#shakeHint'),key='hebao.mobile.shake.enabled.v1';
  let enabled=true,shown=false,closed=false;
  try{enabled=localStorage.getItem(key)!=='off';}catch{}
  toggle.checked=enabled;
  if(!Capacitor.isNativePlatform()||Capacitor.getPlatform()!=='android'){
    toggle.disabled=true;hint.textContent='摇手机反应在安卓安装版使用；手指拖动照常可用。';return;
  }
  const controller=createShakeController({plugin:registerPlugin('HebaoShake'),
    onShake:()=>{
      if(closed||!enabled||!shown||document.hidden||document.querySelector('dialog[open]'))return;
      document.getElementById('portrait')?.contentWindow.postMessage({type:'hecate:shake'},location.origin);
    },onStatus:result=>{
      hint.textContent=result.available?'仅在陪伴页前台检测，切页、锁屏和后台会停止；不影响手指拖动。':'这台设备暂不可用摇晃检测，手指拖动仍可使用。';
    }});
  const update=()=>{void controller.setActive(!closed&&enabled&&shown&&!document.hidden);};
  const visible=e=>{shown=e.detail===true;update();};
  const visibility=()=>update();
  window.addEventListener('hebao:portrait-visible',visible);
  document.addEventListener('visibilitychange',visibility);
  toggle.onchange=()=>{enabled=toggle.checked;try{localStorage.setItem(key,enabled?'on':'off');}catch{}update();};
  void controller.init().then(update).catch(()=>{hint.textContent='摇晃检测未能启动，手指拖动仍可使用。';});
  window.addEventListener('pagehide',()=>{closed=true;window.removeEventListener('hebao:portrait-visible',visible);document.removeEventListener('visibilitychange',visibility);void controller.destroy();},{once:true});
}
