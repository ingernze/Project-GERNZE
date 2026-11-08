const fs=require('fs'),path=require('path');
async function check(root=path.resolve(__dirname,'..')){
 const {validateUpdateLog}=await import('../src/update-log.mjs');
 const text=fs.readFileSync(path.join(root,'www/update-log.json'),'utf8');if(Buffer.byteLength(text)>8192)throw Error('随包日志超过8192字节。');
 const log=validateUpdateLog(JSON.parse(text)),gradle=fs.readFileSync(path.join(root,'android/app/build.gradle'),'utf8');
 const name=gradle.match(/versionName\s+["']([^"']+)["']/)?.[1],code=Number(gradle.match(/versionCode\s+(\d+)/)?.[1]);
 if(log.versionName!==name||log.versionCode!==code)throw Error('随包日志与Android构建版本不一致。');
 console.log('PASS update-log '+name+'/'+code+' (candidate, not installed verification)');return log;
}
module.exports=check;
if(require.main===module)check(process.argv[2]).catch(e=>{console.error(e.message);process.exitCode=1;});
