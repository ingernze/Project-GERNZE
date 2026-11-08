package com.gernze.companion;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONArray;
import org.json.JSONObject;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Narrow native bridge: the key never returns to the web page. No tools or startup calls. */
@CapacitorPlugin(name="HebaoChat")
public final class LibaoChatPlugin extends Plugin {
    private static final String ALIAS="hebao.chat.config.v1";
    private static final int MAX_PROFILES=8;
    private static final int STANDARD_REQUEST_BYTES=65536, DEEPSEEK_REQUEST_BYTES=131072;
    private static final String WEB_TOOL="search_public_web";
    private final Object configLock=new Object();
    private final ExecutorService io=Executors.newFixedThreadPool(2);
    private final ScheduledExecutorService clock=Executors.newSingleThreadScheduledExecutor();
    private final AtomicReference<Task> active=new AtomicReference<>();
    private static final class Task {
        final String id; volatile boolean cancelled; volatile HttpsURLConnection connection;
        Task(String id){this.id=id;}
        void stop(){cancelled=true;HttpsURLConnection c=connection;if(c!=null)c.disconnect();}
    }
    private final AtomicReference<Task> balanceActive=new AtomicReference<>();
    private long configGeneration=0;
    private static boolean balanceSupported(JSONObject config) throws Exception {
        URI uri=new URI(config.getString("endpoint"));
        return "https".equals(uri.getScheme())&&"api.deepseek.com".equalsIgnoreCase(uri.getHost())&&(uri.getPort()==-1||uri.getPort()==443)&&!config.optString("key","").isEmpty();
    }
    private void stopBalance(){Task t=balanceActive.get();if(t!=null)t.stop();}
    @PluginMethod public void cancelBalance(PluginCall call){stopBalance();call.resolve();}
    @PluginMethod public void getBalance(PluginCall call){
        Task task=new Task("balance");if(!balanceActive.compareAndSet(null,task)){call.reject("正在查询余额，请稍等。","busy");return;}
        io.execute(()->{
            ScheduledFuture<?> deadline=clock.schedule(task::stop,15,TimeUnit.SECONDS);
            try{
                JSONObject config;long generation;synchronized(configLock){config=readConfig();generation=configGeneration;}
                if(!balanceSupported(config)){call.reject("请先保存 DeepSeek 官方接口及密钥。","not_supported");return;}
                if(task.cancelled)throw new InterruptedException();
                HttpsURLConnection c=(HttpsURLConnection)new URI("https://api.deepseek.com/user/balance").toURL().openConnection();task.connection=c;
                c.setInstanceFollowRedirects(false);c.setConnectTimeout(8000);c.setReadTimeout(8000);c.setRequestMethod("GET");
                c.setRequestProperty("Authorization","Bearer "+config.getString("key"));
                if(task.cancelled)throw new InterruptedException();int code=c.getResponseCode();
                if(code!=200){call.reject(code==401||code==403?"密钥未通过，请检查聊天配置。":"余额查询未完成（HTTP "+code+"）。","provider_error");return;}
                ByteArrayOutputStream buffer=new ByteArrayOutputStream();
                try(InputStream in=c.getInputStream()){byte[] chunk=new byte[4096];int n;while((n=in.read(chunk))!=-1){if(task.cancelled)throw new InterruptedException();if(buffer.size()+n>65536)throw new IllegalArgumentException();buffer.write(chunk,0,n);}}
                JSONObject data=new JSONObject(buffer.toString("UTF-8"));Object available=data.get("is_available");if(!(available instanceof Boolean))throw new IllegalArgumentException();
                JSONArray rows=data.getJSONArray("balance_infos"),balances=new JSONArray();if(rows.length()>20)throw new IllegalArgumentException();
                for(int i=0;i<rows.length();i++){
                    JSONObject row=rows.getJSONObject(i),item=new JSONObject();String currency=row.getString("currency");if(!currency.matches("[A-Z]{3}"))throw new IllegalArgumentException();item.put("currency",currency);
                    String[] fields={"total_balance","granted_balance","topped_up_balance"},names={"total","granted","paid"};
                    for(int j=0;j<fields.length;j++){String amount=row.getString(fields[j]);if(amount.length()>50||!amount.matches("[0-9]+(?:\\.[0-9]+)?"))throw new IllegalArgumentException();item.put(names[j],new java.math.BigDecimal(amount).toPlainString());}balances.put(item);
                }
                synchronized(configLock){if(task.cancelled||generation!=configGeneration)throw new InterruptedException();JSObject result=new JSObject();result.put("available",available);result.put("balances",balances);call.resolve(result);}
            }catch(InterruptedException e){call.reject("余额查询已停止。","cancelled");}
            catch(IllegalArgumentException|org.json.JSONException e){call.reject("余额数据格式异常，请稍后刷新。","invalid_response");}
            catch(Exception e){call.reject(task.cancelled?"余额查询已停止。":"余额连接未完成，请检查网络后刷新。",task.cancelled?"cancelled":"network_error");}
            finally{deadline.cancel(false);if(task.connection!=null)task.connection.disconnect();balanceActive.compareAndSet(task,null);}
        });
    }

