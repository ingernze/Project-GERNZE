package com.gernze.companion.updates.transport;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONArray;
import org.json.JSONObject;

/** Keystore-encrypted credentials in app no-backup storage, never JS preferences. */
final class SecurePairStore {
    private final AtomicFile file;
    private final String alias="hebao-update-transport-aes-v1";
    private JSONObject state;
    SecurePairStore(Context context) throws Exception {
        File directory=context.getNoBackupFilesDir().getCanonicalFile();
        File path=new File(directory,"hebao-update-pairing.enc");
        TransportRules.require(path.getCanonicalFile().equals(path.getAbsoluteFile()),"private_storage_failed");
        file=new AtomicFile(path);
        if(path.exists()){
            try(FileInputStream in=file.openRead()){
                ByteArrayOutputStream b=new ByteArrayOutputStream();byte[] block=new byte[4096];int n;
                while((n=in.read(block))!=-1){TransportRules.require(b.size()+n<=65536,"private_storage_failed");b.write(block,0,n);}
                JSONObject sealed=TransportRules.parse(b.toString("UTF-8"),65536);
                TransportRules.keys(sealed,"iv","ciphertext");
                Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
                c.init(Cipher.DECRYPT_MODE,key(false),new GCMParameterSpec(128,Base64.decode(sealed.getString("iv"),Base64.NO_WRAP)));
                state=TransportRules.parse(new String(c.doFinal(Base64.decode(sealed.getString("ciphertext"),Base64.NO_WRAP)),StandardCharsets.UTF_8),65536);
            }
            TransportRules.keys(state,"deviceId","pairs");TransportRules.uuid(state.getString("deviceId"));
            TransportRules.require(state.get("pairs") instanceof JSONArray&&state.getJSONArray("pairs").length()<=8,"private_storage_failed");
        }else{
            state=new JSONObject().put("deviceId",UUID.randomUUID().toString()).put("pairs",new JSONArray());persist(state);
        }
    }
    private SecretKey key(boolean create) throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(!ks.containsAlias(alias)){
            TransportRules.require(create,"private_storage_failed");
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build());
            generator.generateKey();
        }
        return (SecretKey)ks.getKey(alias,null);
    }
    private void persist(JSONObject next) throws Exception {
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key(true));
        byte[] encrypted=c.doFinal(next.toString().getBytes(StandardCharsets.UTF_8));
        JSONObject sealed=new JSONObject().put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP))
            .put("ciphertext",Base64.encodeToString(encrypted,Base64.NO_WRAP));
        FileOutputStream out=null;
        try{out=file.startWrite();out.write(sealed.toString().getBytes(StandardCharsets.UTF_8));file.finishWrite(out);}
        catch(Exception e){if(out!=null)file.failWrite(out);throw e;}
    }
    synchronized String deviceId() throws Exception{return state.getString("deviceId");}
    synchronized JSONObject get(String pairingId) throws Exception {
        TransportRules.uuid(pairingId);
        JSONArray a=state.getJSONArray("pairs");
        for(int i=0;i<a.length();i++)if(a.getJSONObject(i).getString("pairingId").equals(pairingId))return new JSONObject(a.getJSONObject(i).toString());
        throw new TransportRules.Failure("unpaired");
    }
    synchronized void checkCapacity(JSONObject payload) throws Exception {
        JSONArray a=state.getJSONArray("pairs");
        if(a.length()<8)return;
        for(int i=0;i<a.length();i++)if(a.getJSONObject(i).getString("serverId").equals(payload.getString("serverId")))return;
        throw new TransportRules.Failure("busy");
    }
    synchronized void put(JSONObject payload,JSONObject answer) throws Exception {
        checkCapacity(payload);
        JSONObject next=new JSONObject(state.toString());JSONArray old=next.getJSONArray("pairs"),a=new JSONArray();
        for(int i=0;i<old.length();i++)if(!old.getJSONObject(i).getString("serverId").equals(payload.getString("serverId")))a.put(old.get(i));
        JSONObject p=new JSONObject();
        for(String k:new String[]{"serverId","host","port","certificateDer","certificateSha256"})p.put(k,payload.get(k));
        p.put("pairingId",answer.getString("pairingId")).put("token",answer.getString("token"));a.put(p);
        next.put("pairs",a);try{persist(next);}catch(Exception e){throw new TransportRules.Failure("private_storage_failed");}state=next;
    }
    synchronized void remove(String pairingId) throws Exception {
        JSONObject next=new JSONObject(state.toString());JSONArray old=next.getJSONArray("pairs"),a=new JSONArray();
        for(int i=0;i<old.length();i++)if(!old.getJSONObject(i).getString("pairingId").equals(pairingId))a.put(old.get(i));
        next.put("pairs",a);try{persist(next);}catch(Exception e){throw new TransportRules.Failure("private_storage_failed");}state=next;
    }
    synchronized boolean current(JSONObject p){
        try{return get(p.getString("pairingId")).getString("token").equals(p.getString("token"));}
        catch(Exception e){return false;}
    }
}
