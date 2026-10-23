"""Paper review/help cases and migration from actual v01 JSON exports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from workbench.bridge import Bridge as WorkbenchBridge
from optional_modules import OptionalModules


def Bridge(data_dir):
    # These tests exercise study behavior, independent of installed packages.
    return WorkbenchBridge(data_dir, modules=OptionalModules(Path(__file__).parent/'fixtures', data_dir))

from libao_modules.sample import SAMPLE


class PaperStudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.bridge=Bridge(self.tmp.name);self.daily=self.bridge.daily

    def prompt(self,lid=None):
        return self.daily.prompt(lid)

    def report(self,scenario='question_help',prompt=None):
        p=prompt or self.prompt()
        r=json.loads(p['prompt'][p['prompt'].rfind('\n{')+1:])
        r.update(scenario=scenario,discussion_completed=True,summary='解释although引导的让步关系，并整理一个笔记要点',
            evidence='用户提供了Although it was late, she stayed句子，认为是因果关系',
            user_report={'material':'用户纸质六级练习','details':'Although it was late, she stayed. 我认为前半句表示原因，对吗？','accuracy':None,'accuracy_basis':''},
            activities=[{'skill':'reading','task':'解释用户提供的句子连接关系','response':'我认为although表示原因。','feedback':'although表示尽管，前后构成让步；主句是she stayed。可记为：虽然很晚，她仍留下了。'}],
            weak_points=[{'point':'让步与因果连接混淆','evidence':'用户认为although表示原因'}],review_focus='下次遇到连接词先看两部分关系；无需另做一套题')
        return r

    def save(self,r):return self.daily.save(json.dumps(r,ensure_ascii=False))
    def count(self):return self.bridge.study.progress_summary()['submission_count']

    def load_v01(self):
        f=json.loads((Path(__file__).parent/'fixtures/v01_reports.json').read_text(encoding='utf-8'))
        with self.bridge.store.connection() as db:
            for table,rows in f['data'].items():
                for row in rows:
                    names=list(row)
                    db.execute('INSERT OR REPLACE INTO '+table+' ('+','.join(names)+') VALUES ('+','.join('?' for _ in names)+')',[row[n] for n in names])
        return f

    def test_default_waits_for_paper_input_without_exercise_or_quiz(self):
        p=self.prompt();text=p['prompt']
        self.assertIn('先等待我提交',text)
        self.assertIn('收到问题后直接讲解',text)
        self.assertNotIn('先给材料、问一个问题',text)
        self.assertNotIn('150–220',text)
        self.assertNotIn('每轮只问一个理解问题',text)
        self.assertEqual('user_supplied_later',p['plan']['material_kind'])
        self.assertNotIn('suggested_minutes',p['plan'])
        self.assertEqual([],self.bridge.study.lesson(p['lesson_id'])['questions'])
        self.assertEqual(0,self.count())

    def test_teacher_update_refreshes_output_but_keeps_prior_handoff_savable(self):
        old=self.prompt();report=self.report(prompt=old)
        cached='旧版教师提示词；保留既有交接以接收已完成的汇报'
        with self.bridge.store.connection() as db:
            db.execute('UPDATE study_prompt_cache SET prompt=? WHERE handoff_id=?',(cached,old['handoff_id']))
        self.assertIsNone(self.daily.workspace()['pending_prompt'])
        new=self.prompt()
        self.assertNotEqual(old['handoff_id'],new['handoff_id'])
        self.assertFalse(new['reused']);self.assertEqual(new['handoff_id'],self.prompt()['handoff_id'])
        saved=self.save(report)
        self.assertFalse(saved['already_saved']);self.assertEqual(1,self.count())
        self.assertTrue(self.save(report)['already_saved'])
        with self.bridge.store.connection() as db:
            self.assertEqual(cached,db.execute('SELECT prompt FROM study_prompt_cache WHERE handoff_id=?',(old['handoff_id'],)).fetchone()[0])

    def test_paper_review_with_user_accuracy_and_difficulty_does_not_create_local_verdict(self):
        r=self.report('exam_review')
        r['user_report']={'material':'纸上练习第3套','details':'我做完阅读，自述正确率60%，错题集中在让步句，长句主干找不到。','accuracy':60,'accuracy_basis':'用户自述本次阅读部分60%；不是整卷成绩'}
        saved=self.save(r)
        self.assertEqual(60,saved['user_report']['accuracy'])
        self.assertIsNone(saved['local_evaluation'])
        h=Bridge(self.tmp.name).daily.workspace()['history'][0]
        self.assertEqual('exam_review',h['scenario']);self.assertEqual(r['user_report'],h['user_report'])
        self.assertEqual('unverified',h['outcome']);self.assertEqual(1,self.count())
        self.assertEqual(0,self.bridge.study.history()[0]['minutes']);self.assertEqual([],self.bridge.store.reminders())

    def test_question_help_needs_no_second_student_answer(self):
        r=self.report();r['activities'][0]['response']=r['user_report']['details']
        saved=self.save(r)
        self.assertFalse(saved['already_saved']);self.assertEqual('question_help',saved['scenario'])
        self.assertEqual(1,self.count());self.assertEqual({},self.bridge.study.history()[0]['answers'])

    def test_unknown_accuracy_and_ability_stay_unknown(self):
        self.save(self.report())
        report=json.loads(self.bridge.store.export_json())['data']['study_web_reports'][0]['report']
        r=json.loads(report)
        self.assertIsNone(r['user_report']['accuracy'])
        self.assertNotIn('mastery',r);self.assertNotIn('minutes',r)
        text=self.prompt()['prompt'];self.assertIn('"accuracy": null',text)
        self.assertNotIn('"accuracy": 0',text)

    def test_report_requires_actual_discussion_and_input(self):
        r=self.report()
        cases=[]
        for flag in (False,None,1,'true'):
            cases.append({**r,'discussion_completed':flag})
        for feedback in ('','等待用户提交','尚未答疑','填写实际讲解'):
            x=copy.deepcopy(r);x['activities'][0]['feedback']=feedback;cases.append(x)
        x=copy.deepcopy(r);x['user_report']['details']='';cases.append(x)
        x=copy.deepcopy(r);x['activities']=[];cases.append(x)
        for bad in cases:
            with self.subTest(case=str(bad)[:50]),self.assertRaises(ValueError):self.save(bad)
        self.assertEqual(0,self.count())

    def test_user_accuracy_needs_explicit_basis_and_valid_percent(self):
        r=self.report()
        for rate in (True,-1,101,'60%',{},[]):
            x=copy.deepcopy(r);x['user_report'].update(accuracy=rate,accuracy_basis='用户自述')
            with self.subTest(rate=rate),self.assertRaises(ValueError):self.save(x)
        x=copy.deepcopy(r);x['user_report']['accuracy']=60
        with self.assertRaises(ValueError):self.save(x)
        self.assertEqual(0,self.count())

    def test_equivalent_percent_number_formats_do_not_duplicate(self):
        r=self.report('exam_review');r['user_report'].update(accuracy=60,accuracy_basis='用户自述')
        first=self.save(r);r['user_report']['accuracy']=60.0
        repeated=self.save(r)
        self.assertTrue(repeated['already_saved']);self.assertEqual(first['session_id'],repeated['session_id'])
        self.assertEqual(1,self.count())

    def test_reference_supported_web_conclusion_is_separate_from_local_comparison(self):
        r=self.report();r.update(assessment='correct',basis='reference_material',reference_findings=[{'conclusion':'该句表达让步','source':'用户提供的练习册解析','evidence':'用户提供的解析将although译为尽管'}])
        self.save(r);card=self.daily.workspace()['history'][0]
        self.assertEqual(r['reference_findings'],card['reference_findings']);self.assertIsNone(card['local_evaluation'])
        self.assertEqual('unverified',card['outcome'])

    def test_reference_claim_missing_source_or_evidence_is_rejected(self):
        r=self.report();r['basis']='reference_material'
        with self.assertRaisesRegex(ValueError,'来源和依据'):self.save(r)
        for field in ('source','evidence','conclusion'):
            x=copy.deepcopy(r);x['reference_findings']=[{'conclusion':'支持让步关系','source':'用户练习册','evidence':'解析中的连接词说明'}];x['reference_findings'][0][field]=''
            with self.subTest(field=field),self.assertRaises(ValueError):self.save(x)
        self.assertEqual(0,self.count())

    def test_next_prompt_includes_topics_user_feedback_evidence_and_last_suggestion_across_materials(self):
        r=self.report('exam_review');self.save(r)
        lid=self.bridge.study.import_lesson(SAMPLE)
        prompt=self.prompt(lid)['prompt']
        for fragment in (r['summary'],r['user_report']['details'],r['weak_points'][0]['evidence'],r['review_focus'],r['activities'][0]['feedback']):self.assertIn(fragment,prompt)
        self.assertIn('user_self_report',prompt);self.assertIn('reference_supported_web_findings',prompt)
        self.assertIn('local_imported_answer_comparison',prompt)

    def test_long_history_is_bounded_without_shortening_saved_reports(self):
        for index in range(5):
            r=self.report()
            r['summary']='本次总结'+str(index)+'内容'*2000
            r['user_report']['details']='用户原话'+str(index)+'内容'*2900
            r['activities']=[dict(skill='reading',task='实际问题'*100,
                response='原回答'*1500,feedback='实际解释'*350) for _ in range(2)]
            r['weak_points']=[dict(point='困难'+str(n),evidence='实际依据'*240) for n in range(4)]
            r['reference_findings']=[dict(conclusion='分析'*300,source='练习册'*100,evidence='参考内容'*450) for _ in range(2)]
            r['review_focus']='旧建议'*300
            self.save(r)
        before=self.bridge.store.export_json()
        context=self.daily._learning_context(self.bridge.study.history(limit=5))
        self.assertLessEqual(len(json.dumps(context['recent_learning'],ensure_ascii=False)),7000)
        self.assertEqual(5,len(context['recent_learning'])+context['omitted_recent_records'])
        self.assertEqual(self.daily.workspace()['history'][0]['saved_at'],context['recent_learning'][0]['saved_at'])
        self.assertEqual(before,self.bridge.store.export_json())
        self.assertEqual(r['user_report']['details'],self.daily.workspace()['history'][0]['user_report']['details'])
        self.assertNotEqual(r['review_focus'],context['suggested_attention'])

    def test_large_objective_comparison_keeps_counts_and_source_not_all_answers(self):
        sample=copy.deepcopy(SAMPLE)
        sample['questions']=[{**sample['questions'][0],'id':str(index)} for index in range(10)]
        lid=self.bridge.study.import_lesson(sample)
        r=self.report(prompt=self.prompt(lid))
        r['answers']={str(index):'B' for index in range(10)}
        self.save(r)
        context=self.daily._learning_context(self.bridge.study.history(limit=5))
        comparison=context['recent_learning'][0]['local_imported_answer_comparison']
        self.assertEqual(10,comparison['submitted_count'])
        self.assertEqual(10,comparison['correct_count'])
        self.assertEqual('submitted_questions_only',comparison['scope'])
        self.assertNotIn('questions',comparison)
        self.assertIn(sample['source'],comparison['source'])
        self.assertEqual(10,len(self.daily.workspace()['history'][0]['local_evaluation']['questions']))

    def test_restart_resumes_new_prompt_exactly_and_old_accepted_report_once(self):
        p=self.prompt();new=Bridge(self.tmp.name).daily
        self.assertEqual(p['prompt'],new.prompt()['prompt'])
        r=self.report(prompt=p);new.save(json.dumps(r,ensure_ascii=False))
        self.assertTrue(Bridge(self.tmp.name).daily.save(json.dumps(r,ensure_ascii=False))['already_saved'])
        self.assertEqual(1,self.count())

    def test_genuine_v01_saved_receipt_and_pending_report_are_compatible(self):
        f=self.load_v01();saved=self.save(f['saved_report'])
        self.assertTrue(saved['already_saved']);self.assertEqual(1,self.count())
        self.assertIsNone(self.daily.workspace()['pending_prompt'])
        receipt=self.save(f['pending_report']);self.assertFalse(receipt['already_saved']);self.assertEqual(2,self.count())
        self.assertTrue(self.save(f['pending_report'])['already_saved'])
        self.assertEqual(f['saved_report']['summary'],self.daily.workspace()['history'][1]['summary'])

    def test_old_material_and_records_are_not_rewritten_when_new_prompt_created(self):
        f=self.load_v01()
        before=self.bridge.study.lesson(f['saved_report']['lesson_id'])
        records=self.bridge.study.history()
        p=self.prompt()
        self.assertNotEqual(before['id'],p['lesson_id']);self.assertEqual(before,self.bridge.study.lesson(before['id']))
        self.assertEqual(records,self.bridge.study.history())
        self.assertIn(f['saved_report']['summary'],p['prompt'])
        self.assertIn('v01',self.bridge.store.export_json())

    def test_pending_background_refreshes_after_other_material_save(self):
        first=self.prompt();lid=self.bridge.study.import_lesson(SAMPLE)
        other=self.report(prompt=self.prompt(lid));self.save(other)
        next_=self.prompt();self.assertNotEqual(first['handoff_id'],next_['handoff_id'])
        self.assertIn(other['summary'],next_['prompt'])
        old=self.report(prompt=first);self.assertIn('旧提示词',' '.join(self.daily.parse(json.dumps(old))['warnings']))
        self.save(old);self.assertEqual(2,self.count())

    def test_no_extra_fields_or_false_learning_controls(self):
        r=self.report();r['minutes']=15
        with self.assertRaises(ValueError):self.save(r)
        self.assertEqual(0,self.count())

if __name__=='__main__':unittest.main()
