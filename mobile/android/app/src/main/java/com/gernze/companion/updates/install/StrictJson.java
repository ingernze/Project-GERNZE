package com.gernze.companion.updates.install;

import android.util.JsonReader;
import android.util.JsonToken;
import java.io.*;
import java.nio.charset.*;
import java.util.*;

/** Platform parser, strict types, duplicate keys, depth and byte bounds. */
final class StrictJson {
    static Map<String,Object> read(InputStream stream)throws Exception{
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[2048];int n;
        while((n=stream.read(buf))!=-1){Rules.require(out.size()+n<=16384,"invalid_input");out.write(buf,0,n);}
        Reader text=new InputStreamReader(new ByteArrayInputStream(out.toByteArray()),StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT));
        try(JsonReader r=new JsonReader(text)){r.setLenient(false);Object value=value(r,0);Rules.require(r.peek()==JsonToken.END_DOCUMENT,"invalid_input");return Rules.object(value);}
        catch(IOException|IllegalStateException malformed){throw new Rules.Failure("invalid_input");}
    }
    static Object value(JsonReader r,int depth)throws Exception{
        Rules.require(depth<=6,"invalid_input");
        switch(r.peek()){
            case BEGIN_OBJECT:{Map<String,Object> m=new LinkedHashMap<>();r.beginObject();while(r.hasNext()){String key=r.nextName();Rules.require(!m.containsKey(key)&&m.size()<32,"invalid_input");m.put(key,value(r,depth+1));}r.endObject();return m;}
            case BEGIN_ARRAY:{List<Object>a=new ArrayList<>();r.beginArray();while(r.hasNext()){Rules.require(a.size()<32,"invalid_input");a.add(value(r,depth+1));}r.endArray();return a;}
            case STRING:return r.nextString();
            case NUMBER:{String s=r.nextString();Rules.require(s.matches("0|[1-9][0-9]*"),"invalid_input");try{return Long.valueOf(s);}catch(NumberFormatException e){throw new Rules.Failure("invalid_input");}}
            default:throw new Rules.Failure("invalid_input");
        }
    }
}
