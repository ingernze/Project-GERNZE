package com.gernze.companion;

import com.getcapacitor.*;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.gernze.companion.web.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;

/** No startup requests, arbitrary method/header API, cookies, uploads or model tools. */
@CapacitorPlugin(name="LibaoWeb")
public final class LibaoWebPlugin extends Plugin {
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService clock=Executors.newSingleThreadScheduledExecutor();
    private final AtomicReference<WebHttp.Task> active=new AtomicReference<>();
    private final LinkedHashSet<String> cancelled=new LinkedHashSet<>();
    private final AtomicLong lifecycleGeneration=new AtomicLong();
    private volatile boolean foreground=true,closed;
    private final AtomicReference<PluginCall> completion=new AtomicReference<>();
    private String selection(){
        String p=getContext().getSharedPreferences("gernze.web.provider.v2",0).getString("selected","auto");
        return p.equals("brave")||p.equals("tavily")||p.equals("none")?p:"auto";
    }
    private WebKeyStore store(String p)throws Exception{return new WebKeyStore(getContext(),p);}
    private void select(String p)throws Exception{if(!getContext().getSharedPreferences("gernze.web.provider.v2",0).edit().putString("selected",p).commit())throw new IllegalStateException();}
    private static final class SearchAccess {
        final String provider,key;
        SearchAccess(String provider,String key){this.provider=provider;this.key=key;}
    }
    private SearchAccess searchAccess(String selection) throws Exception {
        if(selection.equals("none"))return new SearchAccess("none","");
        if(selection.equals("auto")){
            String key=LibaoChatPlugin.officialSearchKey(getContext());
            return new SearchAccess(key.isEmpty()?"none":"deepseek",key);
        }
        return new SearchAccess(selection,store(selection).read());
    }
    private JSObject config()throws Exception{
        String selected=selection();SearchAccess access=searchAccess(selected);JSObject r=new JSObject();
        r.put("selection",selected);r.put("provider",access.provider);r.put("keyPresent",!access.key.isEmpty());return r;
    }
    @PluginMethod public void getConfig(PluginCall c){try{c.resolve(config());}catch(Exception e){c.reject("搜索设置未能读取，请重新保存。","config_unavailable");}}
    @PluginMethod public void configure(PluginCall c){try{stop();String p=c.getString("provider","auto");WebRules.require(p.equals("auto")||p.equals("none")||p.equals("brave")||p.equals("tavily"),"provider_unsupported");if(p.equals("brave")||p.equals("tavily")){String key=c.getString("key","");if(!key.isEmpty())store(p).write(key);WebRules.require(!store(p).read().isEmpty(),"not_configured");}select(p);c.resolve(config());}catch(Exception e){c.reject("搜索服务未保存；须明确选择且单独配置密钥。","config_unavailable");}}
    @PluginMethod public void deleteKey(PluginCall c){try{stop();String p=selection();if(p.equals("brave")||p.equals("tavily")){store(p).clear();select("auto");}c.resolve(config());}catch(Exception e){c.reject("搜索密钥未移除。","config_unavailable");}}
    private void stop(){WebHttp.Task t=active.get();if(t!=null)t.cancel();}
    @PluginMethod public void cancel(PluginCall c){
        String id=c.getString("id","");synchronized(cancelled){if(id.matches("[A-Za-z0-9_-]{1,100}")){cancelled.add(id);while(cancelled.size()>32)cancelled.remove(cancelled.iterator().next());}}
        WebHttp.Task t=active.get();if(t!=null&&t.id.equals(id))t.cancel();c.resolve();
    }
    @PluginMethod public void run(PluginCall c){
        String id=c.getString("id",""),mode=c.getString("mode",""),value=c.getString("value","");
        if(!id.matches("[A-Za-z0-9_-]{1,100}")||!(mode.equals("read")||mode.equals("search"))){c.reject("联网输入无效。","invalid_request");return;}
        final long ownGeneration=lifecycleGeneration.get();
        if(closed||!foreground){c.reject("已离开前台，本轮联网未启动。","cancelled");return;}
        WebHttp.Task t=new WebHttp.Task(id);
        synchronized(cancelled){if(cancelled.remove(id)){c.reject("本轮联网已停止。","cancelled");return;}}
        if(!active.compareAndSet(null,t)){c.reject("上一轮联网尚在停止，请稍后再试。","busy");return;}
        completion.set(c);
        try{io.execute(()->{
            ScheduledFuture<?> deadline=null;
            try{
                if(closed||!foreground||lifecycleGeneration.get()!=ownGeneration)t.cancel();
                t.check();deadline=clock.schedule(t::expire,30,TimeUnit.SECONDS);
                SearchAccess access=mode.equals("search")?searchAccess(selection()):new SearchAccess("none","");
                t.check();
                org.json.JSONObject data=new WebEngine().run(mode,value,access.provider,access.key,t);t.check();
                if(closed||!foreground||lifecycleGeneration.get()!=ownGeneration)t.cancel();t.check();
                JSObject r=new JSObject();r.put("id",id);r.put("data",data);if(completion.compareAndSet(c,null))c.resolve(r);
            }catch(Exception e){
                String code=t.timedOut?"timeout":t.cancelled?"cancelled":e instanceof WebRules.Failure?((WebRules.Failure)e).code:"network_failed";
                if(completion.compareAndSet(c,null))c.reject("本轮联网未完成（"+code+"）。未更换代理、登录或重试。",code);
            }finally{if(deadline!=null)deadline.cancel(false);active.compareAndSet(t,null);}
        });}catch(RejectedExecutionException e){t.cancel();active.compareAndSet(t,null);if(completion.compareAndSet(c,null))c.reject("页面已关闭，本轮联网未启动。","cancelled");}
    }
    @Override protected void handleOnPause(){foreground=false;lifecycleGeneration.incrementAndGet();stop();}
    @Override protected void handleOnResume(){if(!closed)foreground=true;}
    @Override protected void handleOnDestroy(){closed=true;foreground=false;lifecycleGeneration.incrementAndGet();stop();PluginCall pending=completion.getAndSet(null);if(pending!=null)pending.reject("页面已关闭，本轮联网已停止。","cancelled");io.shutdownNow();clock.shutdownNow();}
}
