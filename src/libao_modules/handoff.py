"""Manual web-chat handoff: parse a data draft, then explicitly commit it."""
from datetime import datetime, timezone
import hashlib
import json
import re

from .core import choice, now_iso, text_value, timestamp, uid
from .registry import canonical
from .security import strict_json


FIELDS = {"schema_version", "handoff_id", "lesson_id", "answers", "assessment", "basis", "weak_points", "summary", "evidence", "review_focus"}
ASSESSMENTS = {"unverified", "correct", "incorrect", "partial"}
BASES = {"reference_material", "passage_inference", "not_checked"}


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def decode_result(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > 100_000:
        raise ValueError("回填文字须在100KB内")
    text = text.strip()
    if "```" in text:
        blocks = re.findall(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text, re.IGNORECASE)
        if len(blocks) != 1 or text.count("```") != 2:
            raise ValueError("请只粘贴一个JSON回填块；多个代码块不能确定属于哪次学习")
        text = blocks[0]
    return strict_json(text, max_bytes=100_000)


class WebHandoff:
    def __init__(self, study):
        self.study = study
        self.store = study.store

    def prepare_prompt(self, lid, mode="practice"):
        from .prompts import build_prompt
        lesson = self.study.lesson(lid)
        recent = self.study.history(lid, 1)
        session = recent[0] if recent else None
        prompt = build_prompt(lesson, session, mode)
        hid = uid("handoff")
        # This records a handoff identity, not a completed learning session.
        with self.store.connection() as db:
            db.execute("INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,?,?)",
                       (hid, lid, digest(lesson), session["id"] if session else None, mode, now_iso(), None, None, None))
        sample = dict(schema_version=1, handoff_id=hid, lesson_id=lid,
                      answers={q["id"]: "填写我的实际作答；尚未作答的题不要放入" for q in lesson["questions"]},
                      assessment="unverified", basis="not_checked", weak_points=[],
                      summary="本次实际处理的内容", evidence="判断依据；缺少核验时明确说明", review_focus="下次建议检查什么")
        return prompt + "\n\n【学习结束后的回填约定】\n" + (
            "结束学习时，先给简短总结，再单独输出一个JSON代码块，遵循下面字段。不要一开始输出回填块。\n"
            "原样保留schema_version、handoff_id、lesson_id，不生成新编号；只填实际观察到的作答和薄弱点。\n"
            "answers的键必须使用下方模板中的本地题号；未作答的题省略。若材料是原样粘贴的整组题，"
            "则将真实题号与选项合并为本地1题的一段作答文字。不要重复填空模板内容。\n"
            "assessment仅用unverified/correct/incorrect/partial；basis仅用reference_material/passage_inference/not_checked。"
            "这是你的分析建议，不意味着用户已核对。没有参考依据就不要称官方答案。\n"
            "不要增加字段，不估计学习分钟数、不安排提醒、不输出工具调用或执行代码。\n"
        ) + json.dumps(sample, ensure_ascii=False, indent=2)

    def _validated(self, value, expected_lid=None):
        if not isinstance(value, dict) or value.keys() != FIELDS:
            missing = FIELDS - value.keys() if isinstance(value, dict) else FIELDS
            extra = value.keys() - FIELDS if isinstance(value, dict) else set()
            raise ValueError(f"回填字段不匹配；缺少：{', '.join(sorted(missing)) or '无'}；多余：{', '.join(sorted(extra)) or '无'}")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("不支持该回填格式版本")
        hid = text_value(value["handoff_id"], "交接编号", 100)
        lid = text_value(value["lesson_id"], "材料编号", 100)
        if expected_lid is not None and lid != expected_lid:
            raise ValueError("回填属于另一份材料；请选择对应材料后再读取")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM handoffs WHERE id=?", (hid,)).fetchone()
        if row is None or row["lesson_id"] != lid:
            raise ValueError("找不到匹配的本地交接编号；请使用莉宝生成的完整提示词")
        if row["mode"] == "daily":
            raise ValueError("这次提示词使用新版汇报，请复制它对应的完整结束汇报。")
        lesson = self.study.lesson(lid)
        if digest(lesson) != row["lesson_hash"]:
            raise ValueError("材料已改变，请重新生成提示词，避免把旧结果写到新材料")
        choice(value["assessment"], "网页判断", ASSESSMENTS)
        choice(value["basis"], "网页自报依据", BASES)
        clean = {**value, "handoff_id": hid, "lesson_id": lid}
        for key, maximum, required in (("summary", 5000, True), ("evidence", 2000, True), ("review_focus", 1000, False)):
            clean[key] = text_value(value[key], key, maximum, required)
        # Reuse session validation without inserting a session.
        values = self.study._record_values(lid, value["answers"], tags=value["weak_points"])
        clean["answers"] = json.loads(values[2])
        clean["weak_points"] = json.loads(values[4])
        return clean, dict(row)

    def parse(self, lid, text):
        clean, handoff = self._validated(decode_result(text), lid)
        warnings = ["网页判断属于待核对建议；读取草稿不会保存学习结果。"]
        if clean["basis"] != "reference_material":
            warnings.append("网页没有自报使用参考答案，不能当作官方核对结果。")
        latest = self.study.history(lid, 1)
        if latest and latest[0]["id"] != handoff["base_session_id"]:
            warnings.append("生成提示词之后，本地已有新的学习记录；请确认这是要回填的那次学习。")
        if handoff["result_session_id"]:
            warnings.append("这次交接已经保存过；相同内容重复提交不会重复记账，改变内容请另建记录。")
        return {"result": clean, "warnings": warnings, "already_saved": handoff["result_session_id"] is not None}

    def commit(self, result, *, minutes=0, verified=False, review_at=None, create_reminder=False):
        if type(verified) is not bool or type(create_reminder) is not bool:
            raise ValueError("核对和提醒开关须为布尔值")
        clean, handoff = self._validated(result)
        if review_at is not None:
            review_at = datetime.fromtimestamp(timestamp(review_at), timezone.utc).isoformat(timespec="seconds")
        if create_reminder and review_at is None:
            raise ValueError("创建复习提醒前，请选择复习时间")
        source = ("网页GPT回填；网页自报依据：" + clean["basis"] +
                  ("；用户明确确认已核对" if verified else "；用户尚未核对判断"))
        note = (clean["summary"] + "\n网页判断建议：" + clean["assessment"] +
                "\n依据：" + clean["evidence"] + "\n复习方向：" + clean["review_focus"])
        values = self.study._record_values(clean["lesson_id"], clean["answers"],
            clean["assessment"] if verified else "unverified", clean["weak_points"], note, minutes, source, review_at)
        receipt = digest({"result": clean, "minutes": minutes, "verified": verified,
                          "review_at": review_at, "create_reminder": create_reminder})
        rid = uid("reminder") if create_reminder else None
        title = text_value("复习：" + self.study.lesson(clean["lesson_id"])["title"], "提醒标题", 300)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            live = db.execute("SELECT * FROM handoffs WHERE id=?", (clean["handoff_id"],)).fetchone()
            if live is None:
                raise ValueError("交接记录已不存在，未写入")
            # Verify the current persisted lesson inside the same write transaction.
            stored = db.execute("SELECT payload FROM lessons WHERE id=?", (clean["lesson_id"],)).fetchone()
            current_lesson = {"id": clean["lesson_id"], **json.loads(stored["payload"])}
            if digest(current_lesson) != live["lesson_hash"]:
                raise ValueError("材料已改变，未写入")
            if live["result_session_id"]:
                if live["result_digest"] != receipt:
                    raise ValueError("本次交接已保存；修改结果请重新生成提示词或手动追加记录")
                return {"session_id": live["result_session_id"], "reminder_id": live["result_reminder_id"], "already_saved": True}
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", values)
            if rid:
                db.execute("INSERT INTO reminders VALUES (?,?,?,?)", (rid, title, timestamp(review_at), "pending"))
            db.execute("UPDATE handoffs SET result_session_id=?,result_digest=?,result_reminder_id=? WHERE id=?",
                       (values[0], receipt, rid, clean["handoff_id"]))
        return {"session_id": values[0], "reminder_id": rid, "already_saved": False}
