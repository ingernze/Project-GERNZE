"""Conservative *admission*, not a general-purpose fact/fiction classifier.

Only complete, narrowly supported self-report forms can be auto-promoted.
Everything else stays L3 even when the review model says approve. This cannot
establish real-world truth or detect fiction lacking any contextual marker.
No model output can set an attribution flag or expand the admitted language.
"""
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class Assertion:
    field: str
    value: str

VALUE=r'[\u3400-\u9fffA-Za-z0-9 _·\-]{1,40}'
END=r'[。.!！]?'
CORRECTION=re.compile(r'^(?:纠正一下|更正一下)[，,](?:上一条|刚才)(?:说错了|不对)[，,]')
CONTEXT=re.compile(
    r'(?:下面|以下|接下来).{0,18}(?:小说|台词|引文|摘录|角色扮演|设定片段)'
    r'|(?:小说|角色|主角|人物).{0,12}(?:台词|说[：:]|经历|自述)'
    r'|(?:不是|并非).{0,5}(?:我|本人).{0,5}(?:经历|亲历|事实)'
    r'|(?:假如|假设|设想|扮演|角色卡|人设卡|反讽|讽刺|开玩笑|转述|引用|朋友说|他说[：:]|她说[：:])'
    r'|(?:前面|刚才|上面|上一条).{0,10}(?:不是真的|作废|取消)')

def assertion(text):
    """Full matches only: no prefix/suffix stripping except named correction.

    Quoted/profile-like text embedded in narrative never matches. Dates and
    negation remain in the original stored text; this returns comparison keys
    only and never rewrites a memory body.
    """
    text=CORRECTION.sub('',text,count=1)
    for name,pattern in [
        ('nickname',rf'我的(?:合成测试|合成)?昵称是(?P<v>{VALUE}){END}'),
        ('username',rf'我的用户名是(?P<v>{VALUE}){END}'),
        ('major',rf'我的专业是(?P<v>{VALUE}){END}'),
        ('residence',rf'我(?:目前|现在)?住在(?P<v>{VALUE}){END}'),
        ('writing',r'我(?:在|正在)(?:写|创作)(?:一部)?小说《(?P<v>[^《》\n\r“”「」]{1,80})》'+END),
        ('preference',rf'我(?:不)?喜欢(?P<v>{VALUE}){END}'),
        ('plan',rf'我计划(?P<v>20\d{{2}}年\d{{1,2}}月\d{{1,2}}日(?:去|做|开始){VALUE})[，,](?:现在还没去|尚未开始|还没发生){END}'),
        ('plan',rf'我把(?P<v>{VALUE}计划排在(?:明天|下周|下个月))[，,]尚未开始{END}'),
        ('not_visited',rf'我(?:还)?没(?:有)?去过(?P<v>{VALUE}){END}'),
    ]:
        m=re.fullmatch(pattern,text)
        if m:
            value=m['v']
            if name=='preference':value=('negative:' if text.startswith('我不喜欢') else 'positive:')+value
            return Assertion(name,value)
    return None

def assess(sources,evidence):
    """Returns an allow/defer reason derived solely from host-owned sources.

    Recognized ambiguity can veto an assertion. More importantly, absence of
    an ambiguity keyword does NOT confer permission: a full supported positive
    form and complete quote are required. Unknown language is deferred.
    """
    users=[s for s in sources if s.get('role')=='user']
    for s in users:
        text=s.get('content','')
        if not isinstance(text,str):return False,'invalid_source'
        if CONTEXT.search(text):return False,'fiction_quote_or_uncertain_context'
        if re.match(r'^(?:纠正|更正|取消|刚才说错)',text) and assertion(text) is None:
            return False,'unresolved_correction'
    indexed={s['id']:s for s in users}
    latest={}
    for index,s in enumerate(users):
        a=assertion(s.get('content',''))
        if a:
            # Host turnIndex is supplied by the SQLite/phone source reader.
            order=(s.get('turnIndex',index),index)
            field=a.field if a.field!='preference' else a.field+':'+a.value.split(':',1)[-1]
            if field not in latest or order>latest[field][0]:latest[field]=(order,s['id'],a.value)
    if not evidence:return False,'no_evidence'
    for e in evidence:
        s=indexed.get(e.get('messageId'))
        if not s or e.get('quote')!=s.get('content'):return False,'incomplete_source'
        if s.get('origin','user')!='user':return False,'non_user_origin'
        a=assertion(s['content'])
        if a is None:return False,'outside_auto_admission_scope'
        field=a.field if a.field!='preference' else a.field+':'+a.value.split(':',1)[-1]
        if latest[field][1]!=s['id'] and latest[field][2]!=a.value:return False,'superseded_source'
    return True,'supported_complete_self_report'
