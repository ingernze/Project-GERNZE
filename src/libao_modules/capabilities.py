"""Register local capabilities. These functions know nothing about Tk widgets."""
from .handoff import WebHandoff
from .registry import Tool, parameters


STRING = {"type": "string"}
OBJECT = {"type": "object"}
ARRAY = {"type": "array", "items": OBJECT}
BOOLEAN = {"type": "boolean"}
MODE = {"type": "string", "enum": ["practice", "diagnose", "explain", "review"]}


def register_modules(registry, study, memory, owner="hebao.modules"):
    handoff = WebHandoff(study)
    def register(name, description, props, required, output, fn):
        registry.register(Tool(name, description, parameters(props, required), output, fn), owner)
    register("study.import_lesson", "导入一份阅读材料，不表示已经学习", {"payload": OBJECT}, ["payload"], STRING,
             lambda args: study.import_lesson(args["payload"]))
    register("study.lessons", "读取最近阅读材料列表", {}, [], ARRAY, lambda args: study.lessons())
    register("study.lesson", "读取一份材料", {"lid": STRING}, ["lid"], OBJECT, lambda args: study.lesson(args["lid"]))
    register("study.record", "明确保存一次手动填写的学习记录", {"payload": OBJECT}, ["payload"], STRING,
             lambda args: study.record(**args["payload"]))
    register("study.evaluate", "只依据导入答案比较已提交客观题，不写入进度", {"lid": STRING, "answers": OBJECT}, ["lid", "answers"], OBJECT,
             lambda args: study.evaluate(**args))
    register("study.record_evaluated", "用户点击后按题目答案判题并保存，不推断薄弱点", {"payload": OBJECT}, ["payload"], OBJECT,
             lambda args: study.record_evaluated(**args["payload"]))
    register("study.local_hint", "只读取指定题目的一条预写提示", {"lid": STRING, "qid": STRING, "level": {"type": "integer"}}, ["lid", "qid"], OBJECT,
             lambda args: study.local_hint(**args))
    register("study.local_explanation", "已保存作答后按请求查看该题导入的答案解析", {"lid": STRING, "qid": STRING}, ["lid", "qid"], OBJECT,
             lambda args: study.local_explanation(**args))
    register("study.prompt", "生成供手动复制到网页的提示词及回填约定", {"lid": STRING, "mode": MODE}, ["lid"], STRING,
             lambda args: study.prompt(args["lid"], args.get("mode", "practice")))
    register("study.parse_web_result", "读取回填草稿；不保存进度或创建提醒", {"lid": STRING, "text": STRING}, ["lid", "text"], OBJECT,
             lambda args: handoff.parse(args["lid"], args["text"]))
    register("study.commit_web_result", "用户确认后保存草稿，可同时创建一条复习提醒",
             {"result": OBJECT, "minutes": {"type": "integer"}, "verified": BOOLEAN,
              "review_at": {"type": "string"}, "create_reminder": BOOLEAN}, ["result"], OBJECT,
             lambda args: handoff.commit(**args))
    register("study.history", "读取最近学习记录", {"lid": STRING}, [], ARRAY,
             lambda args: study.history(args.get("lid")))
    register("study.due_reviews", "按最新记录读取到期复习", {}, [], ARRAY, lambda args: study.due_reviews())
    register("study.progress_summary", "读取首次使用、最近提交、次数和实际学习日数", {}, [], OBJECT, lambda args: study.progress_summary())
    register("memory.add", "保存带来源的项目记录；确认记忆须显式指定", {"payload": OBJECT}, ["payload"], STRING,
             lambda args: memory.add(**args["payload"]))
    register("memory.records", "读取项目记录，保留替代历史", {"current_only": BOOLEAN}, [], ARRAY,
             lambda args: memory.records(args.get("current_only", False)))
    register("memory.confirmed", "只读取当前已确认记忆，可指定适用版本", {"scope": STRING}, [], ARRAY,
             lambda args: memory.confirmed_memories(args.get("scope")))
    register("memory.markdown", "按用户请求导出项目记录文字", {}, [], STRING, lambda args: memory.export_markdown())
    register("reminder.add", "保存一条单次提醒；启用由主程序明确处理", {"title": STRING, "due": STRING}, ["title", "due"], STRING,
             lambda args: study.store.add_reminder(**args))
    register("reminder.cancel", "取消指定提醒", {"rid": STRING}, ["rid"], BOOLEAN,
             lambda args: _cancel(study.store, args["rid"]))
    register("reminder.list", "按用户请求读取提醒记录", {}, [], ARRAY, lambda args: study.store.reminders())
    register("data.export_json", "按用户请求导出本地数据", {}, [], STRING, lambda args: study.store.export_json())


def _cancel(store, rid):
    store.cancel_reminder(rid)
    return True
