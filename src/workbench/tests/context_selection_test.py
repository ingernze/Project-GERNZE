"""Context-selection regressions; no model, credentials or persistent user data."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from context_manager import ContextManager, Budget
from conversation_store import ChatStateError

def note(key, body, **extra):
    return dict(id=key, revision='r1', title='archive', body=body, kind='other',
                event_date='', important=False, chat_enabled=True, **extra)


def pair(i, body='recent', origin='user'):
    return {'id':str(i), 'seq':i, 'origin':origin, 'messages':[
        {'id':'u'+str(i), 'role':'user', 'origin':origin, 'content':body},
        {'id':'a'+str(i), 'role':'assistant', 'origin':'assistant', 'content':'answer '+str(i)}]}


class Store:
    def __init__(self, recent=()): self.pairs=list(recent)
    def directives(self, *args): return []
    def recent(self, *args): return self.pairs
    def retrieve(self, *args): return []
    def summary_view(self, *args, **kwargs):
        return {'segments':[], 'last_attempt_status':'disabled', 'old_unsummarized_turns':0}


def data(messages):
    return json.loads(messages[0]['content'].split('本机上下文资料JSON:\n',1)[1])


class ContextTests(unittest.TestCase):
    def build(self, store=None, notes=(), policies=None, manager=None, **kw):
        return (manager or ContextManager(budget=Budget(context_window=8192))).build(
            store or Store(), 'session', 'request', 'L1 synthetic fixed',
            kw.pop('current','quasar'), notes, policies or {}, **kw)

    def test_unrelated_notes_cannot_displace_six_pairs_or_related_l2(self):
        rows=[note(str(i),'z'*450) for i in range(64)]+[note('relevant','quasar plan')]
        messages, refs, report=self.build(Store([pair(i,'x'*250) for i in range(6)]),rows)
        self.assertEqual(len(report['recent_turn_ids']),6)
        self.assertEqual(refs[0]['id'],'relevant')
        self.assertTrue(any(item.startswith('note:') for item in report['omitted']))
        self.assertEqual(len(report['unmatched_note_ids']),64)
        self.assertEqual([m['role'] for m in messages],['system']+['user','assistant']*6+['user'])
        self.assertEqual([json.loads(m['content'])['source_id'] for m in messages[1:-1:2]],['u'+str(i) for i in range(6)])
        self.assertLessEqual(report['count'],report['input_limit'])

    def test_actual_fixed_content_not_silently_dropped_at_budget_boundary(self):
        messages, _, r=self.build()
        exact_fit=Budget(context_window=r['count']+700+512)
        self.assertEqual(self.build(manager=ContextManager(budget=exact_fit))[0],messages)
        with self.assertRaises(ChatStateError) as caught:
            self.build(manager=ContextManager(budget=Budget(context_window=exact_fit.context_window-1)))
        self.assertEqual(caught.exception.code,'context_overflow')

    def test_long_pair_is_omitted_intact_and_reported_smaller_pair_survives(self):
        messages,_,r=self.build(Store([pair(1),pair(2,'x'*50000)]))
        self.assertEqual(r['recent_turn_ids'],['1']);self.assertIn('turn:2',r['omitted'])
        self.assertEqual(len(messages),4);self.assertNotIn('u2',json.dumps(messages))

    def test_newer_pairs_get_first_claim_when_all_six_do_not_fit(self):
        _,_,r=self.build(Store([pair(1,'a'*1800),pair(2,'b'*1800),pair(3,'c'*1800)]))
        self.assertIn('3',r['recent_turn_ids']);self.assertIn('2',r['recent_turn_ids'])
        self.assertNotIn('1',r['recent_turn_ids']);self.assertIn('turn:1',r['omitted'])

    def test_corrections_scopes_and_revisions_remain_enforced(self):
        rows=[note(k,'no overlap') for k in ['correct','wrongscope','stale','disabled']]
        rows[-1]['chat_enabled']=False
        policies={k:{'revision':'r1','scope':'technical','correction':True} for k in ['correct','wrongscope','stale']}
        policies['wrongscope']['scope']='casual';policies['stale']['revision']='r0'
        messages,refs,r=self.build(notes=rows,policies=policies,topic='technical')
        self.assertEqual([n['id'] for n in refs],['correct'])
        self.assertTrue(data(messages)['confirmed_notes'][0]['correction'])

    def test_mandatory_overflow_fails_instead_of_evicting_l1(self):
        row=note('huge','z'*50000);row['important']=True
        with self.assertRaises(ChatStateError) as caught:self.build(notes=[row])
        self.assertEqual(caught.exception.code,'context_overflow')

    def test_empty_terms_no_false_memory_hit_and_external_role_is_data(self):
        messages,refs,r=self.build(Store([pair(1,'quoted claim','quote')]),[note('a','archive')],current='?',origin='external_ai')
        self.assertEqual([n['id'] for n in refs],['a']);self.assertTrue(r['no_retrieval_hit'])
        self.assertEqual(json.loads(messages[1]['content'])['origin'],'quote')
        self.assertEqual(json.loads(messages[-1]['content'])['category'],'provided_material')
        self.assertEqual(messages[2]['role'],'assistant')



if __name__=='__main__':unittest.main(verbosity=2)
