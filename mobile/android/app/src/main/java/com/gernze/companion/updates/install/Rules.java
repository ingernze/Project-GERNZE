package com.gernze.companion.updates.install;

import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Pure decisions. Production metadata is supplied only by AndroidMetadata, never JS. */
public final class Rules {
    public static final long MAX_SIZE=536870912L, MAX_SAFE=9007199254740991L;
    private Rules() {}
    public static final class Failure extends Exception {
        public final String code;
        public Failure(String code){super(code);this.code=code;}
    }
    public static void require(boolean condition,String code)throws Failure{if(!condition)throw new Failure(code);}
    public static String uuid(Object value)throws Failure{
        require(value instanceof String,"invalid_input");String s=(String)value;
        require(s.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")&&UUID.fromString(s).toString().equals(s),"invalid_input");return s;
    }
    static void keys(Map<?,?> m,String...names)throws Failure{require(m.keySet().equals(new HashSet<String>(Arrays.asList(names))),"invalid_input");}
    static String text(Object o,int max)throws Failure{require(o instanceof String&&!((String)o).isEmpty()&&((String)o).length()<=max,"invalid_input");return (String)o;}
    static long integer(Object o,long max)throws Failure{require(o instanceof Long||o instanceof Integer,"invalid_input");long n=((Number)o).longValue();require(n>=1&&n<=max,"invalid_input");return n;}
    static String hex(Object o)throws Failure{require(o instanceof String&&((String)o).matches("[0-9a-f]{64}"),"invalid_input");return (String)o;}
    @SuppressWarnings("unchecked") static Map<String,Object> object(Object o)throws Failure{require(o instanceof Map,"invalid_input");return (Map<String,Object>)o;}
    static List<String> certificates(Object o)throws Failure{
        require(o instanceof List&&!((List<?>)o).isEmpty()&&((List<?>)o).size()<=32,"invalid_input");
        List<String> result=new ArrayList<>();for(Object v:(List<?>)o)result.add(hex(v));
        List<String> sorted=new ArrayList<>(new TreeSet<>(result));require(result.equals(sorted),"invalid_input");return Collections.unmodifiableList(result);
    }
    public static final class Release {
        public final String artifactId,packageName,versionName,sha256;public final long versionCode,size;public final int minSdk;
        public final List<String> signers;public final Map<String,Object> json;
        private Release(Map<String,Object> m)throws Failure{
            keys(m,"schemaVersion","artifactId","packageName","versionCode","versionName","size","sha256","signerCertificateSha256","minSdkVersion");
            require(integer(m.get("schemaVersion"),1)==1,"invalid_input");artifactId=uuid(m.get("artifactId"));
            packageName=text(m.get("packageName"),255);require(packageName.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+"),"invalid_input");
            versionCode=integer(m.get("versionCode"),MAX_SAFE);versionName=text(m.get("versionName"),64);size=integer(m.get("size"),MAX_SIZE);
            sha256=hex(m.get("sha256"));signers=certificates(m.get("signerCertificateSha256"));minSdk=(int)integer(m.get("minSdkVersion"),Integer.MAX_VALUE);
            Map<String,Object> copy=new LinkedHashMap<>(m);copy.put("signerCertificateSha256",signers);json=Collections.unmodifiableMap(copy);
        }
    }
    public static Release release(Map<String,Object> m)throws Failure{return new Release(m);}
    public static Release sidecar(Map<String,Object> m,String id)throws Failure{
        uuid(id);keys(m,"contractVersion","downloadId","release");require(integer(m.get("contractVersion"),1)==1,"invalid_input");
        require(uuid(m.get("downloadId")).equals(id),"invalid_input");return release(object(m.get("release")));
    }
    public static final class Metadata {
        public final String packageName,versionName;public final long versionCode;public final int minSdk;public final List<String> signers;public final boolean split,rotation;
        public Metadata(String p,long v,String n,int sdk,Collection<String> s,boolean split,boolean rotation){
            packageName=p;versionCode=v;versionName=n;minSdk=sdk;signers=Collections.unmodifiableList(new ArrayList<>(new TreeSet<>(s)));this.split=split;this.rotation=rotation;
        }
    }
    public static void validate(Release r,Metadata installed,Metadata apk,int deviceSdk)throws Failure{
        require(apk!=null&&!apk.split,"invalid_apk");
        require(installed!=null&&installed.packageName!=null&&!installed.signers.isEmpty(),"unknown_result");
        require(r.packageName.equals(installed.packageName)&&r.packageName.equals(apk.packageName),"package_mismatch");
        require(r.versionCode==apk.versionCode&&r.versionName.equals(apk.versionName),"invalid_apk");
        require(r.versionCode>installed.versionCode,"not_newer");
        require(r.minSdk==apk.minSdk,"invalid_apk");require(apk.minSdk<=deviceSdk,"incompatible_sdk");
        require(!apk.rotation&&!installed.rotation&&!apk.signers.isEmpty()&&apk.signers.equals(installed.signers)&&apk.signers.equals(r.signers),"signer_mismatch");
    }
    public static String digest(InputStream in,OutputStream out,long size)throws Exception{
        MessageDigest d=MessageDigest.getInstance("SHA-256");byte[] b=new byte[65536];long count=0;int n;
        while((n=in.read(b))!=-1){count+=n;require(count<=size&&count<=MAX_SIZE,"integrity_failed");d.update(b,0,n);if(out!=null)out.write(b,0,n);}
        require(count==size,"integrity_failed");return encode(d.digest());
    }
    public static String encode(byte[] bytes){StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();}
    public static boolean installedTarget(Release target,Metadata actual){
        return actual!=null&&target.packageName.equals(actual.packageName)&&target.versionCode==actual.versionCode&&target.versionName.equals(actual.versionName)&&target.signers.equals(actual.signers)&&!actual.rotation;
    }
    public static String recover(Release target,Metadata actual,boolean sessionExists,String previous){
        if(installedTarget(target,actual))return "installed";
        if("cancelled".equals(previous)||"failed".equals(previous))return previous;
        return sessionExists&&"awaiting_user".equals(previous)?"awaiting_user":"unknown";
    }
    public static final class Gate {
        private final AtomicBoolean held=new AtomicBoolean();
        public void enter()throws Failure{require(held.compareAndSet(false,true),"busy");}
        public void leave(){held.set(false);}
    }
}
