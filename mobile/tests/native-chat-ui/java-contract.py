"""Source contract audit, explicitly NOT Java compilation or Android execution."""
from pathlib import Path
import re,json,hashlib
p=Path(__file__).resolve().parents[2]/'android/app/src/main/java/com/gernze/companion/LibaoChatPlugin.java'
s=p.read_text(encoding='utf8');checks=[]
def check(name,condition):
 if not condition:raise AssertionError(name)
 checks.append(name)
check('purpose defaults to chat and accepts only chat/summary','call.getString("purpose","chat")' in s and '!purpose.equals("chat")&&!purpose.equals("summary")' in s)
check('request id has ASCII length 1..100','id.matches("[A-Za-z0-9_-]{1,100}")' in s)
check('native slot is an AtomicReference','AtomicReference<Task> active=new AtomicReference<>()' in s)
check('single slot claimed before worker starts',s.index('if(!active.compareAndSet(null,task))')<s.index('ScheduledFuture<?> deadline=clock.schedule(task::stop,purpose.equals("summary")'))
check('summary/chat deadlines are 16/65 seconds','purpose.equals("summary")?16:65,TimeUnit.SECONDS' in s)
check('message transport cap is 65536 bytes','messages.length()>1000' in s and 'messages.toString().getBytes(StandardCharsets.UTF_8).length>65536' in s)
check('only role and content accepted','if(m.length()!=2' in s)
check('last message must be user','messages.getJSONObject(messages.length()-1).getString("role").equals("user")' in s)
check('validated per-request cap reaches payload with legacy500/700 defaults','put("max_tokens",maxTokens)' in s and 'final int maxTokens=supplied?((Number)allowance).intValue():(purpose.equals("summary")?500:700);' in s)
check('non-streaming request remains','put("stream",false)' in s)
check('cancel matches active id','t.id.equals(call.getString("id","")))t.stop()' in s)
check('cancel reports request accepted without freeing slot','r.put("cancelled",true);call.resolve(r);' in s)
check('Task.stop marks cancelled and disconnects','void stop(){cancelled=true;HttpsURLConnection c=connection;if(c!=null)c.disconnect();}' in s)
check('late native success fenced before resolve','if(task.cancelled)throw new InterruptedException();\n                JSObject result=new JSObject();result.put("data"' in s)
check('slot released in finally, independent of cancel return','finally{deadline.cancel(false);if(task.connection!=null)task.connection.disconnect();active.compareAndSet(task,null);}' in s)
check('destroy stops chat task','handleOnDestroy(){stopBalance();Task t=active.get();if(t!=null)t.stop();' in s)
check('pause currently stops balance only','handleOnPause(){stopBalance();super.handleOnPause();}' in s)
print(json.dumps({'status':'passed','checks':checks,'count':len(checks),'sourceSHA256':hashlib.sha256(p.read_bytes()).hexdigest(),'scope':'source-text contract audit only','compiled':False,'AndroidSDK':False,'device':False,'realProviderCalls':0,'limitations':['onPause has no chat stop; foreground JS app/visibility events remain required','native deadline marks stop but does not promise immediate HTTP unwind','resolve may already be queued for JS delivery when cancel arrives']},ensure_ascii=False,indent=2))
