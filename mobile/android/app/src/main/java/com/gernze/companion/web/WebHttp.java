package com.gernze.companion.web;

import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import okhttp3.*;

/** Android-local HTTPS only. Custom DNS answers are the actual OkHttp routes. */
public final class WebHttp {
    public interface Resolver {List<InetAddress> lookup(String host) throws Exception;}
    private static final ExecutorService DNS=new ThreadPoolExecutor(0,2,30,TimeUnit.SECONDS,new SynchronousQueue<>(),r->{Thread t=new Thread(r,"libao-web-dns");t.setDaemon(true);return t;},new ThreadPoolExecutor.AbortPolicy());
    public static final class Task {
        public final String id;public final long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(30);
        public volatile boolean cancelled,timedOut;public volatile Call call;public int requests,bytes;
        public Task(String id){this.id=id;}
        public void check() throws WebRules.Failure {WebRules.require(!timedOut&&System.nanoTime()<deadline,"timeout");WebRules.require(!cancelled,"cancelled");}
        public void expire(){timedOut=true;cancel();}
        public void cancel(){cancelled=true;Call c=call;if(c!=null)c.cancel();}
        public synchronized void request() throws WebRules.Failure {check();WebRules.require(++requests<=WebRules.MAX_REQUESTS,"request_limit");}
    }
    public static final class Page {
        public final String url,type;public final byte[] bytes;
        Page(String url,String type,byte[] bytes){this.url=url;this.type=type;this.bytes=bytes;}
    }
    private static final String DEEPSEEK_SEARCH="https://api.deepseek.com/v1/tools/search";
    private static final String TAVILY_SEARCH="https://api.tavily.com/search";
    private final Resolver resolver;
    public WebHttp(){this(host->Arrays.asList(InetAddress.getAllByName(host)));}
    public WebHttp(Resolver resolver){this.resolver=resolver;}
    public List<InetAddress> resolve(String host,Task t) throws IOException {
        Future<List<InetAddress>> f;
        try{f=DNS.submit(()->resolver.lookup(host));}catch(RejectedExecutionException e){throw new WebRules.Failure("dns_busy");}
        try{
            t.check();List<InetAddress> addresses=f.get(Math.max(1,Math.min(2500,TimeUnit.NANOSECONDS.toMillis(t.deadline-System.nanoTime()))),TimeUnit.MILLISECONDS);
            t.check();WebRules.require(addresses!=null&&!addresses.isEmpty()&&addresses.size()<=32,"blocked_target");
            for(InetAddress a:addresses)WebRules.require(WebRules.publicAddress(a),"blocked_target");
            // A single validated address avoids uncounted retry/fallback routes. No second lookup.
            return Collections.singletonList(addresses.get(0));
        }catch(WebRules.Failure e){throw e;}catch(Exception e){throw new WebRules.Failure("dns_failed");}finally{f.cancel(true);}
    }
    public static HttpUrl redirect(HttpUrl from,String location,int index,boolean search) throws IOException {
        WebRules.require(!search&&index<2,"redirect_blocked");
        HttpUrl next=location==null?null:from.resolve(location);WebRules.require(next!=null,"redirect_blocked");
        return WebRules.url(next.toString());
    }
    public static byte[] readBounded(InputStream in,long declared,Task t) throws IOException {
        WebRules.require(declared<=WebRules.MAX_BYTES,"response_limit");
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[8192];int n;
        while((n=in.read(buf))!=-1){t.check();WebRules.require(out.size()+n<=WebRules.MAX_BYTES&&t.bytes+n<=3*WebRules.MAX_BYTES,"response_limit");out.write(buf,0,n);t.bytes+=n;}
        t.check();return out.toByteArray();
    }
    public static void responsePolicy(String type,String encoding,boolean search) throws IOException {
        WebRules.require("identity".equalsIgnoreCase(encoding),"encoding_unsupported");
        WebRules.require(search?type.startsWith("application/json"):type.startsWith("text/html")||type.startsWith("text/plain"),"unsupported_type");
    }
    public Page get(String target,Task t,String searchKey) throws IOException {return fetch(target,t,searchKey,null);}
    /** One fixed read-only POST; no caller-supplied URL, method, headers or fields. */
    public Page tavily(String query,Task t,String searchKey) throws IOException {
        WebRules.require(searchKey!=null&&!searchKey.isEmpty(),"not_configured");String body;try{body=WebSearch.tavilyBody(query);}catch(WebRules.Failure e){throw e;}catch(Exception e){throw new WebRules.Failure("invalid_request");}
        return fetch(TAVILY_SEARCH,t,searchKey,body);
    }
    public Page deepseek(String query,Task t,String searchKey) throws IOException {
        WebRules.require(searchKey!=null&&!searchKey.isEmpty(),"not_configured");
        String body;try{body=WebSearch.deepseekBody(query);}catch(WebRules.Failure e){throw e;}catch(Exception e){throw new WebRules.Failure("invalid_request");}
        return fetch(DEEPSEEK_SEARCH,t,searchKey,body);
    }
    private Page fetch(String target,Task t,String searchKey,String postBody) throws IOException {
        HttpUrl url=WebRules.url(target);
        boolean search=searchKey!=null;
        if(search)WebRules.require(postBody==null?url.host().equals("api.search.brave.com")&&url.encodedPath().equals("/res/v1/web/search"):(target.equals(TAVILY_SEARCH)||target.equals(DEEPSEEK_SEARCH))&&postBody.getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=4096,"blocked_target");
        for(int redirect=0;;redirect++){
            t.request();
            OkHttpClient client=new OkHttpClient.Builder().proxy(Proxy.NO_PROXY).cookieJar(CookieJar.NO_COOKIES)
                .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
                .connectionPool(new ConnectionPool(0,1,TimeUnit.SECONDS)).protocols(Collections.singletonList(Protocol.HTTP_1_1))
                .dns(host->{try{return resolve(host,t);}catch(IOException e){UnknownHostException x=new UnknownHostException("web_dns_denied");x.initCause(e);throw x;}}).eventListener(new okhttp3.EventListener(){
                    @Override public void connectStart(Call c,InetSocketAddress remote,Proxy proxy){
                        if(remote.isUnresolved()||remote.getPort()!=443||!WebRules.publicAddress(remote.getAddress()))c.cancel();
                    }
                }).connectTimeout(6,TimeUnit.SECONDS).readTimeout(6,TimeUnit.SECONDS)
                .callTimeout(Math.max(1,TimeUnit.NANOSECONDS.toMillis(t.deadline-System.nanoTime())),TimeUnit.MILLISECONDS).build();
            Request.Builder rb=new Request.Builder().url(url).get().header("User-Agent","LibaoReadonlyCandidate/1.1.3")
                .header("Accept",search?"application/json":"text/html,text/plain;q=0.9").header("Accept-Encoding","identity");
            if(postBody!=null){rb.post(RequestBody.create(MediaType.get("application/json; charset=utf-8"),postBody));rb.header("Authorization","Bearer "+searchKey);}else if(search)rb.header("X-Subscription-Token",searchKey);
            Call call=client.newCall(rb.build());t.call=call;
            try{
                t.check();
                try(Response response=call.execute()){
                    t.check();int code=response.code();
                    if(code==301||code==302||code==303||code==307||code==308){
                        url=redirect(url,response.header("Location"),redirect,search);continue;
                    }
                    if(code==429)throw new WebRules.Failure("rate_limited");if(code==402||code==432||code==433)throw new WebRules.Failure("quota_exceeded");if(code==401)throw new WebRules.Failure("invalid_key");if(code==403||code==412||code==202)throw new WebRules.Failure("restricted");
                    WebRules.require(code==200,"http_error");
                    ResponseBody body=response.body();WebRules.require(body!=null,"empty_body");
                    String type=response.header("Content-Type","").toLowerCase(Locale.ROOT);
                    responsePolicy(type,response.header("Content-Encoding","identity"),search);
                    try(InputStream in=body.byteStream()){
                        return new Page(url.toString(),type,readBounded(in,body.contentLength(),t));
                    }
                }
            }finally{t.call=null;client.connectionPool().evictAll();client.dispatcher().executorService().shutdown();}
        }
    }
}
