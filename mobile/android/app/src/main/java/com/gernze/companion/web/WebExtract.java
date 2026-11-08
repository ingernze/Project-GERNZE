package com.gernze.companion.web;

import java.io.*;
import java.nio.*;
import java.nio.charset.*;
import java.util.Locale;
import java.util.regex.*;
import org.jsoup.nodes.*;
import org.jsoup.parser.Parser;
import org.json.JSONObject;

/** Text only: jsoup does not execute scripts, fetch images or follow links. */
public final class WebExtract {
    private WebExtract() {}
    private static final Pattern CHARSET=Pattern.compile("(?i)charset\\s*=\\s*['\"]?([A-Za-z0-9_-]+)");
    public static JSONObject extract(WebHttp.Page page,WebHttp.Task task) throws Exception {
        task.check();long began=System.nanoTime();
        String charset="UTF-8";Matcher m=CHARSET.matcher(page.type);
        if(m.find())charset=m.group(1);else{
            m=CHARSET.matcher(new String(page.bytes,0,Math.min(4096,page.bytes.length),StandardCharsets.ISO_8859_1));if(m.find())charset=m.group(1);
        }
        if(charset.equalsIgnoreCase("gb2312")||charset.equalsIgnoreCase("gbk"))charset="GB18030";
        WebRules.require(charset.matches("(?i)utf-8|utf8|gb18030|big5|iso-8859-1|windows-1252"),"encoding_unsupported");
        String raw;
        try{raw=Charset.forName(charset).newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(page.bytes)).toString();}
        catch(Exception e){throw new WebRules.Failure("encoding_unsupported");}
        String title="",text;boolean article=false;
        if(page.type.startsWith("text/plain")){text=raw;}
        else{
            // Bound token count before parser allocation, in addition to byte and parser-depth caps.
            int tags=0;for(int i=0;i<raw.length();i++)if(raw.charAt(i)=='<')WebRules.require(++tags<=16000,"parse_limit");
            final String input=raw;
            Reader reader=new StringReader(input){@Override public int read(char[] b,int off,int len)throws IOException{
                task.check();if(System.nanoTime()-began>TimeUnitMillis(1500))throw new WebRules.Failure("parse_limit");return super.read(b,off,len);
            }};
            Document doc=Parser.htmlParser().setMaxDepth(128).parseInput(reader,page.url);
            task.check();title=WebRules.clean(doc.title(),240);
            WebRules.require(doc.selectFirst("input[type=password], [class*=captcha], [id*=captcha], [class*=geetest]")==null,"restricted");
            WebRules.require(!title.matches("(?is).*(captcha|verify you|just a moment|access denied|安全验证|验证码|登录验证).*"),"restricted");
            doc.select("script,style,noscript,iframe,svg,canvas,form,nav,footer,header,aside,[hidden],[aria-hidden=true]").remove();
            Element main=doc.selectFirst("article");if(main==null)main=doc.selectFirst("main");article=main!=null;
            if(main==null)main=doc.body();
            text=main==null?"":main.wholeText();
            if(!article&&text.trim().length()<200)throw new WebRules.Failure("no_body");
        }
        task.check();WebRules.require(System.nanoTime()-began<=TimeUnitMillis(1500),"parse_limit");
        text=WebRules.clean(text.replaceAll("[ \\t]+"," ").replaceAll("\\n\\s*\\n\\s*\\n+","\n\n"),WebRules.MAX_BYTES);
        WebRules.require(text.length()>=40,"no_body");int full=text.length();String selected=WebRules.clean(text,WebRules.MAX_BODY);
        return new JSONObject().put("title",title.isEmpty()?"网页文字":title).put("url",page.url).put("basis","body")
            .put("text",selected).put("status","body_text").put("networkBytes",page.bytes.length).put("extractedChars",full)
            .put("retainedChars",selected.length()).put("partial",true).put("scope",article?"静态主内容文字；非全文完整性保证":"静态页面文字；可能含导航或缺少动态内容")
            .put("readAt",WebRules.now()).put("charset",charset);
    }
    private static long TimeUnitMillis(long n){return n*1000000L;}
}
