// Coordinates the received modules; no APK bytes or pairing secrets enter storage.
export function createUpdateController({transport, installer, scanner, storage, uuid, confirmPeer, onChange=()=>{}}) {
  const key='hebao.updates.v1', validId=x=>typeof x==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(x);
  let saved={};try{saved=JSON.parse(storage.getItem(key)||'{}')||{};}catch{}
  let pair=validId(saved.pair?.pairingId)?saved.pair:null;
  let ready=validId(saved.ready?.downloadId)?saved.ready:null;
  let state={busy:false,phase:'idle',message:'电脑连上手机热点后，先扫描电脑上的配对码。',pair,ready,release:null,installed:null,progress:0,permission:false};
  let handle=null,activeId=null,cancelled=false,disposed=false;
  const emit=patch=>{state={...state,...patch,pair,ready};if(!disposed)onChange({...state});};
  function persist(){storage.setItem(key,JSON.stringify({pair,ready}));}
  const fail=(code,message)=>Object.assign(new Error(message),{code});
  const errorText=e=>({cancelled:'已取消，可重新操作。',unpaired:'配对已失效，请重新扫描电脑。',authentication_failed:'电脑已撤销配对，请重新扫描。',unreachable:'没有连上电脑，请确认电脑连着手机热点，发布窗口仍开着。',tls_mismatch:'电脑身份不一致，请在电脑上重新生成配对码后核对。',integrity_failed:'更新文件不完整，已停止。请重新下载。',private_storage_failed:'手机存储暂时不可用，请检查空间后重试。',busy:'已有更新任务，请先完成或取消。',not_newer:'这个安装包不是更新版本，请重新检查。',permission_required:'需要允许莉宝安装更新；点下面的按钮打开系统设置。',unknown_result:'安装结果尚未确认；回到莉宝后会重新核对。',package_mismatch:'这个更新不属于莉宝，已停止。',signer_mismatch:'安装包签名不一致，已停止。',pairing_expired:'配对码已过期，请在电脑上刷新。',pairing_replayed:'配对码已使用，请在电脑上刷新。',release_changed:'电脑发布的版本变了，请重新检查。',incompatible_sdk:'这个更新不兼容当前手机系统。'}[e?.code]||'操作没有完成，请重试。');
  async function run(fn){
    if(disposed)return;
    if(state.busy)throw fail('busy','已有更新任务');
    emit({busy:true});
    try{return await fn();}
    catch(e){emit({phase:e?.code==='cancelled'?'idle':'error',message:errorText(e)});return null;}
    finally{if(!disposed)emit({busy:false});}
  }
  async function pairPayload(payload){
    if(typeof payload!=='string'||new TextEncoder().encode(payload).length>8192)throw fail('invalid_input');
    let p;try{p=JSON.parse(payload);}catch{throw fail('invalid_input');}
    if(p.protocol!=='hebao-pair-v1'||!validId(p.serverId)||!/^\d{1,3}(\.\d{1,3}){3}$/.test(p.host||'')||!Number.isInteger(p.port)||!/^[0-9a-f]{64}$/.test(p.certificateSha256||''))throw fail('invalid_input');
    if(!await confirmPeer({host:p.host,port:p.port,fingerprint:p.certificateSha256}))throw fail('cancelled');
    const result=await transport.pair(payload);
    if(result?.status!=='paired'||!validId(result.pairingId))throw fail('invalid_input');
    pair={pairingId:result.pairingId,host:p.host,port:p.port,fingerprint:p.certificateSha256};persist();
    emit({phase:'paired',message:'已配对这台电脑，可以检查更新。'});return result;
  }
  async function recover(){
    // The native installer deliberately rejects parallel calls with busy.
    const installed=await installer.getInstalled();
    const permission=await installer.getInstallPermission();
    const result=await installer.recoverInstallState();
    emit({installed,permission:permission.allowed});
    applyInstallState(result);
    if(ready&&result?.status!=='awaiting_user'){
      try{const inspected=await installer.inspect({downloadId:ready.downloadId});
        if(inspected.status==='ready'){ready={downloadId:ready.downloadId,release:inspected.release};persist();emit({phase:'ready',message:'更新已下载，点“安装更新”交给系统确认。'});}
      }catch(e){
        if(e.code!=='busy'){ready=null;persist();emit({message:'之前的下载已失效，请重新检查更新。',phase:'idle'});}
      }
    }
  }
  function applyInstallState(result){
    if(!result||!['awaiting_user','installed','cancelled','failed','unknown'].includes(result.status))return;
    if(ready&&result.downloadId&&result.downloadId!==ready.downloadId)return;
    if(result.status==='installed'){
      ready=null;persist();emit({phase:'installed',message:'系统已确认更新完成。'});
    }else if(result.status==='awaiting_user')emit({phase:'awaiting_user',message:'请在系统窗口确认安装；回到莉宝后会核对结果。'});
    else if(result.status==='cancelled')emit({phase:'ready',message:'已取消安装，下载文件保留，可以再点安装。'});
    else if(result.status==='failed')emit({phase:ready?'ready':'error',message:'系统没有完成安装，可以重试。'});
    else if(result.downloadId)emit({phase:ready?'ready':'idle',message:'安装结果尚未确认，请先检查当前版本。'});
  }
  const api={
    get state(){return {...state};},
    init:()=>run(async()=>{
      handle=await installer.addStateListener(applyInstallState);
      await recover();if(!ready&&state.phase==='idle')emit({message:pair?'已记住这台电脑，连上热点后点“检查更新”。':state.message});
    }),
    scan:()=>run(async()=>{if(ready)throw fail('busy');const result=await scanner.scan();return pairPayload(result.payload);}),
    importPayload:payload=>run(()=>{if(ready)throw fail('busy');return pairPayload(payload);}),
    check:()=>run(async()=>{
      if(!pair)throw fail('unpaired');
      if(ready){emit({phase:'ready',message:'已有完整更新，请先安装，或移除这份下载后重新检查。'});return;}
      const installed=await installer.getInstalled();const result=await transport.getRelease(pair.pairingId);const r=result.release;
      if(!r||r.packageName!==installed.packageName)throw fail('package_mismatch');
      if(JSON.stringify(r.signerCertificateSha256)!==JSON.stringify(installed.signerCertificateSha256))throw fail('signer_mismatch');
      if(r.minSdkVersion>installed.apiLevel)throw fail('incompatible_sdk');
      emit({installed,release:r,phase:r.versionCode>installed.versionCode?'available':'latest',message:r.versionCode>installed.versionCode?`发现更新 ${r.versionName}，点“下载更新”继续。`:'已经是最新版本。'});
    }),
    download:()=>run(async()=>{
      if(!pair||!state.release||state.phase!=='available')throw fail('invalid_input');
      const id=uuid();activeId=id;cancelled=false;let progressHandle;
      emit({phase:'downloading',progress:0,message:'正在从电脑下载，请让莉宝保持在前台。'});
      try{
        progressHandle=await transport.onProgress(e=>{if(!disposed&&!cancelled&&activeId===id&&e.downloadId===id&&e.totalBytes>0)emit({progress:Math.min(.99,e.receivedBytes/e.totalBytes)});});
        if(cancelled)throw fail('cancelled');
        const result=await transport.download(pair.pairingId,state.release.artifactId,id);
        // A completed native handoff must be remembered even if Cancel raced its final response.
        if(result?.status!=='downloaded'||result.downloadId!==id)throw fail('integrity_failed');
        ready={downloadId:id,release:state.release};persist();
        const inspected=await installer.inspect({downloadId:id});
        if(inspected.status!=='ready')throw fail('integrity_failed');
        ready={downloadId:id,release:inspected.release};persist();
        emit({phase:'ready',progress:1,message:'下载与安装前检查完成。点“安装更新”后由系统确认。'});
      }finally{activeId=null;await progressHandle?.remove();}
    }),
    async cancel(){if(activeId){cancelled=true;const result=await transport.cancel(activeId);if(result?.cancelled)emit({message:'正在取消下载…'});}},
    install:()=>run(async()=>{
      if(!ready)throw fail('invalid_input');
      const permission=await installer.getInstallPermission();emit({permission:permission.allowed});
      if(!permission.allowed)throw fail('permission_required');
      const result=await installer.install({downloadId:ready.downloadId});applyInstallState(result);return result;
    }),
    openPermission:()=>run(()=>installer.openInstallPermissionSettings()),
    discard:()=>run(async()=>{
      if(!ready)return;
      await installer.discard({downloadId:ready.downloadId});ready=null;persist();emit({phase:'idle',release:null,progress:0,message:'已移除这份下载，可以重新检查。'});
    }),
    forget:()=>run(async()=>{
      if(!pair)return;await transport.forgetPairing(pair.pairingId);pair=null;persist();emit({phase:'idle',release:null,message:'已解除这台电脑的配对。'});
    }),
    resume:()=>run(recover),
    async destroy(){disposed=true;await api.cancel();await handle?.remove();}
  };
  return api;
}
