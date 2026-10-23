package com.gernze.companion.updates.transport;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.net.Socket;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.SSLException;
import org.json.JSONObject;

@CapacitorPlugin(name="HebaoUpdateTransport")
public class LibaoUpdateTransport extends Plugin {
    private final Object gate=new Object(),storeLock=new Object();
    private final Handler main=new Handler(Looper.getMainLooper());
    private final Map<String,Job> jobs=new HashMap<>();
    private final ThreadPoolExecutor workers=new ThreadPoolExecutor(3,3,0L,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(16));
    private SecurePairStore store;
    private boolean active=true,destroyed=false,pairingBusy=false;
    private long epoch=0;
    private interface Work {JSObject run(Job job) throws Exception;}
    private SecurePairStore store() throws Exception {
        synchronized(storeLock){
            try{if(store==null)store=new SecurePairStore(getContext());return store;}
            catch(Exception e){throw new TransportRules.Failure("private_storage_failed");}
        }
    }
    private final class Job implements PinnedHttp.Control {
        final String key,downloadId,pairingId;
        final PluginCall call;
        final long generation,deadline;
        boolean cancelled=false,settled=false,isPair=false;
        Socket connection;
        JSONObject peer;
        DownloadCache cache;
        long total=0;
        Job(PluginCall call,String key,String downloadId,String pairingId){
            this.call=call;this.key=key;this.downloadId=downloadId;this.pairingId=pairingId;generation=epoch;
            deadline=SystemClock.elapsedRealtime()+(downloadId==null?30000:1200000);
        }
        @Override public void check() throws Exception {
            synchronized(gate){TransportRules.require(!cancelled&&!destroyed&&active&&generation==epoch,"cancelled");}
            TransportRules.require(SystemClock.elapsedRealtime()<deadline,"unreachable");
            if(peer!=null)TransportRules.require(store().current(peer),"authentication_failed");
        }
        @Override public void socket(Socket s) throws Exception {
            synchronized(gate){
                if(cancelled||destroyed||!active||generation!=epoch){s.close();throw new TransportRules.Failure("cancelled");}
                connection=s;
            }
        }
        void cancel(){cancelled=true;if(connection!=null)try{connection.close();}catch(Exception ignored){}}
    }
    private void launch(PluginCall call,String downloadId,String pairingId,boolean pairing,Work work){
        Job job;
        synchronized(gate){
            if(destroyed||!active){call.reject("请回到莉宝前台重试。","cancelled");return;}
            String key=downloadId==null?UUID.randomUUID().toString():downloadId;
            if(jobs.containsKey(key)||(pairing&&pairingBusy)){call.reject("已有任务正在处理。","busy");return;}
            job=new Job(call,key,downloadId,pairingId);job.isPair=pairing;
            if(pairing)pairingBusy=true;jobs.put(key,job);
        }
        try{workers.execute(()->{
            JSObject result=null;Exception error=null;
            try{job.check();result=work.run(job);job.check();}catch(Exception e){error=e;}
            JSObject done=result;Exception failed=error;
            main.post(()->finish(job,done,failed));
        });}catch(java.util.concurrent.RejectedExecutionException e){main.post(()->finish(job,null,new TransportRules.Failure("busy")));}
    }
    private void finish(Job job,JSObject result,Exception error){
        synchronized(gate){
            if(job.settled)return;
            try{
                job.check();if(error!=null)throw error;
                if(job.cache!=null){job.cache.commit();progress(job,job.total,true);}
                job.settled=true;job.call.resolve(result);
            }catch(Exception e){job.settled=true;String code=errorCode(e);job.call.reject(message(code),code);}
            finally{
                if(job.connection!=null)try{job.connection.close();}catch(Exception ignored){}
                if(job.cache!=null)job.cache.finish();jobs.remove(job.key);if(job.isPair)pairingBusy=false;
            }
        }
    }
    private void progress(Job job,long received,boolean finalEvent){
        main.post(()->{
            synchronized(gate){
                try{
                    if(!finalEvent){job.check();if(job.settled)return;}
                    else if(!job.settled||destroyed||!active||job.generation!=epoch)return;
                    JSObject event=new JSObject();event.put("downloadId",job.downloadId);
                    event.put("receivedBytes",received);event.put("totalBytes",job.total);notifyListeners("updateProgress",event);
                }catch(Exception ignored){}
            }
        });
    }
    private static String errorCode(Exception e){
        if(e instanceof TransportRules.Failure)return ((TransportRules.Failure)e).code;
        if(e instanceof javax.net.ssl.SSLHandshakeException||e instanceof javax.net.ssl.SSLPeerUnverifiedException||e instanceof java.security.GeneralSecurityException)return "tls_mismatch";
        if(e instanceof android.system.ErrnoException||e instanceof java.io.FileNotFoundException)return "private_storage_failed";
        if(e instanceof org.json.JSONException||e instanceof IllegalArgumentException)return "invalid_input";
        return "unreachable";
    }
    private static String message(String code){
        switch(code){
            case "tls_mismatch":return "电脑证书不匹配或已失效，请核对后重新扫码。";
            case "unpaired":return "尚未配对这台电脑。";
            case "authentication_failed":return "配对授权已失效，请重新扫码。";
            case "pairing_expired":case "pairing_replayed":return "一次性配对载荷已失效，请刷新后重扫。";
            case "cancelled":return "任务已取消，请在前台重试。";
            case "integrity_failed":return "收到的更新不完整，未交付安装。";
            case "busy":return "此编号或其他任务正在处理，请使用新的下载编号。";
            case "redirect_rejected":return "电脑返回了跳转，已停止传输。";
            case "release_changed":return "电脑发布已变化，请重新检查更新。";
            case "private_storage_failed":return "私有凭据或缓存暂时不可用。";
            case "memory_failed":return "记忆没有接回，请检查电脑版本或重新同步。";
            case "memory_unavailable":return "电脑更新窗口还未启用记忆接线，请重开新版窗口。";
            case "invalid_input":return "更新参数无效。";
            default:return "无法连接已配对电脑，请确认同一网络；地址变化时请重新扫码。";
        }
    }
    private static JSObject value(String status) throws Exception {return new JSObject(new JSONObject().put("status",status).toString());}
    private static String argument(PluginCall call,String key) throws Exception{return TransportRules.uuid(TransportRules.string(call.getData(),key,36));}
    @PluginMethod public void pair(PluginCall call){
        try{
            TransportRules.keys(call.getData(),"payload");String payload=TransportRules.string(call.getData(),"payload",8192);
            launch(call,null,null,true,job->{
                JSONObject p=TransportRules.pairing(payload,true);SecurePairStore s=store();s.checkCapacity(p);
                JSONObject body=new JSONObject().put("serverId",p.getString("serverId")).put("deviceId",s.deviceId()).put("pairingSecret",p.getString("pairingSecret"));
                JSONObject answer;
                try(PinnedHttp http=new PinnedHttp(p,"POST","/v1/pair",body,job)){answer=http.json();}
                TransportRules.keys(answer,"pairingId","token","serverId");TransportRules.uuid(TransportRules.string(answer,"pairingId",36));TransportRules.token(TransportRules.string(answer,"token",43));
                TransportRules.require(TransportRules.string(answer,"serverId",36).equals(p.getString("serverId")),"tls_mismatch");
                job.check();s.put(p,answer);JSObject result=value("paired");result.put("pairingId",answer.getString("pairingId"));return result;
            });
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void getRelease(PluginCall call){
        try{
            TransportRules.keys(call.getData(),"pairingId");String id=argument(call,"pairingId");
            launch(call,null,id,false,job->{job.peer=store().get(id);JSONObject r=fetchRelease(job);JSObject result=value("available");result.put("release",r);return result;});
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    private JSONObject fetchRelease(Job job) throws Exception {
        try(PinnedHttp http=new PinnedHttp(job.peer,"GET","/v1/release",null,job)){return TransportRules.release(http.json());}
    }
    private JSONObject memoryAnswer(Job job,String method,String path,JSONObject body) throws Exception {
        if(body!=null)TransportRules.require(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=8388608,"invalid_input");
        job.peer=store().get(job.pairingId);
        try(PinnedHttp http=new PinnedHttp(job.peer,method,path,body,job)){
            JSONObject answer=http.json(8388608);
            TransportRules.require(answer.getString("serverId").equals(job.peer.getString("serverId")),"tls_mismatch");
            return answer;
        }
    }
    private void layerPost(PluginCall call,String path){
        try{TransportRules.keys(call.getData(),"pairingId","request");String id=argument(call,"pairingId");JSONObject body=call.getObject("request");TransportRules.require(body!=null,"invalid_input");
            launch(call,null,id,false,job->new JSObject(memoryAnswer(job,"POST",path,body).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void layerInfo(PluginCall call){
        try{TransportRules.keys(call.getData(),"pairingId");String id=argument(call,"pairingId");launch(call,null,id,false,job->new JSObject(memoryAnswer(job,"GET","/v1/layers/info",null).toString()));}
        catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void layerExchange(PluginCall call){layerPost(call,"/v1/layers/exchange");}
    @PluginMethod public void layerDecide(PluginCall call){call.reject("请在电脑端统一处理审查与冲突。","review_on_desktop");}
    @PluginMethod public void rawExchange(PluginCall call){layerPost(call,"/v1/raw/exchange");}
    @PluginMethod public void memoryInfo(PluginCall call){
        try{TransportRules.keys(call.getData(),"pairingId");String id=argument(call,"pairingId");
            launch(call,null,id,false,job->new JSObject(memoryAnswer(job,"GET","/v1/memory/info",null).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void memoryExchange(PluginCall call){
        try{TransportRules.keys(call.getData(),"pairingId","snapshot");String id=argument(call,"pairingId");JSONObject body=new JSONObject().put("snapshot",call.getObject("snapshot"));
            launch(call,null,id,false,job->new JSObject(memoryAnswer(job,"POST","/v1/memory/exchange",body).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void memoryDecide(PluginCall call){
        try{TransportRules.keys(call.getData(),"pairingId","decision");String id=argument(call,"pairingId");JSONObject body=call.getObject("decision");TransportRules.require(body!=null,"invalid_input");
            launch(call,null,id,false,job->new JSObject(memoryAnswer(job,"POST","/v1/memory/decide",body).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    private JSONObject codexAnswer(Job job,String path,JSONObject body) throws Exception {
        job.peer=store().get(job.pairingId);
        if(body!=null)TransportRules.require(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=4096,"invalid_input");
        try(PinnedHttp http=new PinnedHttp(job.peer,body==null?"GET":"POST",path,body,job)){
            JSONObject answer=http.json(16384);
            TransportRules.require(answer.getString("serverId").equals(job.peer.getString("serverId")),"tls_mismatch");
            return answer;
        }
    }
    @PluginMethod public void codexInfo(PluginCall call){
        try{TransportRules.keys(call.getData(),"pairingId");String id=argument(call,"pairingId");
            launch(call,null,id,false,job->new JSObject(codexAnswer(job,"/v1/codex/info",null).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    private void codexPost(PluginCall call,String path){
        try{TransportRules.keys(call.getData(),"pairingId","request");String id=argument(call,"pairingId");JSONObject body=call.getObject("request");TransportRules.require(body!=null,"invalid_input");
            launch(call,null,id,false,job->new JSObject(codexAnswer(job,path,body).toString()));
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void codexSubscription(PluginCall call){codexPost(call,"/v1/codex/subscription");}
    @PluginMethod public void codexEvents(PluginCall call){codexPost(call,"/v1/codex/events");}
    @PluginMethod public void codexAck(PluginCall call){codexPost(call,"/v1/codex/ack");}

    @PluginMethod public void download(PluginCall call){
        try{
            TransportRules.keys(call.getData(),"pairingId","artifactId","downloadId");
            String pair=argument(call,"pairingId"),artifact=argument(call,"artifactId"),id=argument(call,"downloadId");
            launch(call,id,pair,false,job->{
                job.peer=store().get(pair);JSONObject r=fetchRelease(job);
                TransportRules.require(r.getString("artifactId").equals(artifact),"release_changed");
                job.total=r.getLong("size");job.cache=new DownloadCache(getContext(),id);
                MessageDigest digest=MessageDigest.getInstance("SHA-256");long received=0,last=0;
                try(PinnedHttp http=new PinnedHttp(job.peer,"GET","/v1/artifacts/"+artifact,null,job)){
                    TransportRules.require(http.length==job.total&&"application/vnd.android.package-archive".equals(http.headers.get("content-type"))&&
                        ("\""+r.getString("sha256")+"\"").equals(http.headers.get("etag")),"integrity_failed");
                    byte[] block=new byte[65536];int n;
                    while((n=http.input.read(block))!=-1){
                        job.check();received+=n;TransportRules.require(received<=job.total,"integrity_failed");
                        try{job.cache.output.write(block,0,n);}catch(java.io.IOException e){throw new TransportRules.Failure("private_storage_failed");}digest.update(block,0,n);
                        long now=SystemClock.elapsedRealtime();if(now-last>=150){progress(job,Math.min(received,job.total-1),false);last=now;}
                    }
                }
                TransportRules.require(received==job.total&&TransportRules.hex(digest.digest()).equals(r.getString("sha256")),"integrity_failed");
                job.check();try{job.cache.stage(r,id);}catch(java.io.IOException e){throw new TransportRules.Failure("private_storage_failed");}
                JSObject result=value("downloaded");result.put("downloadId",id);return result;
            });
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void cancel(PluginCall call){
        try{
            TransportRules.keys(call.getData(),"downloadId");String id=argument(call,"downloadId");boolean cancelled=false;
            synchronized(gate){Job j=jobs.get(id);if(j!=null&&!j.settled){j.cancel();cancelled=true;}}
            JSObject result=new JSObject();result.put("cancelled",cancelled);call.resolve(result);
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    @PluginMethod public void forgetPairing(PluginCall call){
        try{
            TransportRules.keys(call.getData(),"pairingId");String id=argument(call,"pairingId");
            launch(call,null,id,true,job->{
                JSONObject p=store().get(id);
                synchronized(gate){for(Job other:jobs.values())if(other!=job&&id.equals(other.pairingId))other.cancel();}
                try(PinnedHttp http=new PinnedHttp(p,"POST","/v1/unpair",new JSONObject(),job)){
                    JSONObject answer=http.json();TransportRules.keys(answer,"status");TransportRules.require(answer.getString("status").equals("unpaired"),"integrity_failed");
                }catch(TransportRules.Failure e){if(!e.code.equals("authentication_failed"))throw e;}
                job.check();store().remove(id);return value("unpaired");
            });
        }catch(Exception e){call.reject(message(errorCode(e)),errorCode(e));}
    }
    private void suspend(boolean destroy){
        synchronized(gate){active=false;epoch++;if(destroy)destroyed=true;for(Job job:jobs.values())job.cancel();}
        if(destroy)workers.shutdown();
    }
    @Override protected void handleOnPause(){suspend(false);}
    @Override protected void handleOnResume(){synchronized(gate){if(!destroyed)active=true;}}
    @Override protected void handleOnDestroy(){suspend(true);}
}
