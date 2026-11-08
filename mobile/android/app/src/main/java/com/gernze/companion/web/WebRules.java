package com.gernze.companion.web;

import java.io.IOException;
import java.net.InetAddress;
import java.net.URI;
import java.util.Locale;
import java.util.regex.Pattern;
import okhttp3.HttpUrl;

/** Fail-closed URL/address policy; no DNS lookup in URL validation. */
public final class WebRules {
    private WebRules() {}
    public static final int MAX_BYTES=524288, MAX_REQUESTS=8, MAX_BODY=12000;
    public static final Pattern SECRET=Pattern.compile("(?i)(?:\\b(?:sk|tvly)-[A-Za-z0-9_-]{8,}|bearer\\s+\\S+|(?:cookie|authorization|api[_-]?key|access[_-]?token|password|sessdata)\\s*[:=]\\s*\\S+)");
    public static final class Failure extends IOException {
        public final String code;
        public Failure(String code){super(code);this.code=code;}
    }
    public static void require(boolean value,String code) throws Failure {if(!value)throw new Failure(code);}
    public static HttpUrl url(String text) throws Failure {
        try {
            require(text!=null&&text.length()>0&&text.length()<=2048&&!text.matches("(?s).*[\\x00-\\x20\\x7f\\\\].*"),"invalid_url");
            URI u=new URI(text);
            require("https".equals(u.getScheme())&&u.getRawUserInfo()==null&&u.getRawFragment()==null&&(u.getPort()==-1||u.getPort()==443),"invalid_url");
            HttpUrl h=HttpUrl.get(text);String host=h.host().toLowerCase(Locale.ROOT);
            require(h.username().isEmpty()&&h.password().isEmpty()&&h.port()==443&&!host.endsWith("."),"invalid_url");
            require(host.contains(".")||host.contains(":"),"blocked_target");
            require(!host.endsWith(".local")&&!host.endsWith(".localhost")&&!host.endsWith(".internal")&&!host.endsWith(".home.arpa")&&!host.endsWith(".test")&&!host.endsWith(".invalid"),"blocked_target");
            // HttpUrl canonicalizes legacy numeric IPv4. Reject such spellings rather than guessing.
            String raw=u.getHost();require(raw!=null,"invalid_url");
            if(host.matches("[0-9.]+"))require(raw.equals(host),"invalid_url");
            if(host.matches("[0-9.]+")||host.contains(":"))require(publicAddress(InetAddress.getByName(host)),"blocked_target");
            for(String key:h.queryParameterNames())require(!key.toLowerCase(Locale.ROOT).matches(".*(?:token|password|cookie|authorization|api.?key|sessdata).*"),"credential_input");
            require(!SECRET.matcher(text).find(),"credential_input");return h;
        } catch(Failure e){throw e;}catch(Exception e){throw new Failure("invalid_url");}
    }
    public static String query(String text) throws Failure {
        require(text!=null&&!text.trim().isEmpty()&&text.length()<=240&&!text.matches("(?s).*[\\r\\n\\x00-\\x1f].*"),"invalid_query");
        require(!SECRET.matcher(text).find()&&!text.contains("://"),"credential_input");return text.trim();
    }
    public static boolean publicAddress(InetAddress ip) {
        byte[] a=ip.getAddress();
        if(ip.isAnyLocalAddress()||ip.isLoopbackAddress()||ip.isLinkLocalAddress()||ip.isSiteLocalAddress()||ip.isMulticastAddress())return false;
        if(a.length==4){
            int x=a[0]&255,y=a[1]&255,z=a[2]&255;
            return !(x==0||x==10||x==127||x>=224||x==100&&y>=64&&y<=127||x==169&&y==254||x==172&&y>=16&&y<=31||
                x==192&&(y==168||y==0||y==88&&z==99)||x==198&&(y==18||y==19||y==51&&z==100)||x==203&&y==0&&z==113);
        }
        if(a.length!=16)return false;
        int first=((a[0]&255)<<8)|(a[1]&255),second=((a[2]&255)<<8)|(a[3]&255);
        // Only ordinary global unicast. Exclude transition/special/documentation ranges.
        return first>=0x2000&&first<=0x3fff&&!(first==0x2001&&(second<=0x1ff||second==0xdb8))&&first!=0x2002&&first!=0x3ffe&&!(first==0x3fff&&second<0x1000);
    }
    public static String now(){java.text.SimpleDateFormat f=new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'",Locale.ROOT);f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));return f.format(new java.util.Date());}
    public static String clean(String s,int max) {
        if(s==null)return "";
        s=SECRET.matcher(s).replaceAll("[已遮盖凭据]").replaceAll("[\\p{Cc}&&[^\\n\\t]]","").trim();
        if(s.length()>max){int end=max;if(Character.isHighSurrogate(s.charAt(end-1)))end--;s=s.substring(0,end);}return s;
    }
}
