package com.gernze.companion.web;
import org.json.JSONObject;
/** Bounded requests to the providers’ documented search endpoints. */
public final class WebSearch {
 private WebSearch(){}
 public static String deepseekBody(String input)throws Exception {
  String query=WebRules.query(input);
  WebRules.require(query.codePointCount(0,query.length())<=128,"search_query_too_long");
  return new JSONObject().put("query",query).put("count",3).put("need_content",false).toString();
 }
 public static String tavilyBody(String input)throws Exception {
  String query=WebRules.query(input);
  return new JSONObject().put("query",query).put("search_depth","basic").put("auto_parameters",false)
   .put("language",query.matches("(?s).*[\\u4e00-\\u9fff].*")?"zh-cn":"en").put("filter_by_language",false).put("topic","general").put("max_results",3).put("include_answer",false)
   .put("include_raw_content",false).put("include_images",false).toString();
 }
}
