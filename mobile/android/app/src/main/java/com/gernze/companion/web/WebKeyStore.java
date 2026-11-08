package com.gernze.companion.web;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Separate alias/preferences. Never reads the chat configuration. */
public final class WebKeyStore {
    private final String ALIAS;
    private final Context context;
    public WebKeyStore(Context context,String provider) throws Exception {WebRules.require(provider.equals("brave")||provider.equals("tavily"),"provider_unsupported");this.context=context;this.ALIAS="gernze.web."+provider+".v1";}
    private SecretKey secret(boolean create) throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(!ks.containsAlias(ALIAS)){
            if(!create)throw new IllegalStateException();
            KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());return gen.generateKey();
        }return (SecretKey)ks.getKey(ALIAS,null);
    }
    public synchronized String read() throws Exception {
        String s=context.getSharedPreferences(ALIAS,Context.MODE_PRIVATE).getString("sealed",null);if(s==null)return "";
        JSONObject box=new JSONObject(s);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,secret(false),new GCMParameterSpec(128,Base64.decode(box.getString("iv"),Base64.NO_WRAP)));
        c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));return new String(c.doFinal(Base64.decode(box.getString("data"),Base64.NO_WRAP)),StandardCharsets.UTF_8);
    }
    public synchronized void write(String value) throws Exception {
        WebRules.require(value!=null&&value.matches("[!-~]{8,512}"),"invalid_key");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,secret(true));c.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
        JSONObject box=new JSONObject().put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP))
            .put("data",Base64.encodeToString(c.doFinal(value.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
        if(!context.getSharedPreferences(ALIAS,Context.MODE_PRIVATE).edit().putString("sealed",box.toString()).commit())throw new IllegalStateException();
    }
    public synchronized void clear() throws Exception {
        if(!context.getSharedPreferences(ALIAS,Context.MODE_PRIVATE).edit().remove("sealed").commit())throw new IllegalStateException();
    }
}
