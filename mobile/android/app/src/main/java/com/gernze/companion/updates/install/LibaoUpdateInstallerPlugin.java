package com.gernze.companion.updates.install;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import com.getcapacitor.*;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.concurrent.Callable;
import org.json.JSONObject;

@CapacitorPlugin(name="HebaoUpdateInstaller")
public final class LibaoUpdateInstallerPlugin extends Plugin {
    private InstallEngine engine;
    private static JSObject js(JSONObject value){JSObject out=new JSObject();if(value!=null){java.util.Iterator<String> keys=value.keys();while(keys.hasNext()){String key=keys.next();try{out.put(key,value.get(key));}catch(org.json.JSONException ignored){}}}return out;}
    @Override public void load(){engine=InstallEngine.get(getContext());engine.attach(getActivity(),value->notifyListeners("updateInstallState",js(value)));}
    private String id(PluginCall call)throws Exception{
        Rules.require(call.getData().length()==1&&call.getData().has("downloadId"),"invalid_input");return Rules.uuid(call.getData().get("downloadId"));
    }
    private void empty(PluginCall c)throws Exception{Rules.require(c.getData().length()==0,"invalid_input");}
    private void run(PluginCall call,Callable<JSONObject> task){
        try{engine.gate.enter();}catch(Rules.Failure busy){call.reject("安装器正在处理其他任务","busy");return;}
        engine.worker.execute(()->{try{JSONObject value=task.call();if(value!=null)call.resolve(js(value));}
            catch(Exception e){String code=e instanceof Rules.Failure?((Rules.Failure)e).code:e instanceof SecurityException?"permission_required":e instanceof java.io.IOException||e instanceof android.system.ErrnoException?"integrity_failed":"invalid_apk";
                call.reject(message(code),code);}
            finally{engine.gate.leave();}});
    }
    private static String message(String code){
        switch(code){case "invalid_input":return "更新参数或缓存清单无效";case "permission_required":return "请先允许本应用安装更新";
            case "integrity_failed":return "安装包完整性校验失败";case "signer_mismatch":return "安装包签名不匹配";case "package_mismatch":return "安装包不属于本应用";
            case "not_newer":return "安装包不是更新版本";case "incompatible_sdk":return "安装包不兼容当前系统";case "unknown_result":return "安装结果尚不能确认，请重新核对";
            case "busy":return "安装器正在处理其他任务";default:return "安装包无法验证或安装";}
    }
    @PluginMethod public void getInstalled(PluginCall c){run(c,()->{empty(c);return engine.installed();});}
    @PluginMethod public void discard(PluginCall c){run(c,()->engine.discard(id(c)));}
    @PluginMethod public void inspect(PluginCall c){run(c,()->engine.inspect(id(c)));}
    @PluginMethod public void install(PluginCall c){run(c,()->engine.install(id(c)));}
    @PluginMethod public void getInstallPermission(PluginCall c){run(c,()->{empty(c);return new JSONObject().put("allowed",engine.permission());});}
    @PluginMethod public void recoverInstallState(PluginCall c){run(c,()->{empty(c);return engine.recover();});}
    @PluginMethod public void openInstallPermissionSettings(PluginCall c){
        run(c,()->{empty(c);if(Build.VERSION.SDK_INT>=26){
            Rules.require(getActivity()!=null&&!getActivity().isFinishing(),"unknown_result");
            getActivity().runOnUiThread(()->{try{getActivity().startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+getContext().getPackageName())));c.resolve();}
                catch(Exception e){c.reject("无法打开系统安装权限设置","permission_required");}});
            return null;
        }return new JSONObject().put("status","not_required");});
    }
    @Override protected void handleOnResume(){engine.attach(getActivity(),value->notifyListeners("updateInstallState",js(value)));engine.worker.execute(()->{try{engine.recover();}catch(Exception ignored){}});}
    @Override protected void handleOnPause(){engine.foreground(false);}
    @Override protected void handleOnDestroy(){engine.detach();}
}
