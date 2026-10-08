"""Local data and prompt logic; no network, GUI, workers or recurring jobs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from .security import export_destination


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex


def text_value(value, name, maximum=100_000, required=True):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{name}必须是长度不超过{maximum}的文字")
    if required and not value.strip():
        raise ValueError(f"{name}不能为空")
    return value.strip()


def choice(value, name, allowed):
    if value not in allowed:
        raise ValueError(f"{name}须为：{', '.join(sorted(allowed))}")
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区，例如2026-10-02T20:00:00+08:00")
    return parsed.timestamp()


SCHEMA = """
CREATE TABLE IF NOT EXISTS lessons (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id),
 answers TEXT NOT NULL, outcome TEXT NOT NULL, tags TEXT NOT NULL,
 note TEXT NOT NULL, source TEXT NOT NULL, minutes INTEGER NOT NULL,
 recorded_at TEXT NOT NULL, next_review TEXT);
CREATE INDEX IF NOT EXISTS sessions_lesson ON sessions(lesson_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS sessions_review ON sessions(next_review);
CREATE INDEX IF NOT EXISTS sessions_recorded ON sessions(recorded_at);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 source TEXT NOT NULL, occurred_at TEXT NOT NULL, created_at TEXT NOT NULL,
 decision TEXT NOT NULL, implementation TEXT NOT NULL, auto_check TEXT NOT NULL,
 manual_check TEXT NOT NULL, evidence TEXT NOT NULL, scope TEXT NOT NULL,
 memory_confirmed INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 superseded_by TEXT REFERENCES records(id));
CREATE INDEX IF NOT EXISTS records_current ON records(active, memory_confirmed, created_at DESC);
CREATE TABLE IF NOT EXISTS reminders (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, due_epoch REAL NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','queued','delivered','cancelled')));
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status, due_epoch);
CREATE TABLE IF NOT EXISTS handoffs (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id),
 lesson_hash TEXT NOT NULL, base_session_id TEXT REFERENCES sessions(id),
 mode TEXT NOT NULL, created_at TEXT NOT NULL,
 result_session_id TEXT REFERENCES sessions(id), result_digest TEXT,
 result_reminder_id TEXT REFERENCES reminders(id));
