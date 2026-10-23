package com.gernze.companion.updates.transport;

import android.util.Base64;
import android.util.JsonReader;
import android.util.JsonToken;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

final class TransportRules {
    static final long MAX_APK=536870912L;
    static final String TLS_NAME="hebao.local";
    static class Failure extends Exception {
        final String code;
        Failure(String code){super(code);this.code=code;}
    }
    static void require(boolean condition,String code) throws Failure {if(!condition)throw new Failure(code);}
    static void keys(JSONObject o,String... names) throws Exception {
        Set<String> wanted=new HashSet<>(Arrays.asList(names));
        require(o.length()==wanted.size(),"invalid_input");
        Iterator<String> it=o.keys();while(it.hasNext())require(wanted.contains(it.next()),"invalid_input");
    }
    static String string(JSONObject o,String key,int max) throws Exception {
        Object v=o.get(key);require(v instanceof String,"invalid_input");String s=(String)v;
        require(!s.isEmpty() && s.codePointCount(0,s.length())<=max && s.equals(s.trim()),"invalid_input");
        for(int i=0;i<s.length();i++){
            char c=s.charAt(i);require(c>=32,"invalid_input");
            if(Character.isHighSurrogate(c)){require(i+1<s.length()&&Character.isLowSurrogate(s.charAt(++i)),"invalid_input");}
            else require(!Character.isLowSurrogate(c),"invalid_input");
        }
        return s;
    }
    static String uuid(String v) throws Exception {
        require(v!=null&&v.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),"invalid_input");
        require(UUID.fromString(v).toString().equals(v),"invalid_input");return v;
    }
    static long number(JSONObject o,String key,long min,long max) throws Exception {
        Object v=o.get(key);require(v instanceof Integer||v instanceof Long,"invalid_input");
        long n=((Number)v).longValue();require(n>=min&&n<=max,"invalid_input");return n;
    }
    static String hash(String v) throws Exception {require(v.matches("[0-9a-f]{64}"),"invalid_input");return v;}
    static String token(String v) throws Exception {require(v.matches("[A-Za-z0-9_-]{43}"),"invalid_input");return v;}
    static String host(String s) throws Exception {
        require(s.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}"),"invalid_input");
        String[] p=s.split("\\.");int[] n=new int[4];
        for(int i=0;i<4;i++){n[i]=Integer.parseInt(p[i]);require(n[i]<=255&&Integer.toString(n[i]).equals(p[i]),"invalid_input");}
        require(n[0]==10||(n[0]==172&&n[1]>=16&&n[1]<=31)||(n[0]==192&&n[1]==168),"invalid_input");return s;
    }
    static String hex(byte[] bytes){StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();}
    static String sha(byte[] b) throws Exception{return hex(MessageDigest.getInstance("SHA-256").digest(b));}
    static JSONObject release(JSONObject r) throws Exception {
        keys(r,"schemaVersion","artifactId","packageName","versionCode","versionName","size","sha256","signerCertificateSha256","minSdkVersion");
        number(r,"schemaVersion",1,1);uuid(string(r,"artifactId",36));
        require(string(r,"packageName",255).matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+"),"invalid_input");
        number(r,"versionCode",1,9007199254740991L);string(r,"versionName",64);
        number(r,"size",1,MAX_APK);hash(string(r,"sha256",64));number(r,"minSdkVersion",1,2147483647);
        Object raw=r.get("signerCertificateSha256");require(raw instanceof JSONArray,"invalid_input");JSONArray a=(JSONArray)raw;
        require(a.length()>0,"invalid_input");String prior="";
        for(int i=0;i<a.length();i++){
            require(a.get(i) instanceof String,"invalid_input");String s=hash((String)a.get(i));
            require(prior.compareTo(s)<0,"invalid_input");prior=s;
        }
        return r;
    }
    static JSONObject pairing(String payload,boolean expiry) throws Exception {
        JSONObject p=parse(payload,8192);
        keys(p,"protocol","serverId","host","port","certificateDer","certificateSha256","pairingSecret","expiresAt");
        require(string(p,"protocol",32).equals("hebao-pair-v1"),"invalid_input");
        uuid(string(p,"serverId",36));host(string(p,"host",15));number(p,"port",1024,65535);
        long expires=number(p,"expiresAt",1,9007199254740991L);
        if(expiry)require(expires>System.currentTimeMillis()&&expires-System.currentTimeMillis()<=300000,"pairing_expired");
        token(string(p,"pairingSecret",43));String cert=string(p,"certificateDer",4096);
        require(cert.matches("[A-Za-z0-9+/]+={0,2}"),"invalid_input");
        byte[] der=Base64.decode(cert,Base64.NO_WRAP);
        require(der.length>=128&&der.length<=3072&&Base64.encodeToString(der,Base64.NO_WRAP).equals(cert),"invalid_input");
        require(sha(der).equals(hash(string(p,"certificateSha256",64))),"tls_mismatch");return p;
    }
    static JSONObject parse(String text,int maxBytes) throws Exception {return parse(text,maxBytes,256);}
    static JSONObject parse(String text,int maxBytes,int arrayLimit) throws Exception {
        require(text!=null&&text.getBytes(StandardCharsets.UTF_8).length<=maxBytes,"invalid_input");
        try(JsonReader reader=new JsonReader(new StringReader(text))){
            reader.setLenient(false);Object v=read(reader,0,arrayLimit);
            require(v instanceof JSONObject&&reader.peek()==JsonToken.END_DOCUMENT,"invalid_input");return (JSONObject)v;
        }catch(Failure e){throw e;}catch(Exception e){throw new Failure("invalid_input");}
    }
    private static Object read(JsonReader r,int depth,int arrayLimit) throws Exception {
        require(depth<=8,"invalid_input");
        switch(r.peek()){
            case BEGIN_OBJECT:{
                JSONObject o=new JSONObject();Set<String> seen=new HashSet<>();r.beginObject();
                while(r.hasNext()){
                    String key=r.nextName();require(key.length()<=64&&seen.size()<32&&seen.add(key),"invalid_input");o.put(key,read(r,depth+1,arrayLimit));
                }r.endObject();return o;
            }
            case BEGIN_ARRAY:{JSONArray a=new JSONArray();r.beginArray();while(r.hasNext()){require(a.length()<arrayLimit,"invalid_input");a.put(read(r,depth+1,arrayLimit));}r.endArray();return a;}
            case STRING:return r.nextString();
            case NUMBER:{String s=r.nextString();require(s.matches("0|[1-9][0-9]{0,15}"),"invalid_input");return Long.parseLong(s);}
            case BOOLEAN:return r.nextBoolean();
            case NULL:r.nextNull();return JSONObject.NULL;
            default:throw new Failure("invalid_input");
        }
    }
}
