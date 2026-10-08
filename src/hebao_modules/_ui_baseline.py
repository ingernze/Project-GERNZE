"""Tk UI loaded only when the host opens these tools. All calls on Tk thread."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from .core import Store, StudyModule, MemoryModule
from .reminders import ReminderController
from .security import local_path, strict_json, write_export


OUTCOMES = {"尚未核验": "unverified", "正确（我已核对）": "correct", "错误（我已核对）": "incorrect", "部分正确（我已核对）": "partial"}
AUTO_OUTCOMES = {"正确（按题目参考答案）": "correct", "错误（按题目参考答案）": "incorrect", "部分正确（按题目参考答案）": "partial"}
OUTCOMES.update(AUTO_OUTCOMES)
KINDS = {"技术决策": "decision", "素材版本": "asset", "项目日志": "project_log", "个人偏好": "preference", "共同经历": "experience", "当前事实": "current_fact"}
DECISIONS = {"候选": "candidate", "已采用": "adopted", "已否决": "rejected", "暂缓": "deferred"}
IMPLEMENTATIONS = {"未实现": "not_implemented", "独立原型": "prototype", "独立试装": "test_install", "开发版": "development", "正式版": "release", "不适用": "not_applicable"}
AUTO = {"未测": "untested", "通过": "passed", "失败": "failed", "不适用": "not_applicable"}
MANUAL = {"未验收": "unreviewed", "通过": "passed", "需返工": "rework", "不适用": "not_applicable"}


class ToolWindow:
    def __init__(self, controller):
        self.controller = controller
        self.study, self.memory = controller.study, controller.memory
        self.window = tk.Toplevel(controller.root)
        self.window.title("赫宝 · 学习与项目记录")
        self.window.geometry("1040x820")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.lesson_id = None
        self.lesson_map = {}
        self.answer_vars = {}
        self.hint_levels = {}
        self.record_ids = []
        self.reminder_ids = []
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="慢慢来。今天先处理一小件事就好。", font=("Microsoft YaHei UI", 12)).pack(anchor="w")
        ttk.Label(outer, text="本地记录 · 提示词手动复制到网页 GPT · 学习结果由你核对后保存").pack(anchor="w", pady=(4, 10))
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.study_tab = ttk.Frame(notebook, padding=10)
        self.memory_tab = ttk.Frame(notebook, padding=10)
        self.reminder_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.study_tab, text="六级阅读")
        notebook.add(self.memory_tab, text="项目记录与记忆")
        notebook.add(self.reminder_tab, text="提醒与备份")
        self._build_study()
        self._build_memory()
        self._build_reminders()
        self.refresh_lessons()
        self.refresh_records()
        self.refresh_reminders()

    def guard(self, function):
        def wrapped():
            try:
                function()
            except (ValueError, OSError, json.JSONDecodeError) as error:
                messagebox.showerror("还需要补一处", str(error), parent=self.window)
            except Exception as error:
                messagebox.showerror("操作未完成", str(error), parent=self.window)
        return wrapped

    def button(self, parent, title, function):
        b = ttk.Button(parent, text=title, command=self.guard(function))
        b.pack(side="left", padx=(0, 6), pady=3)
        return b

    def combo(self, parent, label, values, initial):
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, 10))
        ttk.Label(frame, text=label).pack(anchor="w")
        var = tk.StringVar(value=initial)
        ttk.Combobox(frame, textvariable=var, values=list(values), state="readonly", width=16).pack()
        return var

    def dialog_text(self, title, text, editable=False, save_callback=None):
        dialog = tk.Toplevel(self.window)
        dialog.title(title)
        dialog.geometry("800x600")
        widget = ScrolledText(dialog, wrap="word", padx=10, pady=10)
        widget.pack(fill="both", expand=True)
        widget.insert("1.0", text)
        if not editable:
            widget.configure(state="disabled")
        buttons = ttk.Frame(dialog, padding=8)
        buttons.pack(fill="x")
        def copy():
            self.window.clipboard_clear()
            self.window.clipboard_append(widget.get("1.0", "end-1c"))
            ttk.Label(buttons, text="已复制，可手动粘贴").pack(side="left")
        self.button(buttons, "复制全文", copy)
        if save_callback:
            def save():
                save_callback(widget.get("1.0", "end-1c"))
                dialog.destroy()
            self.button(buttons, "保存", save)
        self.button(buttons, "关闭", dialog.destroy)
        return dialog

    def _build_study(self):
        row = ttk.Frame(self.study_tab)
        row.pack(fill="x")
        self.button(row, "导入阅读 JSON", self.import_lesson)
        self.button(row, "粘贴现有题目", self.paste_lesson)
        self.button(row, "载入示例（非真题）", self.load_sample)
        self.button(row, "粘贴网页学习结果", self.import_web_result)
        self.button(row, "学习记录 / 到期复习", self.show_history)
        progress_row = ttk.Frame(self.study_tab)
        progress_row.pack(fill="x", pady=4)
        self.progress_text = tk.StringVar()
        ttk.Label(progress_row, textvariable=self.progress_text, wraplength=850).pack(side="left", anchor="w")
        self.button(progress_row, "刷新进度", self.refresh_progress)
        self.lesson_choice = tk.StringVar()
        self.selector = ttk.Combobox(self.study_tab, textvariable=self.lesson_choice, state="readonly")
        self.selector.pack(fill="x", pady=6)
        self.selector.bind("<<ComboboxSelected>>", lambda _: self.select_lesson())
        self.passage = ScrolledText(self.study_tab, height=13, wrap="word")
        self.passage.pack(fill="both", expand=True)
        self.passage.configure(state="disabled")
        self.answers_frame = ttk.LabelFrame(self.study_tab, text="你的作答（先记录，再生成追问）", padding=6)
        self.answers_frame.pack(fill="x", pady=6)
        local_row = ttk.Frame(self.study_tab)
        local_row.pack(fill="x", pady=(0, 4))
        self.button(local_row, "按题目答案判题并保存", self.grade_study)
        ttk.Label(local_row, text="提示／解析题号：").pack(side="left")
        self.local_question = tk.StringVar()
        self.local_selector = ttk.Combobox(local_row, textvariable=self.local_question, state="readonly", width=6)
        self.local_selector.pack(side="left", padx=4)
        self.button(local_row, "下一条本地提示", self.show_local_hint)
        self.button(local_row, "本地答案解析", self.show_local_explanation)
        row = ttk.Frame(self.study_tab)
        row.pack(fill="x")
        self.outcome = self.combo(row, "本次结果", OUTCOMES, "尚未核验")
        self.minutes = tk.StringVar(value="0")
        minutes_box = ttk.Frame(row)
        minutes_box.pack(side="left", padx=8)
        ttk.Label(minutes_box, text="学习分钟数（手填）").pack(anchor="w")
        ttk.Entry(minutes_box, textvariable=self.minutes, width=10).pack()
        self.review_time = tk.StringVar()
        date_box = ttk.Frame(row)
        date_box.pack(side="left", padx=8)
        ttk.Label(date_box, text="下次复习（本地时间，可留空）").pack(anchor="w")
        ttk.Entry(date_box, textvariable=self.review_time, width=23).pack()
        ttk.Label(self.study_tab, text="复习时间格式：2026-10-02 20:00；只登记日期，主动提醒需在“提醒”页单独开启。").pack(anchor="w", pady=3)
        self.tags = tk.StringVar()
        self.result_source = tk.StringVar(value="用户手动记录；尚未核验")
        for label, var in (("具体薄弱点（用中文逗号分隔）", self.tags), ("核对依据 / 网页学习记录来源", self.result_source)):
            ttk.Label(self.study_tab, text=label).pack(anchor="w")
            ttk.Entry(self.study_tab, textvariable=var).pack(fill="x", pady=(0, 4))
        ttk.Label(self.study_tab, text="学习笔记 / 网页 GPT 回填摘要（请先核对）").pack(anchor="w")
        self.notes = ScrolledText(self.study_tab, height=3, wrap="word")
        self.notes.pack(fill="x")
        row = ttk.Frame(self.study_tab)
        row.pack(fill="x", pady=6)
        self.button(row, "保存本次作答与结果", self.save_study)
        for title, mode in (("做题提示词", "practice"), ("追问提示词", "diagnose"), ("讲解提示词", "explain"), ("复习提示词", "review")):
            self.button(row, title, lambda m=mode: self.show_prompt(m))

    def refresh_lessons(self):
        self.refresh_progress()
        self.lesson_map = {f"{r['title']} [{r['id'][-6:]}]": r["id"] for r in self.controller.invoke("study.lessons")}
        self.selector["values"] = list(self.lesson_map)
        if self.lesson_id:
            for label, lid in self.lesson_map.items():
                if lid == self.lesson_id:
                    self.lesson_choice.set(label)
                    self.select_lesson()
                    return
        if self.lesson_map:
            self.lesson_choice.set(next(iter(self.lesson_map)))
            self.select_lesson()

    def select_lesson(self):
        self.lesson_id = self.lesson_map.get(self.lesson_choice.get())
        if not self.lesson_id:
            return
        lesson = self.controller.invoke("study.lesson", lid=self.lesson_id)
        qids = [question["id"] for question in lesson["questions"]]
        self.local_selector["values"] = qids
        self.local_question.set(qids[0])
        self.hint_levels.clear()
        display = lesson["passage"] + "\n\n" + "\n\n".join(
            q["id"] + ". " + q["stem"] + "\n" + "\n".join(f"{k}. {v}" for k, v in q["options"].items())
            for q in lesson["questions"])
        self.passage.configure(state="normal")
        self.passage.delete("1.0", "end")
        self.passage.insert("1.0", display)
        self.passage.configure(state="disabled")
        for child in self.answers_frame.winfo_children():
            child.destroy()
        self.answer_vars.clear()
        for i, q in enumerate(lesson["questions"]):
            frame = ttk.Frame(self.answers_frame)
            frame.grid(row=i // 5, column=i % 5, padx=6, pady=4, sticky="w")
            ttk.Label(frame, text=q["id"] + "题").pack(side="left")
            var = tk.StringVar()
            self.answer_vars[q["id"]] = var
            if q["options"]:
                ttk.Combobox(frame, textvariable=var, values=[""] + list(q["options"]), state="readonly", width=8).pack(side="left")
            else:
                ttk.Entry(frame, textvariable=var, width=30).pack(side="left")
        # Never carry another lesson's outcome/notes into this lesson.
        self.outcome.set("尚未核验")
        self.minutes.set("0")
        self.tags.set("")
        self.review_time.set("")
        self.result_source.set("用户手动记录；尚未核验")
        self.notes.delete("1.0", "end")

    def require_lesson(self):
        if self.lesson_id is None:
            raise ValueError("先导入或选择一份阅读材料")

    def import_lesson(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[("阅读JSON", "*.json")])
        if path:
            path = local_path(path)
            if path.stat().st_size > 500_000:
                raise ValueError("导入文件不能超过500KB")
            with path.open("r", encoding="utf-8-sig") as stream:
                payload = strict_json(stream.read(500_001), max_bytes=500_000)
            self.lesson_id = self.controller.invoke("study.import_lesson", payload=payload)
            self.refresh_lessons()

    def paste_lesson(self):
        def save(text):
            self.lesson_id = self.controller.invoke("study.import_lesson", payload={"title": "粘贴材料 " + datetime.now().strftime("%m-%d %H:%M"),
                "passage": text, "source": "用户手动粘贴；未附核验过的参考答案", "questions": [
                    {"id": "1", "stem": "按上方粘贴材料中的题号作答。在记录栏填写例如：1B、2A及你的疑问。", "options": {}}]})
            self.refresh_lessons()
        self.dialog_text("粘贴原文与题目（原样保存）", "", editable=True, save_callback=save)

    def load_sample(self):
        from .sample import SAMPLE
        self.lesson_id = self.controller.invoke("study.import_lesson", payload=SAMPLE)
        self.refresh_lessons()

    def study_input(self):
        self.require_lesson()
        answers = {qid: var.get() for qid, var in self.answer_vars.items() if var.get().strip()}
        date = local_date(self.review_time.get()) if self.review_time.get().strip() else None
        return {"lid": self.lesson_id, "answers": answers,
            "tags": [v.strip() for v in self.tags.get().replace(",", "，").split("，") if v.strip()],
            "note": self.notes.get("1.0", "end-1c"), "minutes": int(self.minutes.get()),
            "next_review": date}

    def save_study(self):
        payload = self.study_input()
        payload.update(outcome=OUTCOMES[self.outcome.get()], source=self.result_source.get())
        self.controller.invoke("study.record", payload=payload)
        self.refresh_progress()
        messagebox.showinfo("已记下", "这次作答已经保存。学习成绩不会影响赫宝与你的关系。", parent=self.window)

    def grade_study(self):
        saved = self.controller.invoke("study.record_evaluated", payload=self.study_input())
        result = saved["evaluation"]
        label = next((key for key, value in AUTO_OUTCOMES.items() if value == result["outcome"]), "尚未核验")
        self.outcome.set(label)
        self.result_source.set(result["source"])
        self.refresh_progress()
        labels = {"correct": "正确", "incorrect": "错误", "unverified": "未核验"}
        rows = [f"第{row['id']}题：{labels[row['outcome']]}" for row in result["questions"]]
        detail = (f"已保存本次{result['submitted_count']}题作答；其中{result['graded_count']}题有可比较参考答案。\n"
                  + "\n".join(rows) + "\n\n只核对已提交题目，依据来自导入材料。薄弱点请根据实际卡点填写；需要时可查看指定题目的提示或解析。学习成绩不影响人物关系。")
        messagebox.showinfo("判题并记下", detail, parent=self.window)

    def show_local_hint(self):
        self.require_lesson()
        qid = self.local_question.get()
        level = self.hint_levels.get(qid, 0)
        hint = self.controller.invoke("study.local_hint", lid=self.lesson_id, qid=qid, level=level)
        if not hint["exhausted"]:
            self.hint_levels[qid] = level + 1
        self.dialog_text(f"第{qid}题 · 一条本地提示", hint["hint"] + "\n\n提示来源：" + hint["source"])

    def show_local_explanation(self):
        self.require_lesson()
        value = self.controller.invoke("study.local_explanation", lid=self.lesson_id, qid=self.local_question.get())
        answer = value["reference_answer"] or "未附参考答案，保持未核验"
        rationale = value["rationale"] or "材料未附解析，可以生成网页讲解提示词。"
        detail = (f"题目：{value['stem']}\n你的已保存作答：{value['my_answer']}\n"
                  f"材料附带答案：{answer}\n\n{rationale}\n\n来源：{value['source']}")
        self.dialog_text(f"第{value['id']}题 · 本地解析", detail)

    def show_prompt(self, mode):
        self.require_lesson()
        # Explicitly previews text; it never watches or writes a web chat.
        self.dialog_text("网页 GPT 提示词 · 请先预览再复制", self.controller.invoke("study.prompt", lid=self.lesson_id, mode=mode))

    def show_history(self):
        self.refresh_progress()
        data = {"日期与提交次数": self.controller.invoke("study.progress_summary"), "到期复习（以每份材料最新记录为准）": self.controller.invoke("study.due_reviews"), "最近100条学习记录": self.controller.invoke("study.history")}
        self.dialog_text("学习进度", json.dumps(data, ensure_ascii=False, indent=2))

    def refresh_progress(self):
        data = self.controller.invoke("study.progress_summary")
        def date(value):
            return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M") if value else "尚未提交"
        self.progress_text.set(
            f"首次使用记录：{date(data['first_used_at'])} · 最近提交：{date(data['last_submission_at'])}\n"
            f"累计提交：{data['submission_count']}次 · 有提交的学习日：{data['learning_days']}天 · 使用跨度：{data['usage_span_days']}天（含首日）")

    def import_web_result(self):
        self.require_lesson()
        lid = self.lesson_id
        lesson = self.controller.invoke("study.lesson", lid=lid)
        dialog = tk.Toplevel(self.window)
        dialog.title("网页学习结果 · 读取草稿后确认保存")
        dialog.geometry("980x850")
        outer = ttk.Frame(dialog, padding=10)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="回填材料：" + lesson["title"]).pack(anchor="w")
        ttk.Label(outer, text="复制学习结束时的JSON回填块粘贴到这里。读取只生成草稿，确认后才写入进度。").pack(anchor="w", pady=4)
        raw = ScrolledText(outer, height=6, wrap="word")
        raw.pack(fill="x")
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=5)
        scrolling = ttk.Frame(outer)
        scrolling.pack(fill="both", expand=True)
        canvas = tk.Canvas(scrolling, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scrolling, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        form = ttk.Frame(canvas)
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(form_window, width=event.width))
        def paste():
            raw.delete("1.0", "end")
            raw.insert("1.0", dialog.clipboard_get())
        self.button(actions, "从剪贴板粘贴", paste)
        def load():
            draft = self.controller.invoke("study.parse_web_result", lid=lid, text=raw.get("1.0", "end-1c"))
            result = draft["result"]
            for child in form.winfo_children():
                child.destroy()
            ttk.Label(form, text="\n".join(draft["warnings"]), wraplength=930).pack(anchor="w", pady=4)
            ttk.Label(form, text="交接编号：" + result["handoff_id"]).pack(anchor="w")
            answers = {}
            answer_row = ttk.LabelFrame(form, text="本次作答（可修正）", padding=5)
            answer_row.pack(fill="x", pady=4)
            for i, q in enumerate(lesson["questions"]):
                frame = ttk.Frame(answer_row)
                frame.grid(row=i // 5, column=i % 5, padx=4, pady=3, sticky="w")
                ttk.Label(frame, text=q["id"] + "题").pack(side="left")
                var = tk.StringVar(value=result["answers"].get(q["id"], ""))
                answers[q["id"]] = var
                if q["options"]:
                    ttk.Combobox(frame, textvariable=var, values=[""] + list(q["options"]), width=8, state="readonly").pack(side="left")
                else:
                    ttk.Entry(frame, textvariable=var, width=30).pack(side="left")
            row = ttk.Frame(form)
            row.pack(fill="x", pady=4)
            assessment_labels = {"尚未判断": "unverified", "网页认为正确": "correct", "网页认为错误": "incorrect", "网页认为部分正确": "partial"}
            basis_labels = {"网页自报对照参考材料": "reference_material", "网页自报从原文推断": "passage_inference", "网页尚未核对": "not_checked"}
            assessment = self.combo(row, "网页判断建议", assessment_labels, next(k for k, v in assessment_labels.items() if v == result["assessment"]))
            basis = self.combo(row, "网页自报依据", basis_labels, next(k for k, v in basis_labels.items() if v == result["basis"]))
            tags = tk.StringVar(value="，".join(result["weak_points"]))
            evidence = tk.StringVar(value=result["evidence"])
            focus = tk.StringVar(value=result["review_focus"])
            for label, var in (("具体薄弱点（中文逗号分隔，可删改）", tags), ("判断依据（可修正）", evidence), ("下次复习方向", focus)):
                ttk.Label(form, text=label).pack(anchor="w")
                ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))
            ttk.Label(form, text="学习摘要（可修正）").pack(anchor="w")
            summary = ScrolledText(form, height=3, wrap="word")
            summary.pack(fill="x")
            summary.insert("1.0", result["summary"])
            row = ttk.Frame(form)
            row.pack(fill="x", pady=5)
            minutes = tk.StringVar(value="0")
            review = tk.StringVar()
            ttk.Label(row, text="学习分钟数（手填）：").pack(side="left")
            ttk.Entry(row, textvariable=minutes, width=7).pack(side="left", padx=4)
            ttk.Label(row, text="复习时间：").pack(side="left")
            ttk.Entry(row, textvariable=review, width=22).pack(side="left", padx=4)
            self.button(row, "选明天此时", lambda: review.set((datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")))
            ttk.Label(form, text="复习格式：2026-10-02 20:00；留空可只保存学习记录。").pack(anchor="w")
            verified = tk.BooleanVar(value=False)
            remind = tk.BooleanVar(value=False)
            ttk.Checkbutton(form, text="我已核对判断；保存为已核对结果（默认保持未核验）", variable=verified).pack(anchor="w")
            ttk.Checkbutton(form, text="同时创建并开启单次复习提醒（需选择时间；仅程序运行期间）", variable=remind).pack(anchor="w")
            buttons = ttk.Frame(form)
            buttons.pack(fill="x", pady=6)
            def save():
                edited = {**result, "answers": {k: v.get() for k, v in answers.items() if v.get().strip()},
                    "assessment": assessment_labels[assessment.get()], "basis": basis_labels[basis.get()],
                    "weak_points": [v.strip() for v in tags.get().replace(",", "，").split("，") if v.strip()],
                    "summary": summary.get("1.0", "end-1c"), "evidence": evidence.get(), "review_focus": focus.get()}
                args = {"result": edited, "minutes": int(minutes.get()), "verified": verified.get(), "create_reminder": remind.get()}
                if review.get().strip():
                    args["review_at"] = local_date(review.get())
                saved = self.controller.invoke("study.commit_web_result", **args)
                self.refresh_progress()
                self.refresh_reminders()
                messagebox.showinfo("已记下", "这次交接已保存过，没有重复记账。" if saved["already_saved"] else "本次学习结果已保存。", parent=dialog)
                dialog.destroy()
            self.button(buttons, "确认保存", save)
            self.button(buttons, "取消", dialog.destroy)
        self.button(actions, "读取为可修改草稿", load)

    def _build_memory(self):
        ttk.Label(self.memory_tab, text="候选不会自动成为事实。决定、实现、自动检查、人工验收分别记录。").pack(anchor="w")
        row = ttk.Frame(self.memory_tab)
        row.pack(fill="x", pady=4)
        self.kind = self.combo(row, "类别", KINDS, "项目日志")
        self.decision = self.combo(row, "决定", DECISIONS, "候选")
        self.implementation = self.combo(row, "实现范围", IMPLEMENTATIONS, "未实现")
        self.auto_check = self.combo(row, "自动检查", AUTO, "未测")
        self.manual_check = self.combo(row, "人工验收", MANUAL, "未验收")
        self.record_title = tk.StringVar()
        self.record_source = tk.StringVar()
        self.occurred_at = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.scope = tk.StringVar()
        self.evidence = tk.StringVar()
        self.supersedes = tk.StringVar()
        for label, var in (("标题", self.record_title), ("来源（必填：用户确认 / 文件 / 聊天依据）", self.record_source),
                           ("发生日期（不确定就写日期待补）", self.occurred_at), ("适用范围 / 版本", self.scope),
                           ("证据文件 / 验证范围", self.evidence), ("替代旧记录 ID（可留空，旧记录保留历史）", self.supersedes)):
            ttk.Label(self.memory_tab, text=label).pack(anchor="w")
            ttk.Entry(self.memory_tab, textvariable=var).pack(fill="x", pady=(0, 3))
        ttk.Label(self.memory_tab, text="正文").pack(anchor="w")
        self.record_body = ScrolledText(self.memory_tab, height=5, wrap="word")
        self.record_body.pack(fill="x")
        self.memory_confirmed = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.memory_tab, text="我已确认：可作为赫宝的长期记忆（仅限已采用的偏好、经历或当前事实）", variable=self.memory_confirmed).pack(anchor="w", pady=4)
        row = ttk.Frame(self.memory_tab)
        row.pack(fill="x")
        self.button(row, "保存记录", self.save_record)
        self.button(row, "查看已确认记忆", self.show_memories)
        self.button(row, "导出 Markdown", self.export_markdown)
        self.records_list = tk.Listbox(self.memory_tab, height=7)
        self.records_list.pack(fill="both", expand=True, pady=6)
        self.records_list.bind("<Double-Button-1>", lambda _: self.view_record())
        ttk.Label(self.memory_tab, text="双击查看记录；替代时复制记录 ID 到上方，新条目须为“已采用”。").pack(anchor="w")

    def save_record(self):
        self.controller.invoke("memory.add", payload={"kind": KINDS[self.kind.get()], "title": self.record_title.get(), "body": self.record_body.get("1.0", "end-1c"),
            "source": self.record_source.get(), "occurred_at": self.occurred_at.get(), "decision": DECISIONS[self.decision.get()],
            "implementation": IMPLEMENTATIONS[self.implementation.get()], "auto_check": AUTO[self.auto_check.get()],
            "manual_check": MANUAL[self.manual_check.get()], "evidence": self.evidence.get(), "scope": self.scope.get(),
            "memory_confirmed": self.memory_confirmed.get(), "supersedes": self.supersedes.get().strip() or None})
        self.refresh_records()
        self.record_title.set("")
        self.record_body.delete("1.0", "end")
        self.supersedes.set("")
        self.memory_confirmed.set(False)

    def refresh_records(self):
        self.record_ids = self.controller.invoke("memory.records")
        self.records_list.delete(0, "end")
        for r in self.record_ids:
            self.records_list.insert("end", f"[{r['decision']}] {r['title']} · {r['implementation']} · {'当前' if r['active'] else '历史'}")

    def view_record(self):
        indices = self.records_list.curselection()
        if indices:
            self.dialog_text("项目记录", json.dumps(self.record_ids[indices[0]], ensure_ascii=False, indent=2))

    def show_memories(self):
        self.dialog_text("已确认的当前记忆", json.dumps(self.controller.invoke("memory.confirmed"), ensure_ascii=False, indent=2))

    def export_markdown(self):
        path = filedialog.asksaveasfilename(parent=self.window, title="导出项目记录（请选择新文件）", initialfile=datetime.now().strftime("Hecate_records_%Y%m%d_%H%M%S.md"), defaultextension=".md", filetypes=[("Markdown", "*.md")])
        if path:
            write_export(path, self.controller.invoke("memory.markdown"), suffix=".md", protected_paths=(self.controller.store.path,))

    def _build_reminders(self):
        ttk.Label(self.reminder_tab, text="提醒默认关闭。启用后只等待最近的一次到期时间；不每秒检查。").pack(anchor="w", pady=4)
        self.enabled_var = tk.BooleanVar(value=self.controller.reminders.enabled)
        self.quiet_var = tk.BooleanVar(value=self.controller.reminders.quiet)
        ttk.Checkbutton(self.reminder_tab, text="启用提醒（仅当前程序运行期间）", variable=self.enabled_var,
                        command=lambda: self.controller.set_reminders_enabled(self.enabled_var.get())).pack(anchor="w")
        ttk.Checkbutton(self.reminder_tab, text="安静模式（如游戏时；到期提醒暂存，解除后集中显示）", variable=self.quiet_var,
                        command=lambda: self.controller.set_quiet_mode(self.quiet_var.get())).pack(anchor="w")
        self.reminder_title = tk.StringVar(value="要不要把上次那道阅读再看一小段？")
        self.reminder_time = tk.StringVar(value=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"))
        ttk.Label(self.reminder_tab, text="提醒内容").pack(anchor="w", pady=(10, 0))
        ttk.Entry(self.reminder_tab, textvariable=self.reminder_title).pack(fill="x")
        ttk.Label(self.reminder_tab, text="本地时间，格式：2026-10-02 20:00").pack(anchor="w", pady=(6, 0))
        ttk.Entry(self.reminder_tab, textvariable=self.reminder_time).pack(fill="x")
        row = ttk.Frame(self.reminder_tab)
        row.pack(fill="x", pady=6)
        self.button(row, "保存单次提醒", self.add_reminder)
        self.button(row, "取消选中提醒", self.cancel_reminder)
        self.button(row, "刷新 / 恢复后核对时间", self.refresh_reminders)
        self.reminder_list = tk.Listbox(self.reminder_tab, height=12)
        self.reminder_list.pack(fill="both", expand=True)
        row = ttk.Frame(self.reminder_tab)
        row.pack(fill="x", pady=8)
        self.button(row, "导出全部数据 JSON", self.export_json)
        self.button(row, "备份数据库", self.backup)
        ttk.Label(self.reminder_tab, text="备份恢复：先退出桌宠，保留旧数据库副本，再将备份放回指定数据位置。\n关闭学习窗口会释放控件；如仍启用提醒，保留一个到期计时器。关闭提醒或退出程序会取消它。").pack(anchor="w")

    def add_reminder(self):
        self.controller.invoke("reminder.add", title=self.reminder_title.get(), due=local_date(self.reminder_time.get()))
        self.refresh_reminders()

    def cancel_reminder(self):
        indices = self.reminder_list.curselection()
        if indices:
            self.controller.invoke("reminder.cancel", rid=self.reminder_ids[indices[0]]["id"])
            self.refresh_reminders()

    def refresh_reminders(self):
        self.controller.reminders.refresh()
        self.reminder_ids = self.controller.invoke("reminder.list")
        self.reminder_list.delete(0, "end")
        for r in self.reminder_ids:
            date = datetime.fromtimestamp(r["due_epoch"]).strftime("%Y-%m-%d %H:%M")
            self.reminder_list.insert("end", f"[{r['status']}] {date} · {r['title']}")

    def export_json(self):
        path = filedialog.asksaveasfilename(parent=self.window, title="导出数据（请选择新文件）", initialfile=datetime.now().strftime("Hecate_data_%Y%m%d_%H%M%S.json"), defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            write_export(path, self.controller.invoke("data.export_json"), suffix=".json", protected_paths=(self.controller.store.path,))

    def backup(self):
        path = filedialog.asksaveasfilename(parent=self.window, title="备份数据库（请选择新文件）", initialfile=datetime.now().strftime("Hecate_backup_%Y%m%d_%H%M%S.sqlite3"), defaultextension=".sqlite3", filetypes=[("SQLite备份", "*.sqlite3")])
        if path:
            self.controller.store.backup(path)

    def close(self):
        self.window.destroy()
        self.controller.window = None


def local_date(text):
    # This prototype accepts the operating system's local timezone.
    return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").astimezone().isoformat(timespec="seconds")


class ModuleController:
    """Thin integration seam. Do not create a second Tk root in the host."""
    def __init__(self, root, data_dir, notify=None):
        self.root = root
        self.store = Store(Path(data_dir) / "hebao_modules.sqlite3")
        self.study = StudyModule(self.store)
        self.memory = MemoryModule(self.store)
        from .registry import ToolRegistry
        from .capabilities import register_modules
        self.tools = ToolRegistry()
        register_modules(self.tools, self.study, self.memory)
        self.window = None
        self.closed = False
        self.reminders = ReminderController(self.store, root.after, root.after_cancel, notify or self._notify)

    def invoke(self, name, **arguments):
        result = self.tools.call(name, arguments)
        if not result["ok"]:
            raise ValueError(result["error"]["message"])
        data = result["data"]
        if name == "study.commit_web_result" and arguments.get("create_reminder") and data["reminder_id"]:
            # The UI label explicitly requests creation AND enabling.
            self.set_reminders_enabled(True)
        elif name in {"reminder.add", "reminder.cancel"}:
            self.reminders.refresh()
        return data

    def _notify(self, rows):
        text = "\n".join(r["title"] for r in rows[:10])
        if len(rows) > 10:
            text += f"\n\n共{len(rows)}条到期提醒，已集中通知；明细保留在提醒记录及数据导出中。"
        messagebox.showinfo("赫宝 · 提醒", text, parent=self.root)

    def open(self):
        if self.closed:
            raise RuntimeError("模块已退出，请重新创建控制器")
        if self.window is None:
            self.window = ToolWindow(self)
        else:
            self.window.window.deiconify()
            self.window.window.lift()
        self.reminders.refresh()

    def set_quiet_mode(self, quiet):
        self.reminders.set_quiet(quiet)
        if self.window:
            self.window.quiet_var.set(bool(quiet))

    def set_reminders_enabled(self, enabled):
        self.reminders.set_enabled(enabled)
        if self.window:
            self.window.enabled_var.set(bool(enabled))

    def on_resume_or_clock_change(self):
        self.reminders.refresh()

    def hide_tools(self):
        if self.window:
            self.window.close()

    def shutdown(self):
        self.reminders.close()
        self.hide_tools()
        self.tools.close()
        self.closed = True
