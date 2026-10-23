package com.gernze.companion.updates.install;

import android.content.Context;
import android.os.ParcelFileDescriptor;
import android.system.*;
import java.io.*;

/** Opens a directory anchor then O_NOFOLLOW regular children; never resolves caller paths. */
final class CacheVerifier {
    static final class Verified implements AutoCloseable{
        final String id;final Rules.Release release;final File snapshot;
        Verified(String id,Rules.Release release,File snapshot){this.id=id;this.release=release;this.snapshot=snapshot;}
        public void close(){snapshot.delete();}
    }
    static ParcelFileDescriptor directory(Context c)throws Exception{
        File cache=c.getCacheDir().getCanonicalFile();File base=new File(cache,"hebao-updates");
        FileDescriptor fd=Os.open(base.getPath(),OsConstants.O_RDONLY|OsConstants.O_NONBLOCK|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
        try{StructStat s=Os.fstat(fd);Rules.require(OsConstants.S_ISDIR(s.st_mode)&&s.st_uid==android.os.Process.myUid(),"integrity_failed");return ParcelFileDescriptor.dup(fd);}
        finally{Os.close(fd);}
    }
    static FileInputStream child(ParcelFileDescriptor dir,String id,String suffix,long max)throws Exception{
        Rules.uuid(id);Rules.require(".apk".equals(suffix)||".json".equals(suffix),"invalid_input");
        FileDescriptor fd=Os.open("/proc/self/fd/"+dir.getFd()+"/"+id+suffix,OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
        try{StructStat s=Os.fstat(fd);Rules.require(OsConstants.S_ISREG(s.st_mode)&&s.st_uid==android.os.Process.myUid()&&s.st_nlink==1&&s.st_size>0&&s.st_size<=max,"integrity_failed");}
        catch(Exception e){Os.close(fd);throw e;}
        return new FileInputStream(fd);
    }
    static Verified verify(Context c,String id)throws Exception{
        Rules.uuid(id);File snapshot=null;
        try(ParcelFileDescriptor dir=directory(c)){
            Rules.Release release;
            try(InputStream json=child(dir,id,".json",16384)){release=Rules.sidecar(StrictJson.read(json),id);}
            File own=new File(c.getNoBackupFilesDir().getCanonicalFile(),"hebao-update-installer");
            Rules.require(own.isDirectory()||own.mkdir(),"integrity_failed");
            Rules.require(own.getCanonicalFile().equals(own.getAbsoluteFile()),"integrity_failed");Os.chmod(own.getPath(),0700);
            File[] stale=own.listFiles();if(stale!=null)for(File f:stale){
                if(f.getName().startsWith("verified-")&&f.getName().endsWith(".apk"))f.delete();
            } // Serialized native worker: only orphan snapshots can exist before this verification.
            snapshot=File.createTempFile("verified-",".apk",own);
            try(InputStream in=child(dir,id,".apk",Rules.MAX_SIZE);FileOutputStream out=new FileOutputStream(snapshot)){
                Rules.require(Rules.digest(in,out,release.size).equals(release.sha256),"integrity_failed");out.getFD().sync();
            }
            Os.chmod(snapshot.getPath(),0400);
            Rules.validate(release,AndroidMetadata.installed(c),AndroidMetadata.archive(c,snapshot),android.os.Build.VERSION.SDK_INT);
            return new Verified(id,release,snapshot);
        }catch(Exception e){if(snapshot!=null)snapshot.delete();throw e;}
    }
    static void discardCandidate(Context c,String id)throws Exception{
        Rules.uuid(id);
        try(ParcelFileDescriptor dir=directory(c)){
            for(String suffix:new String[]{".json",".apk"}){
                String path="/proc/self/fd/"+dir.getFd()+"/"+id+suffix;
                try{
                    StructStat stat=Os.lstat(path);
                    Rules.require(OsConstants.S_ISREG(stat.st_mode)&&stat.st_uid==android.os.Process.myUid()&&stat.st_nlink==1,"integrity_failed");
                    Os.remove(path);
                }catch(ErrnoException missing){if(missing.errno!=OsConstants.ENOENT)throw missing;}
            }
        }catch(ErrnoException missing){if(missing.errno!=OsConstants.ENOENT)throw missing;}
    }
    static void cleanupConfirmed(Context c,String id){
        // Only called after actual PackageManager identity/version/cert confirmation.
        try(ParcelFileDescriptor dir=directory(c)){
            Rules.uuid(id);for(String suffix:new String[]{".json",".apk"})Os.remove("/proc/self/fd/"+dir.getFd()+"/"+id+suffix);
        }catch(Exception ignored){/* Retention is safer than widening deletion. Host may retry maintenance. */}
    }
}
