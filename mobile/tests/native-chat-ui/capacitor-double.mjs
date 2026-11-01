export const Capacitor={isNativePlatform:()=>true,getPlatform:()=> 'android'};
export function registerPlugin(name){
 if(name==='HebaoChat')return window.__nativeUiBridge;
 if(name==='HebaoUpdateTransport')return new Proxy({},{get:(_,method)=>()=>{throw Error('联调禁止电脑同步：'+String(method));}});
 throw Error('未列入联调的原生插件：'+name);
}
