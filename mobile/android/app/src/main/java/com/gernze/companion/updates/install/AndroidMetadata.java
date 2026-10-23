package com.gernze.companion.updates.install;

import android.content.Context;
import android.content.pm.*;
import android.content.res.XmlResourceParser;
import android.os.Build;
import java.io.File;
import java.security.MessageDigest;
import java.util.*;
import org.xmlpull.v1.XmlPullParser;

final class AndroidMetadata {
    private static int flags(){return Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;}
    static Rules.Metadata installed(Context c)throws Exception{
        return from(c.getPackageManager().getPackageInfo(c.getPackageName(),flags()),false);
    }
    static Rules.Metadata archive(Context c,File file)throws Exception{
        // Read the real binary manifest's split/minSdk facts even on platforms whose
        // PackageManager rejects an archive immediately for too-high minSdk.
        // A fresh public-API object avoids inheriting the host's split/overlay paths.
        ApplicationInfo holder=new ApplicationInfo();holder.packageName=c.getPackageName();holder.uid=android.os.Process.myUid();
        holder.targetSdkVersion=c.getApplicationInfo().targetSdkVersion;
        holder.sourceDir=file.getAbsolutePath();holder.publicSourceDir=file.getAbsolutePath();
        boolean split=false,manifest=false;int minSdk=1;
        try(XmlResourceParser x=c.getPackageManager().getResourcesForApplication(holder).getAssets().openXmlResourceParser("AndroidManifest.xml")){
            int type;while((type=x.next())!=XmlPullParser.END_DOCUMENT){if(type!=XmlPullParser.START_TAG)continue;
                if("manifest".equals(x.getName())){manifest=true;String name=x.getAttributeValue(null,"split");split|=name!=null&&!name.isEmpty();}
                if("uses-sdk".equals(x.getName()))minSdk=x.getAttributeIntValue("http://schemas.android.com/apk/res/android","minSdkVersion",1);
                split|="uses-split".equals(x.getName())||x.getAttributeBooleanValue("http://schemas.android.com/apk/res/android","isSplitRequired",false)||x.getAttributeBooleanValue(null,"isSplitRequired",false);
            }
        }
        Rules.require(manifest&&!split,"invalid_apk");Rules.require(minSdk<=Build.VERSION.SDK_INT,"incompatible_sdk");
        // GET_SIGNING_CERTIFICATES/GET_SIGNATURES asks platform collection + verification.
        PackageInfo p=c.getPackageManager().getPackageArchiveInfo(file.getAbsolutePath(),flags());
        Rules.require(p!=null&&p.applicationInfo!=null,"invalid_apk");
        p.applicationInfo.sourceDir=file.getAbsolutePath();p.applicationInfo.publicSourceDir=file.getAbsolutePath();
        split=p.splitNames!=null&&p.splitNames.length>0;
        return from(p,split);
    }
    private static Rules.Metadata from(PackageInfo p,boolean split)throws Exception{
        Signature[] signatures;boolean rotation=false;
        if(Build.VERSION.SDK_INT>=28){Rules.require(p.signingInfo!=null,"invalid_apk");signatures=p.signingInfo.getApkContentsSigners();rotation=p.signingInfo.hasPastSigningCertificates();}
        else signatures=p.signatures;
        Rules.require(signatures!=null&&signatures.length>0,"invalid_apk");
        TreeSet<String>s=new TreeSet<>();for(Signature sig:signatures)s.add(Rules.encode(MessageDigest.getInstance("SHA-256").digest(sig.toByteArray())));
        long code=Build.VERSION.SDK_INT>=28?p.getLongVersionCode():p.versionCode;
        Rules.require(code>0&&code<=Rules.MAX_SAFE,"invalid_apk");
        return new Rules.Metadata(p.packageName,code,p.versionName,p.applicationInfo.minSdkVersion,s,split,rotation);
    }
}
