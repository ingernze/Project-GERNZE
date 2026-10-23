package com.gernze.companion.updates.install;

import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.net.Uri;
import android.os.*;
import java.io.*;
import java.lang.ref.WeakReference;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;
import org.json.*;

/** One app-private serial coordinator, surviving a WebView/plugin instance. No networking. */
final class InstallEngine {
    private static InstallEngine singleton;
    static synchronized InstallEngine get(Context c){if(singleton==null)singleton=new InstallEngine(c.getApplicationContext());return singleton;}
    final ExecutorService worker=Executors.newSingleThreadExecutor();
    final Rules.Gate gate=new Rules.Gate();
    private final Context context;private final SharedPreferences prefs;private final Handler main=new Handler(Looper.getMainLooper());
    private volatile WeakReference<Activity> activity=new WeakReference<>(null);
    private volatile boolean foreground=false;private volatile Consumer<JSONObject> observer;
    private volatile String liveUri;
    private InstallEngine(Context c){context=c;prefs=c.getSharedPreferences("hebao-update-installer-v1",Context.MODE_PRIVATE);}
    void attach(Activity a,Consumer<JSONObject> listener){activity=new WeakReference<>(a);observer=listener;foreground=true;}
    void foreground(boolean value){foreground=value;}
    void detach(){foreground=false;observer=null;activity.clear();}
    String action(){return context.getPackageName()+".HEBAO_INSTALL_RESULT";}
    boolean permission(){return Build.VERSION.SDK_INT<26||context.getPackageManager().canRequestPackageInstalls();}
    JSONObject installed()throws Exception{
        Rules.Metadata m=AndroidMetadata.installed(context);return new JSONObject().put("packageName",m.packageName).put("versionCode",m.versionCode)
            .put("versionName",m.versionName).put("signerCertificateSha256",new JSONArray(m.signers)).put("apiLevel",Build.VERSION.SDK_INT);
    }
    private JSONObject read()throws Exception{String s=prefs.getString("attempt",null);JSONObject value=s==null?null:new JSONObject(s);liveUri=value==null?null:value.getString("callbackUri");return value;}
    private void save(JSONObject value)throws Exception{Rules.require(prefs.edit().putString("attempt",value.toString()).commit(),"unknown_result");liveUri=value.getString("callbackUri");}
    private Rules.Release target(JSONObject record)throws Exception{
        return Rules.release(StrictJson.read(new ByteArrayInputStream(record.getJSONObject("release").toString().getBytes(StandardCharsets.UTF_8))));
    }
    private PackageInstaller pi(){return context.getPackageManager().getPackageInstaller();}
    private PackageInstaller.SessionInfo session(JSONObject record)throws Exception{
        int id=record.getInt("sessionId");if(id<0)return null;
        PackageInstaller.SessionInfo info=pi().getSessionInfo(id);
        if(info!=null)Rules.require(context.getPackageName().equals(info.getInstallerPackageName()),"unknown_result");return info;
    }
    private JSONObject visible(JSONObject record)throws Exception{
        if(record==null)return new JSONObject().put("status","unknown").put("code","unknown_result");
        JSONObject out=new JSONObject().put("status",record.getString("status")).put("downloadId",record.getString("downloadId")).put("sessionId",record.getInt("sessionId"));
        if(record.has("code"))out.put("code",record.getString("code"));return out;
    }
    private void announce(JSONObject record)throws Exception{
        Consumer<JSONObject> listener=observer;if(listener!=null){JSONObject event=visible(record);main.post(()->{Consumer<JSONObject> current=observer;if(current==listener)current.accept(event);});}
    }
    private void set(JSONObject record,String status,String code)throws Exception{
        JSONObject actual=read();Rules.require(actual!=null&&actual.getString("callbackUri").equals(record.getString("callbackUri"))&&actual.getInt("sessionId")==record.getInt("sessionId"),"unknown_result");
        record.put("status",status);if(code!=null)record.put("code",code);else record.remove("code");save(record);announce(record);
    }
    private void discardUnsubmitted(JSONObject record)throws Exception{
        if(record==null||Build.VERSION.SDK_INT<29)return;
        int known=record.getInt("sessionId");
        // Only our own unsealed sessions for updating this same app; never touch committed work.
        for(PackageInstaller.SessionInfo info:pi().getMySessions()){
            if((known<0||info.getSessionId()==known)&&!info.isSealed()
               &&context.getPackageName().equals(info.getInstallerPackageName())
               &&context.getPackageName().equals(info.getAppPackageName()))pi().abandonSession(info.getSessionId());
        }
    }
    private void noLiveAttempt()throws Exception{
        JSONObject old=read();discardUnsubmitted(old);
        if(old!=null&&!Rules.installedTarget(target(old),AndroidMetadata.installed(context)))Rules.require(session(old)==null,"busy");
    }
    JSONObject discard(String id)throws Exception{
        noLiveAttempt();CacheVerifier.discardCandidate(context,id);
        return new JSONObject().put("status","discarded").put("downloadId",id);
    }
    JSONObject inspect(String id)throws Exception{
        noLiveAttempt();try(CacheVerifier.Verified v=CacheVerifier.verify(context,id)){
            return new JSONObject().put("status","ready").put("downloadId",id).put("release",new JSONObject(v.release.json));
        }
    }
    JSONObject install(String id)throws Exception{
        Rules.require(permission(),"permission_required");
        Activity a=activity.get();Rules.require(foreground&&a!=null&&!a.isFinishing(),"unknown_result");noLiveAttempt();
        try(CacheVerifier.Verified verified=CacheVerifier.verify(context,id)){
            Rules.require(permission(),"permission_required");
            JSONObject record=new JSONObject().put("downloadId",id).put("sessionId",-1).put("status","unknown")
                .put("release",new JSONObject(verified.release.json)).put("callbackUri","hebao-install://result/"+UUID.randomUUID());
            save(record); // Persist before creating a session; process death never causes an auto-retry.
            int sid=-1;boolean committed=false;
            try{
                PackageInstaller.SessionParams params=new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
                params.setAppPackageName(context.getPackageName());params.setSize(verified.release.size);
                if(Build.VERSION.SDK_INT>=31)params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED);
                sid=pi().createSession(params);record.put("sessionId",sid);save(record);
                try(PackageInstaller.Session s=pi().openSession(sid)){
                    try(InputStream in=new FileInputStream(verified.snapshot);OutputStream out=s.openWrite("base.apk",0,verified.release.size)){
                        // The bytes written to the session must themselves match, not just an earlier inspect.
                        Rules.require(Rules.digest(in,out,verified.release.size).equals(verified.release.sha256),"integrity_failed");s.fsync(out);
                    }
                    Rules.validate(verified.release,AndroidMetadata.installed(context),AndroidMetadata.archive(context,verified.snapshot),Build.VERSION.SDK_INT);
                    Rules.require(permission(),"permission_required");
                    Activity host=activity.get();Rules.require(foreground&&host!=null&&!host.isFinishing(),"unknown_result");
                    Intent result=new Intent(context,InstallResultReceiver.class).setAction(action()).setData(Uri.parse(record.getString("callbackUri")));
                    int flags=PendingIntent.FLAG_UPDATE_CURRENT;if(Build.VERSION.SDK_INT>=31)flags|=PendingIntent.FLAG_MUTABLE;
                    PendingIntent pending=PendingIntent.getBroadcast(context,sid,result,flags);
                    record.put("status","awaiting_user");save(record);
                    s.commit(pending.getIntentSender());committed=true;
                }
                announce(record);return visible(record);
            }catch(Exception e){
                if(!committed&&sid>=0)try{pi().abandonSession(sid);}catch(Exception ignored){}
                set(record,committed?"unknown":"failed",e instanceof Rules.Failure?((Rules.Failure)e).code:"unknown_result");throw e;
            }
        }
    }
    JSONObject recover()throws Exception{
        JSONObject record=read();if(record==null)return visible(null);discardUnsubmitted(record);
        Rules.Release release=target(record);Rules.Metadata actual=AndroidMetadata.installed(context);
        String status=Rules.recover(release,actual,session(record)!=null,record.getString("status"));
        set(record,status,"unknown".equals(status)?"unknown_result":("failed".equals(status)||"cancelled".equals(status))?record.optString("code",null):null);
        if("installed".equals(status))CacheVerifier.cleanupConfirmed(context,record.getString("downloadId"));
        // No commit, intent launch, permission request or automatic reinstall in recovery.
        return visible(record);
    }
    void result(Intent intent)throws Exception{
        JSONObject record=read();if(record==null)return;
        if(!action().equals(intent.getAction())||!record.getString("callbackUri").equals(String.valueOf(intent.getData())))return;
        int sid=intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID,-1);if(sid<0||sid!=record.getInt("sessionId"))return;
        if(Rules.installedTarget(target(record),AndroidMetadata.installed(context))){set(record,"installed",null);CacheVerifier.cleanupConfirmed(context,record.getString("downloadId"));return;}
        if("installed".equals(record.getString("status"))||"cancelled".equals(record.getString("status"))||"failed".equals(record.getString("status")))return;
        int status=intent.getIntExtra(PackageInstaller.EXTRA_STATUS,Integer.MIN_VALUE);
        if(status==PackageInstaller.STATUS_PENDING_USER_ACTION){
            Rules.require(session(record)!=null,"unknown_result");set(record,"awaiting_user",null);
            if(record.optBoolean("confirmationDispatched",false))return;
            Intent confirm;
            if(Build.VERSION.SDK_INT>=33)confirm=intent.getParcelableExtra(Intent.EXTRA_INTENT,Intent.class);
            else confirm=intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if(confirm==null){set(record,"unknown","unknown_result");return;}
            ResolveInfo resolved=context.getPackageManager().resolveActivity(confirm,PackageManager.MATCH_DEFAULT_ONLY);
            Rules.require(resolved!=null&&resolved.activityInfo!=null&&(resolved.activityInfo.applicationInfo.flags&(ApplicationInfo.FLAG_SYSTEM|ApplicationInfo.FLAG_UPDATED_SYSTEM_APP))!=0,"unknown_result");
            record.put("confirmationDispatched",true);save(record);final String expectedUri=record.getString("callbackUri");
            main.post(()->{
                if(!expectedUri.equals(liveUri))return;
                Activity host=activity.get();
                try{
                    if(!foreground||host==null||host.isFinishing())throw new IllegalStateException();
                    host.startActivity(confirm); // Only the system-supplied confirmation, from a private capability callback.
                }catch(Exception unavailable){worker.execute(()->{
                    try{pi().abandonSession(sid);set(record,"cancelled","cancelled");}
                    catch(Exception cannotAbandon){try{set(record,"unknown","unknown_result");}catch(Exception ignored){}}
                });}
            });
        }else if(status==PackageInstaller.STATUS_SUCCESS){
            // Even authenticated STATUS_SUCCESS is checked against the actual installed package.
            recover();
        }else if(status==PackageInstaller.STATUS_FAILURE_ABORTED){set(record,"cancelled","cancelled");}
        else if(status>=PackageInstaller.STATUS_FAILURE){set(record,"failed","install_failed");}
    }
}
