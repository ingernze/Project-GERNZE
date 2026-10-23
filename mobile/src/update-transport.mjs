import { Capacitor, registerPlugin } from '@capacitor/core';

const transport = registerPlugin('HebaoUpdateTransport');
export function createUpdateTransport({ native = Capacitor, plugin = transport } = {}) {
  const requireNative = () => {
    if (!native.isNativePlatform() || native.getPlatform() !== 'android') {
      const error = new Error('请在手机安装版中检查更新。');
      error.code = 'unavailable'; throw error;
    }
  };
  return Object.freeze({
    // Call pair only AFTER the mainline scan UI shows host/certificate and the
    // user explicitly confirms. No camera permission or scan UI in this module.
    async pair(payload) { requireNative(); return plugin.pair({ payload }); },
    async getRelease(pairingId) { requireNative(); return plugin.getRelease({ pairingId }); },
    async download(pairingId, artifactId, downloadId) {
      requireNative(); return plugin.download({ pairingId, artifactId, downloadId });
    },
    async cancel(downloadId) { requireNative(); return plugin.cancel({ downloadId }); },
    async forgetPairing(pairingId) { requireNative(); return plugin.forgetPairing({ pairingId }); },
    async onProgress(callback) { requireNative(); return plugin.addListener('updateProgress', callback); },
  });
}
