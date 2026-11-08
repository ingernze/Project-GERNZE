package com.gernze.companion.web;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import org.json.*;
import okhttp3.HttpUrl;

public final class WebEngine {
    public interface Transport {
        WebHttp.Page get(String url,WebHttp.Task task,String key) throws java.io.IOException;
        default WebHttp.Page tavily(String query,WebHttp.Task task,String key) throws Exception {throw new WebRules.Failure("provider_unsupported");}
        default WebHttp.Page deepseek(String query,WebHttp.Task task,String key) throws Exception {throw new WebRules.Failure("provider_unsupported");}
    }
    private final Transport http;
    public WebEngine(){this(new Transport(){
        final WebHttp client=new WebHttp();
        public WebHttp.Page get(String u,WebHttp.Task t,String k)throws java.io.IOException{return client.get(u,t,k);}
        public WebHttp.Page tavily(String q,WebHttp.Task t,String k)throws Exception{return client.tavily(q,t,k);}
        public WebHttp.Page deepseek(String q,WebHttp.Task t,String k)throws Exception{return client.deepseek(q,t,k);}
    });}
    public WebEngine(Transport http){this.http=http;}
    public JSONObject run(String mode,String value,String provider,String searchKey,WebHttp.Task task) throws Exception {
        JSONArray sources=new JSONArray();
        if("read".equals(mode)){
            WebRules.url(value);sources.put(read(value,task,null));
        }else if("search".equals(mode)){
            String query=WebRules.query(value);WebRules.require(!"none".equals(provider),"not_configured");WebRules.require("tavily".equals(provider)||"brave".equals(provider)||"deepseek".equals(provider),"provider_unsupported");WebRules.require(searchKey!=null&&!searchKey.isEmpty(),"not_configured");
            WebHttp.Page page;
            if("deepseek".equals(provider))page=http.deepseek(query,task,searchKey);
            else if("tavily".equals(provider))page=http.tavily(query,task,searchKey);
            else{
                HttpUrl target=HttpUrl.get("https://api.search.brave.com/res/v1/web/search").newBuilder()
                    .addQueryParameter("q",query).addQueryParameter("count","3").addQueryParameter("result_filter","web")
                    .addQueryParameter("text_decorations","false").addQueryParameter("safesearch","moderate").build();
                page=http.get(target.toString(),task,searchKey);
            }
            String json=new String(page.bytes,StandardCharsets.UTF_8);int depth=0;boolean str=false,escape=false;
            for(char c:json.toCharArray()){
                if(str){if(escape)escape=false;else if(c=='\\')escape=true;else if(c=='\"')str=false;}
                else if(c=='\"')str=true;else if(c=='['||c=='{')WebRules.require(++depth<=32,"parse_limit");else if(c==']'||c=='}')depth--;
            }
            JSONObject data=new JSONObject(json);JSONObject web=data.optJSONObject("web");JSONArray items="brave".equals(provider)?(web==null?null:web.optJSONArray("results")):data.optJSONArray("results");WebRules.require(items!=null,"provider_response");
            String snippetField="deepseek".equals(provider)?"snippet":"tavily".equals(provider)?"content":"description";
            HashSet<String> seen=new HashSet<>();int read=0;
            for(int i=0;i<items.length()&&i<20&&sources.length()<3;i++){
                JSONObject row=items.optJSONObject(i);if(row==null)continue;String url;
                try{url=WebRules.url(row.optString("url")).toString();}catch(WebRules.Failure e){continue;}
                if(!seen.add(url))continue;
                JSONObject source=new JSONObject().put("url",url).put("title",WebRules.clean(row.optString("title"),240))
                    .put("text",WebRules.clean(ParserText(row.optString(snippetField)),600)).put("basis","snippet").put("status","snippet_only")
                    .put("partial",true).put("scope","搜索服务片段；未取得正文").put("readAt",WebRules.now());
                if(read++<2)source=read(url,task,source);sources.put(source);
            }
        }else throw new WebRules.Failure("invalid_request");
        task.check();return new JSONObject().put("sources",sources).put("requests",task.requests).put("networkBytes",task.bytes).put("platform","android_native_candidate");
    }
    private JSONObject read(String url,WebHttp.Task task,JSONObject fallback) throws Exception {
        try{return WebExtract.extract(http.get(url,task,null),task).put("requestedUrl",url);}
        catch(Exception e){task.check();String code="network_failed";Throwable cause=e;for(int i=0;i<5&&cause!=null;i++,cause=cause.getCause())if(cause instanceof WebRules.Failure){code=((WebRules.Failure)cause).code;break;}
            if(fallback!=null)return fallback.put("status",code);
            return new JSONObject().put("url",url).put("title","网页读取未完成").put("text","").put("basis","none").put("status",code)
                .put("scope","未取得可用正文").put("readAt",WebRules.now()).put("partial",true);
        }
    }
    private static String ParserText(String s){return org.jsoup.parser.Parser.unescapeEntities(s,false).replaceAll("<[^>]{0,300}>"," ");}
}