CREATE TABLE IF NOT EXISTS module_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS study_prompt_cache (
 handoff_id TEXT PRIMARY KEY REFERENCES handoffs(id),
 prompt TEXT NOT NULL, plan TEXT NOT NULL, schema_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS study_web_reports (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 report TEXT NOT NULL, local_evaluation TEXT NOT NULL);
PRAGMA user_version = 2;
"""


class Store:
    """Connections live only for the duration of an explicit data operation."""

    def __init__(self, path):
        self.path = Path(path)
        self._ready = False

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=1.0)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            if not self._ready:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError(f"不支持数据库版本{version}；未改写数据")
                db.executescript(SCHEMA)
                db.execute("INSERT OR IGNORE INTO module_meta VALUES (?,?)", ("first_used_at", now_iso()))
                db.execute("INSERT OR IGNORE INTO module_meta VALUES (?,?)", ("usage_tracking_version", "v01.2"))
                db.commit()
                self._ready = True
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_reminder(self, title, due):
        title = text_value(title, "提醒内容", 300)
        epoch = timestamp(due)
        rid = uid("reminder")
        with self.connection() as db:
            db.execute("INSERT INTO reminders VALUES (?,?,?,?)", (rid, title, epoch, "pending"))
        return rid

    def reminders(self, limit=100):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM reminders ORDER BY due_epoch DESC LIMIT ?", (min(limit, 200),))]

    def cancel_reminder(self, rid):
        with self.connection() as db:
            db.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (rid,))

    def next_due(self):
        with self.connection() as db:
            return db.execute("SELECT MIN(due_epoch) FROM reminders WHERE status='pending'").fetchone()[0]

    def take_due(self, epoch, quiet=False):
        with self.connection() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM reminders WHERE status='pending' AND due_epoch<=? ORDER BY due_epoch LIMIT 100", (epoch,))]
            state = "queued" if quiet else "delivered"
            db.executemany("UPDATE reminders SET status=? WHERE id=?", [(state, r["id"]) for r in rows])
        return rows

    def take_queued(self):
        with self.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM reminders WHERE status='queued' ORDER BY due_epoch")]
            db.executemany("UPDATE reminders SET status='delivered' WHERE id=?", [(r["id"],) for r in rows])
        return rows

    def requeue(self, rows):
        with self.connection() as db:
            # A notification callback can cancel a reminder before failing.
            # Failure recovery must not undo that explicit cancellation.
            db.executemany("UPDATE reminders SET status='queued' WHERE id=? AND status='delivered'", [(r["id"],) for r in rows])

    def export_json(self):
        with self.connection() as db:
            data = {table: [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
                    for table in ("lessons", "sessions", "records", "reminders", "handoffs", "module_meta",
                                  "study_prompt_cache", "study_web_reports")}
        return json.dumps({"schema_version": 2, "exported_at": now_iso(), "data": data}, ensure_ascii=False, indent=2)

    def backup(self, destination):
        """User-requested SQLite backup; do not overwrite the live database."""
        destination = export_destination(destination, suffixes={".sqlite3", ".sqlite", ".db"}, protected_paths=(self.path,))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            # Reserve a new file exclusively before asking SQLite to open it.
            # Never truncate a file that appeared after path validation.
            with destination.open("xb"):
                pass
            try:
                target = sqlite3.connect(destination)
                try:
                    db.backup(target)
                finally:
                    target.close()
            except Exception:
                destination.unlink(missing_ok=True)
                raise


class StudyModule:
    def __init__(self, store):
        self.store = store

    def import_lesson(self, payload):
        if not isinstance(payload, dict) or len(json.dumps(payload, ensure_ascii=False).encode()) > 500_000:
            raise ValueError("题目须为JSON对象，且不超过500KB")
        if payload.keys() - {"title", "passage", "source", "questions"}:
            raise ValueError("题目包含未约定字段；不接受命令或工具配置")
        title = text_value(payload.get("title"), "标题", 200)
        passage = text_value(payload.get("passage"), "阅读材料")
        source = text_value(payload.get("source", "用户导入；来源未标注"), "材料来源", 1000)
        items = payload.get("questions")
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError("每份阅读材料须含1—10个问题")
        questions, ids = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("问题须为对象")
            if item.keys() - {"id", "stem", "options", "answer", "rationale", "hints"}:
                raise ValueError("问题包含未约定字段")
            qid = text_value(item.get("id"), "题号", 30)
            if qid in ids:
                raise ValueError("同一材料内题号不能重复")
            ids.add(qid)
            stem = text_value(item.get("stem"), "题干", 5000)
            options = item.get("options", {})
            if not isinstance(options, dict) or len(options) > 8:
                raise ValueError("选项须为最多8项的对象")
            normalized_options = {}
            for key, value in options.items():
                key = text_value(key, "选项编号", 10)
                if key in normalized_options:
                    raise ValueError("去除空白后选项编号重复")
                normalized_options[key] = text_value(value, "选项内容", 5000)
            options = normalized_options
            answer = item.get("answer")
            if answer is not None:
                answer = text_value(answer, "参考答案", 1000)
                if options and answer not in options:
                    raise ValueError("参考答案须对应已有选项")
            rationale = text_value(item.get("rationale", ""), "参考解析", 10_000, required=False)
            hints = item.get("hints", [])
            if not isinstance(hints, list) or len(hints) > 5:
                raise ValueError("每题预写提示须为最多5项的列表")
            hints = [text_value(value, "预写提示", 1000) for value in hints]
            questions.append(dict(id=qid, stem=stem, options=options, answer=answer, rationale=rationale, hints=hints))
        clean = dict(title=title, passage=passage, source=source, questions=questions)
        lid = uid("lesson")
        with self.store.connection() as db:
            db.execute("INSERT INTO lessons VALUES (?,?,?,?)",
                       (lid, title, json.dumps(clean, ensure_ascii=False), now_iso()))
        return lid

    def lesson(self, lid):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
        if row is None:
            raise ValueError("找不到这份阅读材料")
        return {"id": lid, **json.loads(row["payload"])}

    def lessons(self):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,title,created_at FROM lessons ORDER BY created_at DESC LIMIT 200")]

    def record(self, lid, answers, outcome="unverified", tags=(), note="", minutes=0,
               source="用户手动记录；尚未核验", next_review=None):
        values = self._record_values(lid, answers, outcome, tags, note, minutes, source, next_review)
        with self.store.connection() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)", values)
        return values[0]

    def evaluate(self, lid, answers):
        """Compare submitted objective choices with imported keys. No write or diagnosis."""
        values = self._record_values(lid, answers)
        submitted = json.loads(values[2])
        lesson = self.lesson(lid)
        rows = []
        for question in lesson["questions"]:
            qid = question["id"]
            if qid not in submitted:
                continue
            comparable = bool(question["options"] and question.get("answer"))
            outcome = ("correct" if submitted[qid] == question["answer"] else "incorrect") if comparable else "unverified"
            rows.append({"id": qid, "answer": submitted[qid], "outcome": outcome})
        correct = sum(row["outcome"] == "correct" for row in rows)
        graded = sum(row["outcome"] != "unverified" for row in rows)
        unverified = len(rows) - graded
        outcome = ("unverified" if unverified else "correct" if correct == graded
                   else "incorrect" if correct == 0 else "partial")
        source = ("按题目附带参考答案比较已提交的客观题；没有可比较答案的题保持未核验。材料来源：" + lesson["source"])
        return {"questions": rows, "submitted_count": len(rows), "graded_count": graded,
                "correct_count": correct, "unverified_count": unverified, "outcome": outcome,
                "source": source, "scope": "submitted_questions_only"}

    def record_evaluated(self, lid, answers, *, tags=(), note="", minutes=0, next_review=None):
        """Explicit UI save; imported keys are the basis, never an invented diagnosis."""
        evaluation = self.evaluate(lid, answers)
        sid = self.record(lid, answers, evaluation["outcome"], tags, note, minutes,
                          evaluation["source"], next_review)
        return {"session_id": sid, "evaluation": evaluation}

    def _question(self, lid, qid):
        lesson = self.lesson(lid)
        for question in lesson["questions"]:
            if question["id"] == qid:
                return lesson, question
        raise ValueError("找不到指定题号")

    def local_hint(self, lid, qid, level=0):
        if type(level) is not int or not 0 <= level <= 5:
            raise ValueError("提示位置须在0—5之间")
        lesson, question = self._question(lid, qid)
        hints = question.get("hints", [])
        available = level < len(hints)
        hint = (hints[level] if available else "这题没有预写提示，可生成网页追问提示词。" if not hints
                else "这题的预写提示已看完，可请求本地解析或继续网页追问。")
        return {"id": qid, "hint": hint, "level": level, "total": len(hints),
                "exhausted": not available, "source": lesson["source"]}

    def local_explanation(self, lid, qid):
        lesson, question = self._question(lid, qid)
        recent = self.history(lid, 1)
        if not recent or qid not in recent[0]["answers"]:
            raise ValueError("请先保存这道题的作答，再查看本地解析")
        return {"id": qid, "stem": question["stem"], "my_answer": recent[0]["answers"][qid],
                "reference_answer": question.get("answer"), "rationale": question.get("rationale", ""),
                "source": lesson["source"], "basis": "imported_material"}

    def _record_values(self, lid, answers, outcome="unverified", tags=(), note="", minutes=0,
                       source="用户手动记录；尚未核验", next_review=None):
        """Validate before a write; handoff commits use the same contract."""
        lesson = self.lesson(lid)
        if not isinstance(answers, dict) or not answers:
            raise ValueError("请先填写至少一个作答")
        known = {q["id"]: q for q in lesson["questions"]}
        clean = {}
        for qid, value in answers.items():
            if qid not in known:
                raise ValueError(f"未知题号：{qid}")
            value = text_value(value, "作答", 5000)
            if known[qid]["options"] and value not in known[qid]["options"]:
                raise ValueError(f"题号{qid}的作答须来自已有选项")
            clean[qid] = value
        choice(outcome, "结果", {"unverified", "correct", "incorrect", "partial"})
        if not isinstance(tags, (list, tuple)) or len(tags) > 20:
            raise ValueError("薄弱点须为最多20项的列表")
        tags = [text_value(v, "薄弱点", 100) for v in tags]
        note = text_value(note, "学习笔记", 10_000, required=False)
        source = text_value(source, "结果依据", 2000)
        if type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError("学习分钟数须在0—1440之间")
        if next_review is not None:
            timestamp(next_review)
            next_review = datetime.fromtimestamp(timestamp(next_review), timezone.utc).isoformat(timespec="seconds")
        return (uid("session"), lid, json.dumps(clean, ensure_ascii=False), outcome,
                json.dumps(tags, ensure_ascii=False), note, source, minutes, now_iso(), next_review)

    def history(self, lid=None, limit=100):
        with self.store.connection() as db:
            if lid:
                rows = db.execute("SELECT * FROM sessions WHERE lesson_id=? ORDER BY rowid DESC LIMIT ?", (lid, min(limit, 200))).fetchall()
            else:
                rows = db.execute("SELECT * FROM sessions ORDER BY rowid DESC LIMIT ?", (min(limit, 200),)).fetchall()
        return [{**dict(r), "answers": json.loads(r["answers"]), "tags": json.loads(r["tags"])} for r in rows]

    def progress_summary(self):
        with self.store.connection() as db:
            meta = dict(db.execute("SELECT key,value FROM module_meta").fetchall())
            row = db.execute("""SELECT COUNT(*) AS submissions,MIN(recorded_at) AS first_submission,
                MAX(recorded_at) AS last_submission,
                COUNT(DISTINCT date(recorded_at,'localtime')) AS learning_days FROM sessions""").fetchone()
        first_day = datetime.fromisoformat(meta["first_used_at"]).astimezone().date()
        today = datetime.now().astimezone().date()
        return {"first_used_at": meta["first_used_at"], "first_submission_at": row["first_submission"],
                "last_submission_at": row["last_submission"], "submission_count": row["submissions"],
                "learning_days": row["learning_days"], "usage_span_days": max(1, (today - first_day).days + 1),
                "usage_tracking_version": meta["usage_tracking_version"]}

    def due_reviews(self, at=None):
        cutoff = at or now_iso()
        cutoff = datetime.fromtimestamp(timestamp(cutoff), timezone.utc).isoformat(timespec="seconds")
        with self.store.connection() as db:
            rows = db.execute("""SELECT l.id,l.title,s.next_review,s.outcome FROM sessions s
                JOIN lessons l ON l.id=s.lesson_id
                WHERE s.rowid=(SELECT MAX(s2.rowid) FROM sessions s2 WHERE s2.lesson_id=s.lesson_id)
                AND s.next_review IS NOT NULL AND s.next_review<=?
                ORDER BY s.next_review LIMIT 200""", (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def prompt(self, lid, mode="practice"):
        from .handoff import WebHandoff
        return WebHandoff(self).prepare_prompt(lid, mode)


KINDS = {"decision", "asset", "project_log", "preference", "experience", "current_fact"}
MEMORY_KINDS = {"preference", "experience", "current_fact"}
DECISIONS = {"candidate", "adopted", "rejected", "deferred"}
IMPLEMENTATIONS = {"not_implemented", "prototype", "test_install", "development", "release", "not_applicable"}
AUTO_CHECKS = {"untested", "passed", "failed", "not_applicable"}
MANUAL_CHECKS = {"unreviewed", "passed", "rework", "not_applicable"}


class MemoryModule:
    def __init__(self, store):
        self.store = store

    def add(self, *, kind, title, body, source, occurred_at="日期待补", decision="candidate",
            implementation="not_implemented", auto_check="untested", manual_check="unreviewed",
            evidence="", scope="", memory_confirmed=False, supersedes=None):
        choice(kind, "记录类别", KINDS)
        choice(decision, "决定状态", DECISIONS)
        choice(implementation, "实现状态", IMPLEMENTATIONS)
        choice(auto_check, "自动检查", AUTO_CHECKS)
        choice(manual_check, "人工验收", MANUAL_CHECKS)
        title = text_value(title, "标题", 300)
        body = text_value(body, "正文", 30_000)
        source = text_value(source, "来源", 2000)
        occurred_at = text_value(occurred_at, "发生日期", 100)
        evidence = text_value(evidence, "证据索引", 4000, required=False)
        scope = text_value(scope, "适用范围/版本", 500, required=False)
        if type(memory_confirmed) is not bool:
            raise ValueError("记忆确认须为布尔值")
        if memory_confirmed and (kind not in MEMORY_KINDS or decision != "adopted"):
            raise ValueError("只有已采用的偏好、经历或当前事实可确认为赫宝记忆")
        rid = uid("record")
        with self.store.connection() as db:
            if supersedes:
                old = db.execute("SELECT * FROM records WHERE id=?", (supersedes,)).fetchone()
                if old is None or not old["active"] or old["kind"] != kind:
                    raise ValueError("只能替代同类别且仍有效的记录")
                if decision != "adopted":
                    raise ValueError("新记录须已采用，才能替代旧记录")
            db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rid, kind, title, body, source, occurred_at, now_iso(), decision,
                        implementation, auto_check, manual_check, evidence, scope, int(memory_confirmed), 1, None))
            if supersedes:
                db.execute("UPDATE records SET active=0,decision='superseded',superseded_by=? WHERE id=?", (rid, supersedes))
        return rid

    def records(self, current_only=False, limit=100):
        where = "WHERE active=1" if current_only else ""
        with self.store.connection() as db:
            return [dict(r) for r in db.execute(f"SELECT * FROM records {where} ORDER BY rowid DESC LIMIT ?", (min(limit, 200),))]

    def confirmed_memories(self, scope=None, limit=100):
        condition = ""
        parameters = []
        if scope is not None:
            condition = " AND (scope='' OR scope=?)"
            parameters.append(scope)
        parameters.append(min(limit, 200))
        with self.store.connection() as db:
            rows = db.execute("""SELECT * FROM records WHERE active=1 AND memory_confirmed=1
                AND decision='adopted' AND kind IN ('preference','experience','current_fact')
                """ + condition + " ORDER BY rowid DESC LIMIT ?", parameters).fetchall()
        # A scoped query includes global records and that exact version, never all versions.
        return [dict(r) for r in rows]

    def export_markdown(self):
        rows = self.records(limit=200)
        lines = ["# 赫宝项目记录（最近200条）", "", f"导出时间：{now_iso()}", ""]
        for r in reversed(rows):
            lines += [f"## {r['title']}", "", f"ID：{r['id']}", f"类别：{r['kind']}；决定：{r['decision']}；有效：{bool(r['active'])}",
                      f"发生：{r['occurred_at']}；记录：{r['created_at']}；范围：{r['scope'] or '未限定'}",
                      f"实现：{r['implementation']}；自动检查：{r['auto_check']}；人工验收：{r['manual_check']}",
                      f"赫宝记忆已确认：{bool(r['memory_confirmed'])}", "", r["body"], "",
                      f"来源：{r['source']}", f"证据：{r['evidence'] or '待补'}",
                      f"替代记录：{r['superseded_by'] or '无'}", ""]
        return "\n".join(lines)
