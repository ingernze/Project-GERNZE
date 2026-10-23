"""Forced wrong approvals, not real model inference. No personal data/network."""
import argparse,json,sys,tempfile,uuid,types
from pathlib import Path
from unittest import TestCase,main
p=argparse.ArgumentParser();p.add_argument('--source',required=True);args,rest=p.parse_known_args()
sys.path.insert(0,str(Path(args.source).resolve()/'src'))
sys.path.insert(0,str(Path(args.source).resolve()/'src/workbench/tests'))
from workbench.companion_chat import CompanionChat
from workbench.desktop_memory_review import DesktopMemoryReview
from workbench.review_admission import assess
from desktop_auto_review_test import Keys

def source(text,index=0):return {'id':str(index),'role':'user','origin':'user','content':text,'turnIndex':index,'time':None}
def allowed(text,context=(),selected=0):
    sources=[source(t,i) for i,t in enumerate([text,*context])]
    return assess(sources,[{'messageId':str(selected),'quote':sources[selected]['content']}])[0]

class Tests(TestCase):
    def test_wrong_full_novel_approval_cannot_enter_second_layer(self):
        text='下面是小说台词：“我住在合成月城。”这不是我的经历。'
        with tempfile.TemporaryDirectory() as temp:
            chat=CompanionChat(Path(temp)/'chat.json',keys=Keys());chat.configure({'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic','key':'synthetic-only'})
            for i in range(8):
                tid=str(uuid.uuid4());chat.store.begin_turn(chat.store.session_id,text if i==0 else '无关的合成上下文。',tid)
                chat.store.complete(tid,{'text':'合成助手回复。','emotion':'normal','action':'none'},chat.store.epoch(),[])
            view=chat.store.summary_view(chat.store.session_id,keep_recent=1,batch=3)
            chat.store.commit_summary(chat.store.session_id,view,view['new_turns'],text)
            class Wrong:
                limits=types.SimpleNamespace(context_window=32768,margin=512,io_timeout=1)
                def count(self,m):return len(json.dumps(m).encode())
                def complete(self,m,*a,**kw):
                    e=json.loads(m[1]['content'])['entries'][0];s=next(s for s in e['sources'] if s['role']=='user')
                    return json.dumps({'decisions':[{'key':e['key'],'revision':e['revision'],'action':'approve','text':text,'evidence':[{'messageId':s['id'],'quote':text}],'reason':'故意给出错误批准，检验主机准入。'}]})
            reviewer=DesktopMemoryReview(chat,adapter=Wrong());result=reviewer.run(force=True)
            self.assertEqual(result['status'],'completed');self.assertEqual(result['decisions'][0]['action'],'defer')
            self.assertEqual(result['decisions'][0]['proposedAction'],'approve');self.assertEqual(result['result']['applied'],0)
            self.assertEqual(chat.layers.snapshot()['approved'],[]);self.assertEqual(len(chat.layers.snapshot()['pending']),1)
            reviewer.stop()
    def test_fiction_quotes_hypotheticals_and_mixed_content_defer(self):
        cases=[
            '角色台词：我的昵称是松果。','甲说：“我住在合成月城。”',
            '我没有去过月城，前面那句是小说。','如果我住在月城，会怎样？',
            '我的昵称是松果。这是人物设定，不是本人资料。',
            '我可太喜欢加班了，哈哈。','小说里：我计划2026年10月25日去合成公园，现在还没去。',
            '```\n我的昵称是松果。\n```','{"text":"我的昵称是松果。"}',
            '我的昵称是松果。下面是小说台词：我住在月城。',
        ]
        for text in cases:
            with self.subTest(text=text):self.assertFalse(allowed(text))
    def test_no_keyword_hit_is_not_permission(self):
        self.assertFalse(allowed('昨晚银龙从天而降，我与它签了契约。'))
        self.assertFalse(allowed('测试通过了，所有事情都结束了。'))
    def test_supported_self_reports_still_work_and_preserve_negation(self):
        for text in ['我的昵称是松果。','我住在合成甲城。','我不喜欢蓝色。','我还没有去过合成公园。','我计划2026年10月25日去合成公园，现在还没去。','我把合成松果计划排在下周，尚未开始。']:
            with self.subTest(text=text):self.assertTrue(allowed(text))
    def test_writing_a_novel_is_distinct_from_character_experiences(self):
        self.assertTrue(allowed('我正在写小说《合成月城》。'))
        self.assertFalse(allowed('我的主角住在合成月城。'))
    def test_roleplay_context_blocks_plain_first_person_line(self):
        self.assertFalse(allowed('下面开始角色扮演。',['我的昵称是松果。'],selected=1))
        self.assertFalse(allowed('这是角色卡。',['我住在合成甲城。'],selected=1))
    def test_later_correction_supersedes_old_evidence(self):
        earlier='我住在合成甲城。';later='纠正一下，上一条说错了，我住在合成乙城。'
        self.assertFalse(allowed(earlier,[later]));self.assertTrue(allowed(earlier,[later],selected=1))
        self.assertFalse(allowed('我计划2026年10月25日去合成公园，现在还没去。',['纠正一下，计划取消了。']))
    def test_unknown_long_mixed_and_partial_messages_stay_unapproved(self):
        text='我的昵称是松果。'+'另一个句子。'*200
        self.assertFalse(allowed(text))
        self.assertFalse(assess([source('不要记录“我已经完成测试”，我还未开始。')],[{'messageId':'0','quote':'我已经完成测试'}])[0])

if __name__=='__main__':main(argv=[sys.argv[0]]+rest,verbosity=2)
