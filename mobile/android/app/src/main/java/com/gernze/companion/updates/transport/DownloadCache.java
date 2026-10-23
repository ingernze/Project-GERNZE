package com.gernze.companion.updates.transport;

import android.content.Context;
import android.system.Os;
import android.system.OsConstants;
import java.io.File;
import java.io.FileOutputStream;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONObject;

/** Single app process. Never delete or overwrite files already handed to installer. */
final class DownloadCache {
    private static final Object LOCK=new Object();
    private static final Set<String> ACTIVE=new HashSet<>(),INITIALIZED=new HashSet<>();
    final File part,apk,json,tmp;
    final FileOutputStream output;
    private final String key;
    private boolean committed=false,closed=false;
    DownloadCache(Context context,String id) throws Exception {
        TransportRules.uuid(id);File root=new File(context.getCacheDir().getCanonicalFile(),"hebao-updates");
        synchronized(LOCK){
            TransportRules.require(root.getCanonicalFile().equals(root.getAbsoluteFile()),"integrity_failed");
            TransportRules.require(root.isDirectory()||root.mkdir(),"private_storage_failed");
            key=root.getAbsolutePath()+"/"+id;
            if(INITIALIZED.add(root.getAbsolutePath())){
                File[] children=root.listFiles();int removed=0;
                if(children!=null)for(File child:children){
                    if(removed>=64)break;
                    String n=child.getName();
                    if(n.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.(part|tmp)") &&
                        !ACTIVE.contains(root.getAbsolutePath()+"/"+n.substring(0,36)) && child.getCanonicalFile().equals(child.getAbsoluteFile())){
                        if(child.delete())removed++;
                    }
                }
            }
            part=new File(root,id+".part");apk=new File(root,id+".apk");json=new File(root,id+".json");tmp=new File(root,id+".tmp");
            for(File f:new File[]{part,apk,json,tmp})TransportRules.require(f.getCanonicalFile().equals(f.getAbsoluteFile()),"integrity_failed");
            TransportRules.require(!ACTIVE.contains(key)&&!part.exists()&&!tmp.exists()&&!apk.exists()&&!json.exists(),"busy");
            ACTIVE.add(key);
            try{output=new FileOutputStream(Os.open(part.getAbsolutePath(),OsConstants.O_WRONLY|OsConstants.O_CREAT|OsConstants.O_EXCL|OsConstants.O_NOFOLLOW,0600));}
            catch(Exception e){ACTIVE.remove(key);throw e;}
        }
    }
    void stage(JSONObject release,String downloadId) throws Exception {
        output.getFD().sync();output.close();
        byte[] bytes=new JSONObject().put("contractVersion",1).put("downloadId",downloadId).put("release",release).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        try(FileOutputStream out=new FileOutputStream(Os.open(tmp.getAbsolutePath(),OsConstants.O_WRONLY|OsConstants.O_CREAT|OsConstants.O_EXCL|OsConstants.O_NOFOLLOW,0600))){
            out.write(bytes);out.getFD().sync();
        }
    }
    void commit() throws Exception {
        synchronized(LOCK){
            TransportRules.require(!closed&&!committed&&!apk.exists()&&!json.exists(),"busy");
            TransportRules.require(part.getCanonicalFile().equals(part.getAbsoluteFile())&&tmp.getCanonicalFile().equals(tmp.getAbsoluteFile()),"integrity_failed");
            Os.rename(part.getAbsolutePath(),apk.getAbsolutePath());
            try{Os.rename(tmp.getAbsolutePath(),json.getAbsolutePath());committed=true;}
            catch(Exception e){apk.delete();throw e;}
        }
    }
    void finish(){
        synchronized(LOCK){
            if(closed)return;closed=true;
            try{output.close();}catch(Exception ignored){}
            if(!committed){part.delete();tmp.delete();}
            ACTIVE.remove(key);
        }
    }
}
