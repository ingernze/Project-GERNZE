"""A / 星夜书房 tools skin. The original business methods stay in _ui_baseline."""
from datetime import datetime, timedelta
import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ._ui_baseline import (ToolWindow as OriginalToolWindow,
                          ModuleController as OriginalController,
                          OUTCOMES, AUTO_OUTCOMES, KINDS, DECISIONS,
                          IMPLEMENTATIONS, AUTO, MANUAL, local_date)
from hecate_ui import (BG, PANEL, RAISED, INK, MUTED, GOLD, BORDER, ERROR, GOOD,
                       PREFIX, Button, Switch, ScrollFrame, ActionBar,
                       configure_window, header, panel, label, font,
                       install_styles, skin_tree, skin_widget)


class ToolWindow(OriginalToolWindow):
    def __init__(self, controller):
        self.controller = controller
        self.study, self.memory = controller.study, controller.memory
        self.window = tk.Toplevel(controller.root)
        configure_window(self.window, '赫宝 · 提醒与资料工具', 1040, 820, (740, 520))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.lesson_id, self.lesson_map = None, {}
        self.answer_vars, self.hint_levels = {}, {}
        self.record_ids, self.reminder_ids = [], []
        self._study_buttons = []
        self._active_dialog = None
        self.feedback = tk.StringVar(self.window, '本地记录 · 所有保存由你确认')
        header(self.window, '提醒与资料工具', '慢慢来。今天先处理一小件事就好。')
        self.notebook = ttk.Notebook(self.window, style=PREFIX+'TNotebook')
        self.notebook.pack(fill='both', expand=True, padx=20, pady=(0, 9))
        self.pages = []
        for title in ('六级阅读', '项目记录与记忆', '提醒与备份'):
            page = ScrollFrame(self.notebook)
            self.pages.append(page)
            self.notebook.add(page, text=title)
        self.study_tab, self.memory_tab, self.reminder_tab = [p.body for p in self.pages]
        for frame in (self.study_tab, self.memory_tab, self.reminder_tab):
            frame.configure(padx=2, pady=6)
        self._build_study()
        self._build_memory()
        self._build_reminders()
        label(self.window, '', 12, MUTED, textvariable=self.feedback, wraplength=980).pack(fill='x', padx=22, pady=(0, 12))
        self.refresh_lessons()
        self.refresh_records()
        self.refresh_reminders()
        self.window.bind('<Configure>', self._wrap, add='+')

    def _wrap(self, event):
        if event.widget == self.window:
            self._layout_answers(max(600, event.width-90))

    def guard(self, function):
        def wrapped():
            try:
                value = function()
                return value
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self._error_feedback('还需要补一处：'+str(error))
            except Exception as error:
                self._error_feedback('操作未完成：'+str(error))
        return wrapped

    def _error_feedback(self, message):
        self.feedback.set(message)
        dialog = self._active_dialog
        if dialog is not None and dialog.winfo_exists() and hasattr(dialog, '_feedback'):
            dialog._feedback.set(message)

    def button(self, parent, title, function):
        primary = title.startswith(('保存', '确认', '按题目'))
        guarded = self.guard(function)
        def activate():
            previous = self._active_dialog
            self._active_dialog = parent.winfo_toplevel()
            if hasattr(self._active_dialog, '_feedback'):
                self._active_dialog._feedback.set('')
            try:return guarded()
            finally:self._active_dialog = previous
        if isinstance(parent, ActionBar):
            return parent.add(title, activate, primary)
        b = Button(parent, text=title, command=activate, primary=primary)
        b.pack(side='left', padx=(0, 8), pady=4)
        return b

    def combo(self, parent, label, values, initial):
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(side='left', padx=(0, 12), pady=(0, 6))
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=font(parent, 11), anchor='w').pack(anchor='w', pady=(0, 4))
        var = tk.StringVar(self.window, value=initial)
        ttk.Combobox(frame, textvariable=var, values=list(values), state='readonly',
                     width=17, style=PREFIX+'TCombobox', font=font(parent)).pack(fill='x')
        return var

    def _field(self, parent, title, var, width=None):
        label(parent, title, 11, MUTED).pack(anchor='w', pady=(6, 4))
        entry = ttk.Entry(parent, textvariable=var, style=PREFIX+'TEntry', font=font(parent), **({'width':width} if width else {}))
        entry.pack(fill='x', pady=(0, 5))
        return entry

    def _text(self, parent, height=4, readonly=False):
        text = ScrolledText(parent, height=height, wrap='word')
        skin_tree(text.frame)
        text.pack(fill='x', pady=(4, 8))
        if readonly:
            text.configure(state='disabled')
        return text

    def _build_study(self):
        # The tray reuses DailyStudy with this controller's existing store; host paths stay unchanged.
        from .daily_study import DailyStudy
        self.daily_study = DailyStudy(self.study)
        self.progress_text = tk.StringVar(self.window)
        body = panel(self.study_tab, '01  输出提示词', '复制老师提示词到网页，提交纸上试卷情况或具体问题；不另设模式。')
        self.daily_prompt_text = self._text(body, height=10, readonly=True)
        actions = ActionBar(body)
        self.button(actions, '复制学习提示词', self._daily_copy)
        label(body, '', 11, MUTED, textvariable=self.progress_text, wraplength=900).pack(fill='x', pady=6)
        incoming = panel(self.study_tab, '02  输入学习汇报', '粘贴网页复盘或答疑后的完整汇报，一次保存；编号自动识别。')
        self.daily_report_text = self._text(incoming, height=11)
        self._daily_busy = False
        self._daily_save_button = self.button(ActionBar(incoming), '保存学习汇报', self._daily_save)
        self.daily_receipt = tk.StringVar(self.window, '网页分析为建议，不自动开启提醒或计入实际学时。')
        label(incoming, '', 12, MUTED, textvariable=self.daily_receipt, wraplength=900).pack(fill='x', pady=(6, 12))
        self.button(ActionBar(incoming), '查看学习历史', self.show_history)
        self._daily_saved_text = None
        pending = self.daily_study.workspace()['pending_prompt']
        if pending:
            self.daily_prompt_text.configure(state='normal')
            self.daily_prompt_text.insert('1.0', pending['prompt'])
            self.daily_prompt_text.configure(state='disabled')

    def show_history(self):
        self.refresh_progress()
        value = self.daily_study.workspace()
        lines = ['已保存 '+str(value['progress']['submission_count'])+' 次；以下为最近5条。',
                 '保存日期不等于实际学习日期；学时未测量，网页薄弱点为建议。']
        for item in value['history']:
            lines += ['', item['saved_at'], item['summary']]
            if item.get('user_report'):
                u=item['user_report'];lines.append('用户自述：'+u['details'])
                lines.append('整体正确率未知。' if u['accuracy'] is None else '用户自述正确率：'+str(u['accuracy'])+'%；'+u['accuracy_basis'])
            if item.get('review_focus'):lines.append('下次可关注：'+item['review_focus'])
            for point in item['weak_points']:
                lines.append('建议复查：'+point['point']+'；依据：'+point['evidence'])
        if not value['history']:
            lines.append('还没有保存的学习记录。')
        self.dialog_text('学习历史', '\n'.join(lines))

    def _daily_copy(self):
        value = self.daily_study.prompt()
        self.daily_prompt_text.configure(state='normal')
        self.daily_prompt_text.delete('1.0', 'end')
        self.daily_prompt_text.insert('1.0', value['prompt'])
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(value['prompt'])
            self.feedback.set('已复制。去网页提交纸上练习情况或具体疑问。')
        except tk.TclError:
            self.daily_prompt_text.tag_add('sel', '1.0', 'end-1c')
            self.daily_prompt_text.focus_set()
            self.feedback.set('剪贴板暂不可用，全文已选中；请按 Ctrl+C 复制。')
        finally:
            self.daily_prompt_text.configure(state='disabled')
        if self._daily_saved_text is not None and self.daily_report_text.get('1.0','end-1c') == self._daily_saved_text:
            self.daily_report_text.delete('1.0','end')
            self._daily_saved_text = None
            self.daily_receipt.set('新一轮提示词已准备；结束后再粘贴汇报。')

    def _daily_save(self):
        if self._daily_busy:
            return
        self._daily_busy = True
        self._daily_save_button.configure(state='disabled')
        try:
            raw = self.daily_report_text.get('1.0','end-1c')
            value = self.daily_study.save(raw)
            self._daily_saved_text = raw
            message = '已经保存过，没有重复计数。' if value['already_saved'] else '已保存，记为一次学习提交。'
            self.feedback.set(message)
            user=value.get('user_report')
            rate=('用户自述正确率：'+str(user['accuracy'])+'%；'+user['accuracy_basis']) if user and user['accuracy'] is not None else '整体正确率未知（未提供）。'
            refs='\n'.join('网页参考支持结论（未独立核验）：'+f['conclusion']+'；来源：'+f['source']+'；依据：'+f['evidence'] for f in value.get('reference_findings',[]))
            self.daily_receipt.set(message+'\n'+value['summary']+'\n'+rate+('\n'+refs if refs else '')+'\n网页分析和薄弱点仍为建议；未增加实际学时或开启提醒。')
            self.refresh_progress()
        finally:
            self._daily_busy = False
            self._daily_save_button.configure(state='normal')

    def refresh_lessons(self):
        # Legacy import callbacks may still request a refresh; no selector is required.
        self.refresh_progress()

    def select_lesson(self):
        super().select_lesson()
        skin_tree(self.answers_frame)
        self._layout_answers(max(600, self.window.winfo_width()-90))

    def _layout_answers(self, width):
        if not hasattr(self, 'answers_frame'):
            return
        frames = self.answers_frame.winfo_children()
        if not frames:
            return
        desired = max(f.winfo_reqwidth() for f in frames)+14
        columns = max(1, min(5, width//max(100, desired)))
        for i, frame in enumerate(frames):
            frame.grid(row=i//columns, column=i%columns, padx=6, pady=5, sticky='w')

    def save_study(self):
        payload = self.study_input()
        payload.update(outcome=OUTCOMES[self.outcome.get()], source=self.result_source.get())
        self.controller.invoke('study.record', payload=payload)
        self.refresh_progress()
        self.feedback.set('已保存本次作答；当前核验状态：'+self.outcome.get())

    def grade_study(self):
        saved = self.controller.invoke('study.record_evaluated', payload=self.study_input())
        result = saved['evaluation']
        self.outcome.set(next((key for key, value in AUTO_OUTCOMES.items() if value == result['outcome']), '尚未核验'))
        self.result_source.set(result['source'])
        self.refresh_progress()
        self.feedback.set(f"已保存 {result['submitted_count']} 题作答，其中 {result['graded_count']} 题有可比较参考答案。")
        states = {'correct':'正确', 'incorrect':'错误', 'unverified':'未核验'}
        rows = [f"第 {row['id']} 题：{states[row['outcome']]}" for row in result['questions']]
        self.dialog_text('按材料答案核验结果', self.feedback.get()+'\n\n'+'\n'.join(rows)+
                         '\n\n仅核对已提交题目，依据来自导入材料。薄弱点请按实际卡点填写。')

    def _build_memory(self):
        body = panel(self.memory_tab, '项目记录', '决定、实现、自动检查与人工验收分别记录。候选不会自动成为事实。')
        # Two rows keep every independent status readable at the minimum width.
        first = tk.Frame(body, bg=PANEL);first.pack(fill='x')
        self.kind = self.combo(first, '类别', KINDS, '项目日志')
        self.decision = self.combo(first, '决定', DECISIONS, '候选')
        second = tk.Frame(body, bg=PANEL);second.pack(fill='x')
        self.implementation = self.combo(second, '实现范围', IMPLEMENTATIONS, '未实现')
        self.auto_check = self.combo(second, '自动检查', AUTO, '未测')
        self.manual_check = self.combo(second, '人工验收', MANUAL, '未验收')
        self.record_title = tk.StringVar(self.window)
        self.record_source = tk.StringVar(self.window)
        self.occurred_at = tk.StringVar(self.window, datetime.now().strftime('%Y-%m-%d'))
        self.scope, self.evidence, self.supersedes = [tk.StringVar(self.window) for _ in range(3)]
        for title, var in [('标题', self.record_title), ('来源（必填：用户确认 / 文件 / 聊天依据）', self.record_source),
                            ('发生日期（不确定就写日期待补）', self.occurred_at), ('适用范围 / 版本', self.scope),
                            ('证据文件 / 验证范围', self.evidence), ('替代旧记录 ID（可留空，旧记录保留历史）', self.supersedes)]:
            self._field(body, title, var)
        label(body, '正文', 11, MUTED).pack(anchor='w', pady=(6, 0))
        self.record_body = self._text(body, 6)
        self.memory_confirmed = tk.BooleanVar(self.window, False)
        ttk.Checkbutton(body, text='我已确认：可作为长期记忆（仅已采用的偏好、经历或当前事实）',
                        variable=self.memory_confirmed, style=PREFIX+'TCheckbutton').pack(anchor='w', pady=5)
        actions = ActionBar(body);actions.pack(fill='x')
        for title, fn in [('保存记录', self.save_record), ('查看已确认记忆', self.show_memories), ('导出 Markdown', self.export_markdown)]:
            self.button(actions, title, fn)
        history = panel(self.memory_tab, '当前与历史记录', '双击查看完整内容；替代旧记录时保留历史并填写旧 ID。')
        self.records_list = tk.Listbox(history, height=8)
        self.records_list.pack(fill='x', pady=4)
        skin_widget(self.records_list)
        self.records_list.bind('<Double-Button-1>', lambda _: self.view_record())

    def save_record(self):
        super().save_record()
        self.feedback.set('项目记录已保存；长期记忆仍按明确确认与类别条件处理。')

    def refresh_records(self):
        self.record_ids = self.controller.invoke('memory.records')
        self.records_list.delete(0, 'end')
        decisions = {**{v:k for k,v in DECISIONS.items()}, 'superseded':'已替代'}
        implementations = {v:k for k,v in IMPLEMENTATIONS.items()}
        for row in self.record_ids:
            self.records_list.insert('end', f"[{decisions.get(row['decision'], row['decision'])}] {row['title']} · "
                f"{implementations.get(row['implementation'], row['implementation'])} · {'当前' if row['active'] else '历史'}")

    def _build_reminders(self):
        settings = panel(self.reminder_tab, '提醒设置', '保存提醒与启用提醒是两件事；只在程序运行期间执行。')
        self.enabled_var = tk.BooleanVar(self.window, self.controller.reminders.enabled)
        self.quiet_var = tk.BooleanVar(self.window, self.controller.reminders.quiet)
        Switch(settings, self.enabled_var, command=lambda: self.controller.set_reminders_enabled(self.enabled_var.get()),
               text='启用提醒（当前程序运行期间）').pack(fill='x')
        Switch(settings, self.quiet_var, command=lambda: self.controller.set_quiet_mode(self.quiet_var.get()),
               text='安静模式（到期暂存，解除后集中显示）', width=660).pack(fill='x')
        body = panel(self.reminder_tab, '单次提醒', '按本机时间安排一次提醒；保存后可在列表查看。')
        self.reminder_title = tk.StringVar(self.window, '要不要把上次那道阅读再看一小段？')
        self.reminder_time = tk.StringVar(self.window, (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d %H:%M'))
        self._field(body, '提醒内容', self.reminder_title)
        self._field(body, '本地时间（例如 2026-10-04 20:00）', self.reminder_time)
        actions = ActionBar(body);actions.pack(fill='x')
        for title, fn in [('保存单次提醒', self.add_reminder), ('取消选中提醒', self.cancel_reminder), ('刷新 / 恢复后核对时间', self.refresh_reminders)]:
            self.button(actions, title, fn)
        self.reminder_list = tk.Listbox(body, height=7)
        self.reminder_list.pack(fill='x', pady=(12, 3));skin_widget(self.reminder_list)
        backup = panel(self.reminder_tab, '导出与备份', '请选择新文件；保留原数据库与历史。')
        actions = ActionBar(backup);actions.pack(fill='x')
        self.button(actions, '导出全部数据 JSON', self.export_json)
        self.button(actions, '备份数据库', self.backup)
        label(backup, '恢复备份前先退出桌宠并保留旧数据库副本。\n关闭此窗口后，已启用的提醒仍会执行；关闭提醒或退出程序会停止。',
              12, MUTED, wraplength=870).pack(anchor='w', pady=(10, 0))

    def add_reminder(self):
        super().add_reminder()
        self.feedback.set('单次提醒已保存；启用状态保持当前设置。')

    def refresh_reminders(self):
        self.controller.reminders.refresh()
        self.reminder_ids = self.controller.invoke('reminder.list')
        self.reminder_list.delete(0, 'end')
        states = {'pending':'等待到期', 'queued':'安静模式暂存', 'delivered':'已通知', 'cancelled':'已取消'}
        for row in self.reminder_ids:
            date = datetime.fromtimestamp(row['due_epoch']).strftime('%Y-%m-%d %H:%M')
            self.reminder_list.insert('end', f"[{states.get(row['status'], row['status'])}] {date} · {row['title']}")

    def dialog_text(self, title, text, editable=False, save_callback=None):
        dialog = tk.Toplevel(self.window)
        configure_window(dialog, title, 800, 600)
        dialog.transient(self.window)
        header(dialog, title, '先预览内容，再按需要复制或保存。')
        body = tk.Frame(dialog, bg=BG);body.pack(fill='both', expand=True, padx=22)
        widget = ScrolledText(body, wrap='word');widget.pack(fill='both', expand=True)
        skin_tree(widget.frame);widget.insert('1.0', text)
        if not editable:widget.configure(state='disabled')
        response = tk.StringVar(dialog)
        dialog._feedback = response
        label(dialog, '', 11, GOOD, textvariable=response).pack(fill='x', padx=22, pady=(8, 0))
        actions = ActionBar(dialog);actions.pack(fill='x', padx=22, pady=12)
        def copy():
            dialog.clipboard_clear();dialog.clipboard_append(widget.get('1.0', 'end-1c'))
            response.set('已复制，可手动粘贴。')
        self.button(actions, '复制全文', copy)
        if save_callback:
            def save():
                save_callback(widget.get('1.0', 'end-1c'));dialog.destroy()
            self.button(actions, '保存', save)
        self.button(actions, '关闭', dialog.destroy)
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        return dialog

    def import_web_result(self):
        # Keep original parse/edit/commit payload and duplicate-receipt behavior.
        before = set(self.window.winfo_children())
        super().import_web_result()
        for dialog in set(self.window.winfo_children())-before:
            if isinstance(dialog, tk.Toplevel):
                configure_window(dialog, '网页学习结果 · 读取草稿后确认保存', 980, 820, (740, 520))
                dialog.transient(self.window)
                self._skin_dialog(dialog)

    def _skin_dialog(self, dialog):
        skin_tree(dialog)
        for widget in dialog.winfo_children():
            if isinstance(widget, tk.Frame):widget.configure(bg=BG)
        dialog._feedback = tk.StringVar(dialog)
        label(dialog, '', 11, ERROR, textvariable=dialog._feedback,
              wraplength=900).pack(side='bottom', fill='x', padx=12, pady=5)
        # New draft controls created by the original load callback get our local style.
        def mapped(event):
            widget = event.widget
            skin_widget(widget)
            if isinstance(widget, ttk.LabelFrame):
                widget.bind('<Configure>', lambda e: self._draft_answers(widget, e.width), add='+')
            if isinstance(widget, ttk.Label) and len(str(widget.cget('text'))) > 40:
                widget.configure(wraplength=max(300, dialog.winfo_width()-65))
        dialog.bind('<Map>', mapped, add='+')
        def resized(event):
            if event.widget == dialog:
                def wrap(widget):
                    if isinstance(widget, ttk.Label) and len(str(widget.cget('text'))) > 40:
                        widget.configure(wraplength=max(300, event.width-65))
                    for child in widget.winfo_children():wrap(child)
                wrap(dialog)
        dialog.bind('<Configure>', resized, add='+')
        dialog.bind('<Escape>', lambda _: dialog.destroy())
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        canvas = next((w for w in descendants(dialog) if isinstance(w, tk.Canvas)), None)
        if canvas is not None:
            canvas.configure(yscrollincrement=24)
            form = canvas.winfo_children()[0]
            def belongs(widget):
                while widget is not None and widget != form:
                    widget = getattr(widget, 'master', None)
                return widget == form
            def wheel(event):
                if belongs(event.widget) and event.widget.winfo_class() not in ('Text', 'TCombobox', 'Listbox'):
                    delta = -1 if getattr(event, 'num', 0) == 4 or getattr(event, 'delta', 0) > 0 else 1
                    canvas.yview_scroll(delta*2, 'units')
                    return 'break'
            def focus(event):
                if belongs(event.widget):
                    bounds = canvas.bbox('all')
                    if bounds:
                        top = event.widget.winfo_rooty()-form.winfo_rooty()
                        bottom = top+event.widget.winfo_height()
                        visible, height = canvas.canvasy(0), canvas.winfo_height()
                        if top < visible:canvas.yview_moveto(max(0, top-10)/bounds[3])
                        elif bottom > visible+height:canvas.yview_moveto(max(0, bottom-height+10)/bounds[3])
            for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                dialog.bind(sequence, wheel, add='+')
            dialog.bind('<FocusIn>', focus, add='+')

    def _draft_answers(self, frame, width):
        children = frame.winfo_children()
        if children:
            desired = max(w.winfo_reqwidth() for w in children)+12
            columns = max(1, min(5, (width-20)//max(100, desired)))
            for index, child in enumerate(children):
                child.grid(row=index//columns, column=index%columns, padx=4, pady=4, sticky='w')


class ModuleController(OriginalController):
    def open(self):
        if self.closed:
            raise RuntimeError('模块已退出，请重新创建控制器')
        if self.window is None:
            self.window = ToolWindow(self)
        else:
            self.window.window.deiconify()
            self.window.window.lift()
        self.reminders.refresh()