    private static SharedPreferences prefs(Context context){return context.getSharedPreferences("hebao_chat_private",Context.MODE_PRIVATE);}
    private static SecretKey secret(boolean create) throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(!ks.containsAlias(ALIAS)){
            if(!create)throw new IllegalStateException("stored key unavailable");
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            return generator.generateKey();
        }
        return (SecretKey)ks.getKey(ALIAS,null);
    }
    private static JSONObject readStore(Context context) throws Exception {
        String stored=prefs(context).getString("encrypted",null);
        if(stored==null)return legacyStore(new JSONObject().put("enabled",false)
            .put("endpoint","https://api.deepseek.com/chat/completions").put("model","deepseek-flash").put("key",""));
        JSONObject box=new JSONObject(stored);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,secret(false),new GCMParameterSpec(128,Base64.decode(box.getString("iv"),Base64.NO_WRAP)));
        c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
        JSONObject saved=new JSONObject(new String(c.doFinal(Base64.decode(box.getString("ciphertext"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
        return saved.has("profiles")?saved:legacyStore(saved);
    }
    private static JSONObject legacyStore(JSONObject config) throws Exception {
        config.put("id","default").put("name","当前连接");
        return new JSONObject().put("activeId","default").put("profiles",new JSONArray().put(config));
    }
    private static JSONObject profile(JSONObject store,String id) throws Exception {
        JSONArray rows=store.getJSONArray("profiles");
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);
            if(id.equals(row.getString("id")))return row;
        }
        throw new IllegalArgumentException();
    }
    private static JSONObject activeProfile(JSONObject store) throws Exception {
        return profile(store,store.getString("activeId"));
    }
    private JSONObject readStore() throws Exception { return readStore(getContext()); }
    // Native-only. Never return the credential to the WebView or to an arbitrary provider.
    static String officialSearchKey(Context context) throws Exception {
        JSONObject config=activeProfile(readStore(context));
        if(!config.optBoolean("enabled"))return "";
        String address=config.getString("endpoint");
        endpoint(address);
        URI url=new URI(address);
        return officialDeepSeek(url)?config.optString("key",""):"";
    }
    private static boolean officialDeepSeek(URI url) {
        return "https".equals(url.getScheme())&&"api.deepseek.com".equalsIgnoreCase(url.getHost())&&
            (url.getPort()==-1||url.getPort()==443)&&("/chat/completions".equals(url.getRawPath())||"/v1/chat/completions".equals(url.getRawPath()));
    }
    private static boolean supportsWebTool(JSONObject config) throws Exception {
        if(!officialDeepSeek(new URI(config.getString("endpoint"))))return false;
        String model=config.getString("model");
        return model.equals("deepseek-flash")||model.equals("deepseek-v4-flash")||
            model.equals("deepseek-v4-flash-vision-exp")||model.equals("deepseek-v4-pro");
    }
    private static JSONArray webTools() throws Exception {
        JSONObject query=new JSONObject().put("type","string").put("description","当前用户消息里的公开关键词，可用空格组合。");
        JSONObject params=new JSONObject().put("type","object").put("properties",new JSONObject().put("query",query))
            .put("required",new JSONArray().put("query")).put("additionalProperties",false);
        JSONObject function=new JSONObject().put("name",WEB_TOOL)
            .put("description","查公开网页，只在回答需要近期或外部事实时使用。").put("parameters",params);
        return new JSONArray().put(new JSONObject().put("type","function").put("function",function));
    }
    private JSONObject readConfig() throws Exception {
        return activeProfile(readStore());
    }
    private void writeStore(JSONObject store) throws Exception {
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,secret(true));c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
        JSONObject box=new JSONObject().put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP))
            .put("ciphertext",Base64.encodeToString(c.doFinal(store.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
        if(!prefs(getContext()).edit().putString("encrypted",box.toString()).commit())throw new IllegalStateException("not saved");
        configGeneration++;stopBalance();Task t=active.get();if(t!=null)t.stop();
    }
    private JSObject publicConfig(JSONObject store) throws Exception {
        JSONObject c=activeProfile(store);
        JSONArray rows=store.getJSONArray("profiles"),profiles=new JSONArray();
        int savedCount=0;
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);
            boolean present=!row.optString("key","").isEmpty();
            if(present)savedCount++;
            profiles.put(new JSONObject().put("id",row.getString("id")).put("name",row.getString("name")).put("keyPresent",present));
        }
        boolean key=!c.optString("key","").isEmpty();JSObject value=new JSObject();
        value.put("enabled",c.getBoolean("enabled"));value.put("endpoint",c.getString("endpoint"));value.put("model",c.getString("model"));
        value.put("balanceSupported",balanceSupported(c));value.put("keyPresent",key);value.put("configured",key&&c.getBoolean("enabled"));
        boolean webTool=supportsWebTool(c);
        value.put("webToolSupported",webTool);
        value.put("activeId",c.getString("id"));value.put("profiles",profiles);
        value.put("savedCount",savedCount);value.put("profileLimit",MAX_PROFILES);return value;
    }
    private static void endpoint(String endpoint) throws Exception {
        URI u=new URI(endpoint);
        if(endpoint.length()>2048||!"https".equals(u.getScheme())||u.getHost()==null||u.getRawUserInfo()!=null||u.getRawQuery()!=null||u.getRawFragment()!=null||u.getRawPath()==null||!u.getRawPath().endsWith("/chat/completions"))throw new IllegalArgumentException();
    }
    @PluginMethod public void getConfig(PluginCall call){io.execute(()->{try{synchronized(configLock){call.resolve(publicConfig(readStore()));}}catch(Exception e){call.reject("手机聊天设置未能读取，请重新保存配置。","config_unavailable");}});}
    @PluginMethod public void configure(PluginCall call){io.execute(()->{
        try{synchronized(configLock){
            JSONObject store=readStore(),old=activeProfile(store);
            boolean create=Boolean.TRUE.equals(call.getBoolean("createProfile",false));
            String name=call.getString("profileName",create?"":old.getString("name")).trim();
            if(name.isEmpty()||name.length()>48||name.chars().anyMatch(Character::isISOControl))throw new IllegalArgumentException();
            String url=call.getString("endpoint","").trim(),model=call.getString("model","").trim(),key=call.getString("key","").trim();
            endpoint(url);
            if(model.isEmpty()||model.length()>150||model.chars().anyMatch(c->c<32)||key.length()>4096||key.chars().anyMatch(c->c<33||c>126))throw new IllegalArgumentException();
            if(!create&&key.isEmpty()&&url.equals(old.getString("endpoint")))key=old.optString("key","");
            boolean enabled=Boolean.TRUE.equals(call.getBoolean("enabled",false));
            if((enabled||create)&&key.isEmpty()){call.reject("请在手机设置中填写API密钥。","key_required");return;}
            JSONObject next=old;
            if(create){
                JSONArray profiles=store.getJSONArray("profiles");
                if(profiles.length()>=MAX_PROFILES){call.reject("聊天连接数量已达上限。","profile_limit");return;}
                String id=UUID.randomUUID().toString();
                next=new JSONObject().put("id",id);
                profiles.put(next);store.put("activeId",id);
            }
            next.put("name",name).put("endpoint",url).put("model",model).put("enabled",enabled).put("key",key);
            writeStore(store);call.resolve(publicConfig(store));
        }}catch(IllegalArgumentException e){call.reject("请检查连接名称、HTTPS完整接口地址、模型名称和密钥。","invalid_config");}
        catch(Exception e){call.reject("聊天设置保存失败，未启用新配置。","config_unavailable");}
    });}
    @PluginMethod public void switchProfile(PluginCall call){io.execute(()->{try{synchronized(configLock){
        JSONObject store=readStore();
        String id=call.getString("profileId","");
        profile(store,id);
        if(!id.equals(store.getString("activeId"))){store.put("activeId",id);writeStore(store);}
        call.resolve(publicConfig(store));
    }}catch(Exception e){call.reject("未能切换聊天连接。","config_unavailable");}});}
    @PluginMethod public void deleteKey(PluginCall call){io.execute(()->{try{synchronized(configLock){
        JSONObject store=readStore(),c=activeProfile(store);c.put("key","");c.put("enabled",false);writeStore(store);call.resolve(publicConfig(store));
    }}catch(Exception e){call.reject("密钥未能移除，请重试。","config_unavailable");}});}
    @PluginMethod public void cancel(PluginCall call){Task t=active.get();if(t!=null&&t.id.equals(call.getString("id","")))t.stop();JSObject r=new JSObject();r.put("cancelled",true);call.resolve(r);}
    @PluginMethod public void request(PluginCall call){
        String purpose=call.getString("purpose","chat");if(!purpose.equals("chat")&&!purpose.equals("summary")){call.reject("请求类型无效。","invalid_request");return;}
        // Missing field: legacy chat=700 / summary=500. Present values must be
        // integer JSON numbers; never coerce a boolean/string or silently default.
        Object allowance=call.getData().opt("maxTokens");
        boolean supplied=call.getData().has("maxTokens");
        if(supplied&&(!(allowance instanceof Integer||allowance instanceof Long)||
            (purpose.equals("summary")?((Number)allowance).longValue()!=500:
             (((Number)allowance).longValue()!=700&&((Number)allowance).longValue()!=1800)))){
            call.reject("输出预算无效；聊天只接受700或1800，摘要只接受500。","invalid_request");return;
        }
        Object webPermission=call.getData().opt("allowWebSearch");
        if(call.getData().has("allowWebSearch")&&(!(webPermission instanceof Boolean)||!purpose.equals("chat"))){
            call.reject("联网工具请求无效。","invalid_request");return;
        }
        final boolean allowWebSearch=Boolean.TRUE.equals(webPermission);
        final int maxTokens=supplied?((Number)allowance).intValue():(purpose.equals("summary")?500:700);
        String id=call.getString("id","");if(!id.matches("[A-Za-z0-9_-]{1,100}")){call.reject("请求编号无效。","invalid_request");return;}
        Task task=new Task(id);if(!active.compareAndSet(null,task)){call.reject("上一轮尚未结束，请稍等。","busy");return;}
        io.execute(()->{
            ScheduledFuture<?> deadline=clock.schedule(task::stop,purpose.equals("summary")?16:65,TimeUnit.SECONDS);
            try{
                JSONObject config;synchronized(configLock){config=readConfig();}
                if(!config.optBoolean("enabled")||config.optString("key").isEmpty()){call.reject("请先配置并启用手机聊天API。","not_configured");return;}
                endpoint(config.getString("endpoint"));JSONArray messages=call.getArray("messages");
                boolean webTool=supportsWebTool(config);
                int limit=webTool?DEEPSEEK_REQUEST_BYTES:STANDARD_REQUEST_BYTES;
                if(messages==null||messages.length()<2||messages.length()>1000||messages.toString().getBytes(StandardCharsets.UTF_8).length>limit)throw new IllegalArgumentException();
                for(int i=0;i<messages.length();i++){
                    JSONObject m=messages.getJSONObject(i);String role=m.getString("role");
                    if(m.length()!=2||!role.equals(i==0?"system":i%2==1?"user":"assistant")||!(m.get("content") instanceof String)||m.getString("content").isEmpty())throw new IllegalArgumentException();
                }
                if(!messages.getJSONObject(messages.length()-1).getString("role").equals("user"))throw new IllegalArgumentException();
                JSONObject payload=new JSONObject().put("model",config.getString("model")).put("messages",messages).put("stream",false).put("max_tokens",maxTokens);
                // This optional official-provider switch matches the desktop adapter; other APIs receive standard fields only.
                if("api.deepseek.com".equalsIgnoreCase(new URI(config.getString("endpoint")).getHost()))payload.put("thinking",new JSONObject().put("type","disabled"));
                if(allowWebSearch&&webTool)payload.put("tools",webTools()).put("tool_choice","auto");
                if(task.cancelled)throw new InterruptedException();
                HttpsURLConnection c=(HttpsURLConnection)new URI(config.getString("endpoint")).toURL().openConnection();task.connection=c;
                c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(60000);c.setRequestMethod("POST");c.setDoOutput(true);
                c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Authorization","Bearer "+config.getString("key"));
                byte[] body=payload.toString().getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(body.length);
                if(task.cancelled)throw new InterruptedException();
                try(java.io.OutputStream out=c.getOutputStream()){out.write(body);}
                int status=c.getResponseCode();
                if(task.cancelled)throw new InterruptedException();
                if(status<200||status>=300){call.reject(status==401||status==403?"服务未接受密钥，请检查手机配置。":status==429?"服务暂时限流或额度不足，请稍后重试。":"服务返回错误，请检查接口与模型（HTTP "+status+"）。","provider_error");return;}
                ByteArrayOutputStream buffer=new ByteArrayOutputStream();
                try(InputStream in=c.getInputStream()){
                    byte[] chunk=new byte[8192];int n;
                    while((n=in.read(chunk))!=-1){if(task.cancelled)throw new InterruptedException();if(buffer.size()+n>1048576)throw new IllegalArgumentException();buffer.write(chunk,0,n);}
                }
                if(task.cancelled)throw new InterruptedException();
                JSObject result=new JSObject();result.put("data",new JSONObject(buffer.toString("UTF-8")));
                deadline.cancel(false);
                c.disconnect();task.connection=null;
                // Release the native request slot before a valid tool result can trigger a follow-up.
                synchronized(configLock){
                    if(task.cancelled)throw new InterruptedException();
                    active.compareAndSet(task,null);
                    call.resolve(result);
                }
            }catch(InterruptedException e){call.reject("已停止等待本轮回复。","cancelled");}
            catch(IllegalArgumentException e){call.reject("请求或服务回复超过限制。","invalid_request");}
            catch(Exception e){call.reject(task.cancelled?"已停止等待本轮回复。":"连接未完成，请检查网络后重试。",task.cancelled?"cancelled":"network_error");}
            finally{deadline.cancel(false);if(task.connection!=null)task.connection.disconnect();active.compareAndSet(task,null);}
        });
    }
    @Override protected void handleOnPause(){stopBalance();super.handleOnPause();}
    @Override protected void handleOnDestroy(){stopBalance();Task t=active.get();if(t!=null)t.stop();io.shutdownNow();clock.shutdownNow();super.handleOnDestroy();}
}
