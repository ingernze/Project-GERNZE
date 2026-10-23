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

    private SharedPreferences prefs(){return getContext().getSharedPreferences("hebao_chat_private",Context.MODE_PRIVATE);}
    private SecretKey secret(boolean create) throws Exception {
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
    private JSONObject readConfig() throws Exception {
        String stored=prefs().getString("encrypted",null);
        if(stored==null)return new JSONObject().put("enabled",false).put("endpoint","https://api.deepseek.com/chat/completions").put("model","deepseek-flash").put("key","");
        JSONObject box=new JSONObject(stored);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,secret(false),new GCMParameterSpec(128,Base64.decode(box.getString("iv"),Base64.NO_WRAP)));
        c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
        return new JSONObject(new String(c.doFinal(Base64.decode(box.getString("ciphertext"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
    }
    private void writeConfig(JSONObject config) throws Exception {
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,secret(true));c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
        JSONObject box=new JSONObject().put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP))
            .put("ciphertext",Base64.encodeToString(c.doFinal(config.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
        if(!prefs().edit().putString("encrypted",box.toString()).commit())throw new IllegalStateException("not saved");
        configGeneration++;stopBalance();
    }
    private JSObject publicConfig(JSONObject c) throws Exception {
        boolean key=!c.optString("key","").isEmpty();JSObject value=new JSObject();
        value.put("enabled",c.getBoolean("enabled"));value.put("endpoint",c.getString("endpoint"));value.put("model",c.getString("model"));
        value.put("balanceSupported",balanceSupported(c));value.put("keyPresent",key);value.put("configured",key&&c.getBoolean("enabled"));return value;
    }
    private static void endpoint(String endpoint) throws Exception {
        URI u=new URI(endpoint);
        if(endpoint.length()>2048||!"https".equals(u.getScheme())||u.getHost()==null||u.getRawUserInfo()!=null||u.getRawQuery()!=null||u.getRawFragment()!=null||u.getRawPath()==null||!u.getRawPath().endsWith("/chat/completions"))throw new IllegalArgumentException();
    }
    @PluginMethod public void getConfig(PluginCall call){io.execute(()->{try{synchronized(configLock){call.resolve(publicConfig(readConfig()));}}catch(Exception e){call.reject("手机聊天设置未能读取，请重新保存配置。","config_unavailable");}});}
    @PluginMethod public void configure(PluginCall call){io.execute(()->{
        try{synchronized(configLock){
            if(active.get()!=null){call.reject("正在回复，请先停止。","busy");return;}
            JSONObject old=readConfig();String url=call.getString("endpoint","").trim(),model=call.getString("model","").trim(),key=call.getString("key","").trim();
            endpoint(url);
            if(model.isEmpty()||model.length()>150||model.chars().anyMatch(c->c<32)||key.length()>4096||key.chars().anyMatch(c->c<33||c>126))throw new IllegalArgumentException();
            if(key.isEmpty()&&url.equals(old.getString("endpoint")))key=old.optString("key","");
            boolean enabled=Boolean.TRUE.equals(call.getBoolean("enabled",false));
            if(enabled&&key.isEmpty()){call.reject("请在手机设置中填写API密钥。","key_required");return;}
            JSONObject next=new JSONObject().put("endpoint",url).put("model",model).put("enabled",enabled).put("key",key);
            writeConfig(next);call.resolve(publicConfig(next));
        }}catch(IllegalArgumentException e){call.reject("请填写HTTPS完整接口地址、模型名称和有效密钥。","invalid_config");}
        catch(Exception e){call.reject("聊天设置保存失败，未启用新配置。","config_unavailable");}
    });}
    @PluginMethod public void deleteKey(PluginCall call){io.execute(()->{try{synchronized(configLock){
        Task t=active.get();if(t!=null)t.stop();JSONObject c=readConfig();c.put("key","");c.put("enabled",false);writeConfig(c);call.resolve(publicConfig(c));
    }}catch(Exception e){call.reject("密钥未能移除，请重试。","config_unavailable");}});}
    @PluginMethod public void cancel(PluginCall call){Task t=active.get();if(t!=null&&t.id.equals(call.getString("id","")))t.stop();JSObject r=new JSObject();r.put("cancelled",true);call.resolve(r);}
    @PluginMethod public void request(PluginCall call){
        String purpose=call.getString("purpose","chat");if(!purpose.equals("chat")&&!purpose.equals("summary")){call.reject("请求类型无效。","invalid_request");return;}
        String id=call.getString("id","");if(!id.matches("[A-Za-z0-9_-]{1,100}")){call.reject("请求编号无效。","invalid_request");return;}
        Task task=new Task(id);if(!active.compareAndSet(null,task)){call.reject("上一轮尚未结束，请稍等。","busy");return;}
        io.execute(()->{
            ScheduledFuture<?> deadline=clock.schedule(task::stop,purpose.equals("summary")?16:65,TimeUnit.SECONDS);
            try{
                JSONObject config;synchronized(configLock){config=readConfig();}
                if(!config.optBoolean("enabled")||config.optString("key").isEmpty()){call.reject("请先配置并启用手机聊天API。","not_configured");return;}
                endpoint(config.getString("endpoint"));JSONArray messages=call.getArray("messages");
                if(messages==null||messages.length()<2||messages.length()>1000||messages.toString().getBytes(StandardCharsets.UTF_8).length>65536)throw new IllegalArgumentException();
                for(int i=0;i<messages.length();i++){
                    JSONObject m=messages.getJSONObject(i);String role=m.getString("role");
                    if(m.length()!=2||!role.equals(i==0?"system":i%2==1?"user":"assistant")||!(m.get("content") instanceof String)||m.getString("content").isEmpty())throw new IllegalArgumentException();
                }
                if(!messages.getJSONObject(messages.length()-1).getString("role").equals("user"))throw new IllegalArgumentException();
                JSONObject payload=new JSONObject().put("model",config.getString("model")).put("messages",messages).put("stream",false).put("max_tokens",purpose.equals("summary")?500:700);
                // This optional official-provider switch matches the desktop adapter; other APIs receive standard fields only.
                if("api.deepseek.com".equals(new URI(config.getString("endpoint")).getHost()))payload.put("thinking",new JSONObject().put("type","disabled"));
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
                JSObject result=new JSObject();result.put("data",new JSONObject(buffer.toString("UTF-8")));call.resolve(result);
            }catch(InterruptedException e){call.reject("已停止等待本轮回复。","cancelled");}
            catch(IllegalArgumentException e){call.reject("请求或服务回复超过限制。","invalid_request");}
            catch(Exception e){call.reject(task.cancelled?"已停止等待本轮回复。":"连接未完成，请检查网络后重试。",task.cancelled?"cancelled":"network_error");}
            finally{deadline.cancel(false);if(task.connection!=null)task.connection.disconnect();active.compareAndSet(task,null);}
        });
    }
    @Override protected void handleOnPause(){stopBalance();super.handleOnPause();}
    @Override protected void handleOnDestroy(){stopBalance();Task t=active.get();if(t!=null)t.stop();io.shutdownNow();clock.shutdownNow();super.handleOnDestroy();}
}
