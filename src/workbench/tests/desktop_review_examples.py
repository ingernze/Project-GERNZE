"""Current assistant's judgments replayed as explicit synthetic adapter responses.
This is not an isolated model experiment, API conversation or real user data.
"""
import sys,argparse,json,tempfile,uuid,types,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.source).resolve();sys.path.insert(0,str(root/'src'));sys.path.insert(0,str(root/'src/workbench/tests'))
from desktop_auto_review_test import Keys
from workbench.companion_chat import CompanionChat
from workbench.desktop_memory_review import DesktopMemoryReview

def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
CASES=[
 {'name':'明确事实','users':['我的合成测试昵称是松果。'],'body':'我的合成测试昵称是松果。','action':'approve','quoteIndex':0,'reason':'这是用户本人明确陈述的测试昵称，原文与候选一致。'},
 {'name':'计划未发生','users':['我计划2026年10月25日去合成公园，现在还没去。'],'body':'我已经去过合成公园。','action':'correct','quoteIndex':0,'reason':'原文明确是未来计划且尚未发生，晋级正文必须保留计划与否定限定。'},
 {'name':'后续纠正','users':['我住在合成甲城。','纠正一下，上一条说错了，我住在合成乙城。'],'body':'用户住在合成甲城。','action':'correct','quoteIndex':1,'reason':'后续用户明确纠正旧说法，采用新消息的完整原话，保留纠正关系。'},
 {'name':'小说引文','users':['下面是小说台词：“我住在合成月城。”这不是我的经历。'],'body':'用户住在合成月城。','action':'defer','reason':'这段话自称小说且明确否认亲历，不能据此认定用户居住地。'},
 {'name':'手机来源缺失','users':['仅用于建立合成候选，不作为手机证据。'],'body':'手机摘要称用户喜欢合成蓝茶。','action':'defer','missingPhone':True,'reason':'对应手机第四层原文尚未传到电脑，不用摘要自证，保留待审。'},
 {'name':'暂停期间晚到结果','users':['我的合成测试昵称是松果。'],'body':'我的合成测试昵称是松果。','action':'approve','quoteIndex':0,'pause':True,'reason':'文字本身有完整原话；但生成期间用户暂停，旧响应必须作废。'},
 {'name':'边界：截掉否定与引文限定','users':['不要记录“我已经完成测试”，我还未开始。'],'body':'我已经完成测试。','action':'correct','literalQuote':'我已经完成测试','reason':'故意注入错误审查结果，检验子串不能冒充完整用户陈述。','injectedWrongDecision':True},
 {'name':'边界：整段小说被错误批准','users':['下面是小说台词：“我住在合成月城。”这不是我的经历。'],'body':'下面是小说台词：“我住在合成月城。”这不是我的经历。','action':'approve','quoteIndex':0,'reason':'故意注入错误语义判断，展示完整原话校验仍无法判断是否适合晋级。','injectedWrongDecision':True},
 {'name':'边界：长消息保守拒绝','users':['我的合成昵称是松果。'+'这是无关的合成测试填充句。'*100],'body':'我的合成昵称是松果。','action':'correct','quoteIndex':0,'reason':'完整消息超过1000字，当前规则不允许只摘出昵称句，仍须待审。'}]
records=[]
for case in CASES:
 with tempfile.TemporaryDirectory() as temp:
  chat=CompanionChat(Path(temp)/'chat.json',keys=Keys());chat.configure({'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic','key':'synthetic-only'})
  users=case['users']
  for i in range(8):
   text=users[i] if i<len(users) else ('这是一条无关的合成陪衬。' if i<3 else '合成近期上下文。')
   tid=str(uuid.uuid4());chat.store.begin_turn(chat.store.session_id,text,tid);chat.store.complete(tid,{'text':'合成助手观点，不能充当用户证据。','emotion':'normal','action':'none'},chat.store.epoch(),[])
  view=chat.store.summary_view(chat.store.session_id,keep_recent=1,batch=3);chat.store.commit_summary(chat.store.session_id,view,view['new_turns'],case['body'])
  w=chat.layers.snapshot()['pending'][0]
  if case.get('missingPhone'):
   with chat.store.connection() as db:
    db.execute('INSERT INTO lm_layer_sync_meta VALUES (?,?)',('phone3:'+w['key']+':'+w['revision'],json.dumps({'device':str(uuid.uuid4()),'sessionId':'synthetic-unsynced','start':0,'end':6})))
    db.execute('INSERT INTO lm_remote_sources VALUES (?,?,?)',(w['key'],w['revision'],'{}'))
  class Adapter:
   limits=types.SimpleNamespace(context_window=32768,margin=512,io_timeout=1)
   calls=0;request=None;response=None
   def count(self,m):return len(json.dumps(m,ensure_ascii=False).encode())+128
   def complete(self,m,maximum,control,report,**kw):
    self.calls+=1;self.request=m;entry=json.loads(m[1]['content'])['entries'][0]
    quote=case.get('literalQuote',users[case.get('quoteIndex',0)])
    source=next(s for s in entry['sources'] if s['role']=='user' and quote in s['content'])
    speak=case['action'] in ('approve','correct')
    self.response={'decisions':[{'key':entry['key'],'revision':entry['revision'],'action':case['action'],'text':quote if speak else '', 'evidence':[{'messageId':source['id'],'quote':quote}] if speak else [],'reason':case['reason']}]}
    if case.get('pause'):reviewer.configure(False)
    return json.dumps(self.response,ensure_ascii=False)
  adapter=Adapter();reviewer=DesktopMemoryReview(chat,adapter=adapter)
  result=reviewer.run(force=True);snapshot=chat.layers.snapshot()
  records.append({'name':case['name'],'mode':'synthetic_fixture_current_assistant_judgment_replayed','injectedWrongDecision':case.get('injectedWrongDecision',False),'thirdLayer':case['body'],'sources':[] if case.get('missingPhone') else users,'assistantAssessment':case['reason'],'proposedAction':case['action'],'result':result,'approvedBodies':[x['body'] for x in snapshot['approved'] if not x['deleted']],'pendingCount':len(snapshot['pending']),'syntheticAdapterCalls':adapter.calls,'syntheticRequestHash':digest(adapter.request) if adapter.request else None,'syntheticResponseHash':digest(adapter.response) if adapter.response else None})
  reviewer.stop()
report={'data':'all synthetic','semanticReviewer':'current assistant assessment in this conversation; decisions are replay fixtures, not isolated model inference','realAPICalls':0,'currentAssistantUsage':None,'cases':records}
Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps([{'name':r['name'],'status':r['result']['status'],'approved':len(r['approvedBodies']),'pending':r['pendingCount']} for r in records],ensure_ascii=False,indent=2))
