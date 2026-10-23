"""Workflow regressions using temporary SQLite files, never real learner data."""
import concurrent.futures
import copy
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from libao_modules.sample import SAMPLE
from workbench.bridge import Bridge as WorkbenchBridge
from optional_modules import OptionalModules


def Bridge(data_dir):
    # These tests exercise study behavior, independent of installed packages.
    return WorkbenchBridge(data_dir, modules=OptionalModules(Path(__file__).parent/'fixtures', data_dir))



class DailyStudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = Bridge(self.tmp.name)
        self.daily = self.bridge.daily

    def report(self, prompt=None):
        prompt = prompt or self.daily.prompt()
        result = json.loads(prompt["prompt"][prompt["prompt"].rfind("\n{")+1:])
        result.update(summary="完成纸上阅读的因果题与although句子答疑",
            discussion_completed=True,scenario="question_help",
            user_report={"material":"纸质练习","details":"我不理解although引导的两句关系。", "accuracy":None,"accuracy_basis":""},
            evidence="用户指出原文两句证据，并解释转折关系",
            activities=[dict(skill="reading",task="说明短文中的因果关系",
                response="It changed because the old route was no longer safe.",feedback="依据原文的网页分析")],
            weak_points=[dict(point="although让步关系需复查",evidence="用户首次把although解释为原因")],
            review_focus="下次先检查一个让步句")
        return result

    def text(self, result, language="json"):
        return "本次汇报如下：\n" + chr(96)*3 + language + "\n" + json.dumps(result,ensure_ascii=False) + "\n" + chr(96)*3 + "\n已按实际学习填写。"

    def count(self):
        return self.bridge.study.progress_summary()["submission_count"]

    def test_first_use_needs_no_material_or_setup(self):
        self.assertIsNone(self.daily.workspace()["pending_prompt"])
        prompt = self.daily.prompt()
        self.assertIn("纸",prompt["prompt"])
        self.assertNotIn("150–220",prompt["prompt"])
        self.assertEqual(3,prompt["plan"]["report_version"])
        self.assertNotIn('"provided_reference_answer"',prompt["prompt"])
        self.assertEqual(0,self.count())
        self.assertEqual([],self.bridge.store.reminders())

    def test_outputs_and_parse_are_not_learning(self):
        prompt = self.daily.prompt()
        r = self.report(prompt)
        self.daily.parse(self.text(r))
        self.assertEqual(0,self.count())
        self.assertEqual([],self.bridge.study.history())

    def test_pending_prompt_reused_after_restart(self):
        one = self.daily.prompt()
        two = Bridge(self.tmp.name).daily.prompt()
        self.assertEqual(one["prompt"],two["prompt"])
        self.assertEqual(one["handoff_id"],two["handoff_id"])
        self.assertTrue(two["reused"])

    def test_actual_report_persists_and_not_minutes_or_reminder(self):
        r = self.report()
        saved = self.daily.save(self.text(r))
        restarted = Bridge(self.tmp.name)
        self.assertEqual(1,restarted.study.progress_summary()["submission_count"])
        h = restarted.daily.workspace()["history"][0]
        self.assertEqual(r["summary"],h["summary"])
        self.assertEqual(r["weak_points"],h["weak_points"])
        self.assertEqual("unverified",h["outcome"])
        self.assertEqual(0,restarted.study.history()[0]["minutes"])
        self.assertIsNone(restarted.study.history()[0]["next_review"])
        self.assertIsNone(saved["reminder_id"])

    def test_duplicate_with_changed_format_has_same_receipt(self):
        r = self.report()
        one = self.daily.save(self.text(r))
        two = Bridge(self.tmp.name).daily.save(json.dumps(dict(reversed(list(r.items())))))
        self.assertEqual(one["session_id"],two["session_id"])
        self.assertTrue(two["already_saved"])
        self.assertEqual(1,self.count())

    def test_changed_saved_result_rejected(self):
        r = self.report()
        self.daily.save(self.text(r))
        r["summary"] = "后来改写的结果"
        with self.assertRaisesRegex(ValueError,"已经保存"):
            self.daily.save(self.text(r))
        self.assertEqual(1,self.count())

    def test_editing_input_before_save_uses_current_text(self):
        r = self.report()
        self.daily.parse(self.text(r))
        r["summary"] = "输入途中改为实际处理一个转折句"
        self.daily.save(self.text(r))
        self.assertEqual(r["summary"],self.daily.workspace()["history"][0]["summary"])

    def test_unknown_ids_and_wrong_version_never_write(self):
        base = self.report()
        for field,value in (("handoff_id","foreign"),("lesson_id","foreign"),("schema_version",True),("schema_version",9)):
            r = {**base,field:value}
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                self.daily.save(self.text(r))
        self.assertEqual(0,self.count())

    def test_wrong_contract_cannot_reuse_new_handoff(self):
        r = self.report()
        r.pop("activities")
        for key in ("scenario","discussion_completed","user_report","reference_findings"):
            r.pop(key)
        r["schema_version"]=1
        r["weak_points"]=[]
        with self.assertRaisesRegex(ValueError,"新版"):
            self.daily.save(self.text(r))
        self.assertEqual(0,self.count())

    def test_malformed_report_never_leaves_partial_rows(self):
        r = self.report()
        for raw in ("plain text","{broken",self.text(r)+"\n"+self.text(r),
                    '{"schema_version":2,"schema_version":2}', '{"a":NaN}'):
            with self.subTest(raw=raw[:20]),self.assertRaises(ValueError):
                self.daily.save(raw)
        self.assertEqual(0,self.count())
        with self.bridge.store.connection() as db:
            self.assertEqual(0,db.execute("SELECT COUNT(*) FROM study_web_reports").fetchone()[0])

    def test_crlf_and_uppercase_json_report(self):
        r = self.report()
        self.daily.save(self.text(r,"JSON").replace("\n","\r\n"))
        self.assertEqual(1,self.count())

    def test_empty_activity_and_template_are_not_learning(self):
        prompt = self.daily.prompt()
        template = json.loads(prompt["prompt"][prompt["prompt"].rfind("\n{")+1:])
        with self.assertRaises(ValueError):
            self.daily.save(self.text(template))
        r = self.report(prompt)
        r["activities"]=[]
        with self.assertRaises(ValueError):
            self.daily.save(self.text(r))
        self.assertEqual(0,self.count())

    def test_weak_point_without_evidence_rejected(self):
        r = self.report()
        r["weak_points"]=[{"point":"单词不认识","evidence":""}]
        with self.assertRaises(ValueError):
            self.daily.save(self.text(r))
        self.assertEqual(0,self.count())

    def test_unknown_question_and_option_rejected(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        r = self.report(self.daily.prompt(lid))
        for answers in ({"foreign":"B"},{"1":"not-an-option"}):
            r["answers"]=answers
            with self.assertRaises(ValueError):
                self.daily.save(self.text(r))
        self.assertEqual(0,self.count())

    def test_local_reference_result_separate_from_web_claim(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        r = self.report(self.daily.prompt(lid))
        r.update(answers={"1":"B"},assessment="incorrect",basis="passage_inference")
        saved = self.daily.save(self.text(r))
        self.assertEqual("correct",saved["local_evaluation"]["outcome"])
        with self.bridge.store.connection() as db:
            stored = json.loads(db.execute("SELECT report FROM study_web_reports").fetchone()[0])
        self.assertEqual("incorrect",stored["assessment"])
        self.assertEqual("correct",self.bridge.study.history()[0]["outcome"])

    def test_web_correct_does_not_verify_free_response(self):
        r = self.report()
        r.update(assessment="correct",basis="reference_material",
            reference_findings=[{"conclusion":"参考解析支持该句让步关系","source":"用户提供的纸质练习解析", "evidence":"解析明确指出although引导让步从句"}])
        self.daily.save(self.text(r))
        self.assertEqual("unverified",self.bridge.study.history()[0]["outcome"])

    def test_material_changes_invalidate_old_unsaved_report(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        first = self.daily.prompt(lid)
        r = self.report(first)
        with self.bridge.store.connection() as db:
            payload = json.loads(db.execute("SELECT payload FROM lessons WHERE id=?",(lid,)).fetchone()[0])
            payload["passage"] += "\nMaterial revised."
            db.execute("UPDATE lessons SET payload=? WHERE id=?",(json.dumps(payload),lid))
        self.assertIsNone(self.daily.workspace()["pending_prompt"])
        with self.assertRaisesRegex(ValueError,"更新"):
            self.daily.save(self.text(r))
        new = self.daily.prompt(lid)
        self.assertNotEqual(first["handoff_id"],new["handoff_id"])
        self.assertEqual(0,self.count())

    def test_saved_receipt_survives_later_material_question_edits(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        r = self.report(self.daily.prompt(lid))
        r["answers"] = {"1":"B"}
        first = self.daily.save(self.text(r))
        with self.bridge.store.connection() as db:
            payload = json.loads(db.execute("SELECT payload FROM lessons WHERE id=?",(lid,)).fetchone()[0])
            payload["questions"][0]["id"] = "new-question"
            db.execute("UPDATE lessons SET payload=? WHERE id=?",(json.dumps(payload),lid))
        repeated = self.daily.save(self.text(r))
        self.assertEqual(first["session_id"],repeated["session_id"])
        self.assertTrue(repeated["already_saved"])
        self.assertEqual(1,self.count())

    def test_old_prompt_return_after_new_save_is_append_only(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        old = self.report(self.daily.prompt(lid))
        # Simulate one real later legacy submission without changing the material.
        existing = self.bridge.study.record(lid,{"1":"B"},note="另一份已保存的实际作答")
        self.daily.save(self.text(old))
        ids = [r["id"] for r in self.bridge.study.history(lid)]
        self.assertIn(existing,ids)
        self.assertEqual(2,len(ids))
        self.assertEqual(2,self.count())

    def test_next_prompt_after_save_is_new_with_background(self):
        first = self.daily.prompt()
        self.daily.save(self.text(self.report(first)))
        next_ = self.daily.prompt()
        self.assertNotEqual(first["handoff_id"],next_["handoff_id"])
        self.assertIn("although让步关系需复查",next_["prompt"])
        self.assertEqual(1,self.count())

    def test_legacy_report_auto_identified_without_material_selection(self):
        lid = self.bridge.study.import_lesson(SAMPLE)
        prompt = self.bridge.handoff.prepare_prompt(lid)
        r = json.loads(prompt[prompt.rfind("\n{")+1:])
        r.update(answers={"1":"B"},summary="实际学习题1",evidence="原文证据",weak_points=[],review_focus="")
        receipt = self.daily.save(self.text(r))
        self.assertFalse(receipt["already_saved"])
        self.assertTrue(self.daily.save(self.text(r))["already_saved"])
        self.assertEqual(1,self.count())

    def test_v2_database_preserved_and_old_code_can_read_new_records(self):
        # Use the exact source package's schema, not the revised Store implementation.
        import ast
        source=Path(__file__).parents[1]/"tests/fixtures/v2_schema.sql"
        db_path=Path(self.tmp.name)/"modules/hebao_modules.sqlite3"
        db_path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.executescript(source.read_text(encoding="utf-8"))
            payload=copy.deepcopy(SAMPLE)
            db.execute("INSERT INTO lessons VALUES (?,?,?,?)",("legacy",payload["title"],json.dumps(payload),"2026-10-01T00:00:00+00:00"))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("kept","legacy",'{"1":"B"}',"unverified",'["旧标签"]',"旧笔记","旧来源",7,"2026-10-01T00:00:00+00:00",None))
        new = Bridge(self.tmp.name)
        self.assertEqual("旧笔记",new.study.history()[0]["note"])
        self.assertEqual(7,new.study.history()[0]["minutes"])
        r = self.report(new.daily.prompt("legacy"))
        new.daily.save(self.text(r))
        with closing(sqlite3.connect(db_path)) as db, db:
            self.assertEqual(2,db.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(2,db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            # Legacy table shape is unchanged, so v2 old readers can select it.
            self.assertEqual(10,len(db.execute("PRAGMA table_info(sessions)").fetchall()))

    def test_parallel_repeat_saves_exactly_once(self):
        r = self.report()
        raw = self.text(r)
        bridges = [Bridge(self.tmp.name) for _ in range(6)]
        for b in bridges:
            b.daily.workspace()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            receipts=list(pool.map(lambda b:b.daily.save(raw),bridges))
        self.assertEqual(1,len({r["session_id"] for r in receipts}))
        self.assertEqual(1,self.count())

    def test_bridge_contract_rejects_extra_controls(self):
        raw = self.text(self.report())
        with self.assertRaises(ValueError):
            self.bridge.call({"command":"daily.save","params":{"text":raw,"verified":True}})
        with self.assertRaises(ValueError):
            self.bridge.call({"command":"daily.prompt","params":{"minutes":15}})
        self.assertEqual(0,self.count())

    def test_export_includes_new_metadata_and_preserves_legacy(self):
        self.daily.save(self.text(self.report()))
        data=json.loads(self.bridge.store.export_json())["data"]
        self.assertEqual(1,len(data["sessions"]))
        self.assertEqual(1,len(data["study_web_reports"]))
        self.assertEqual(1,len(data["study_prompt_cache"]))


if __name__=="__main__":
    unittest.main(verbosity=2)
