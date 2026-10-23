// Capacitor core 8.5.3 is supplied by the host; no network, downloader or web installer fallback.
import {registerPlugin} from '@capacitor/core';
const native=registerPlugin('HebaoUpdateInstaller');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function input(value){if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==1||!Object.hasOwn(value,'downloadId')||typeof value.downloadId!=='string'||!UUID.test(value.downloadId)){const e=new TypeError('更新标识无效');e.code='invalid_input';throw e;}return {downloadId:value.downloadId};}
export const updateInstaller=Object.freeze({
  getInstalled:()=>native.getInstalled(),
  inspect:options=>native.inspect(input(options)),
  discard:options=>native.discard(input(options)),
  getInstallPermission:()=>native.getInstallPermission(),
  openInstallPermissionSettings:()=>native.openInstallPermissionSettings(),
  install:options=>native.install(input(options)),
  recoverInstallState:()=>native.recoverInstallState(),
  addStateListener:listener=>native.addListener('updateInstallState',listener)
});
