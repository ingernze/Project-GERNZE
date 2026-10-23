"""Narrow JSON facade over the existing Python modules. No desktop commands."""
from pathlib import Path
import json
import os
import tempfile

from libao_modules.core import MemoryModule, Store, StudyModule, text_value
from optional_modules import OptionalModules
from libao_modules.security import strict_json


CONTRACTS = {
    'daily.workspace': (set(), set()),
    'daily.prompt': (set(), {'lesson_id'}),
    'daily.parse': ({'text'}, set()),
    'daily.save': ({'text'}, set()),
    'state.summary': (set(), set()),
    'modules.list': (set(), set()),
    'lesson.import': ({'payload'}, set()),
    'lesson.get': ({'lesson_id'}, set()),
    'study.evaluate': ({'lesson_id', 'answers'}, set()),
    'study.save': ({'lesson_id', 'answers'}, {'tags', 'note', 'minutes', 'next_review'}),
    'study.hint': ({'lesson_id', 'question_id'}, {'level'}),
    'study.explain': ({'lesson_id', 'question_id'}, set()),
    'study.history': (set(), {'lesson_id'}),
    'handoff.prompt': ({'lesson_id'}, {'mode'}),
    'handoff.parse': ({'lesson_id', 'text'}, set()),
    'handoff.commit': ({'result'}, {'minutes', 'verified', 'review_at'}),
    'memory.list': (set(), set()),
    'reminder.list': (set(), set()),
    'backup.export': (set(), set()),
    'appearance.set': ({'theme'}, set()),
}


def validate_call(value, contracts=CONTRACTS):
    if not isinstance(value, dict) or set(value) != {'command', 'params'}:
        raise ValueError('调用须仅含 command 和 params')
    command, params = value['command'], value['params']
    if not isinstance(command, str) or command not in contracts:
        raise ValueError('不允许的本地接口')
    required, optional = contracts[command]
    if not isinstance(params, dict) or not required <= params.keys() or params.keys() - required - optional:
        raise ValueError('接口参数不匹配')
    for name in ('lesson_id', 'question_id'):
        if name in params:
            text_value(params[name], name, 100)
    return command, params


class Bridge:
    def __init__(self, data_dir, *, modules=None):
        self.appearance_path = Path(data_dir) / 'workbench' / 'appearance.json'
        self.store = Store(Path(data_dir) / 'modules' / 'hebao_modules.sqlite3')
        self.study = StudyModule(self.store)
        self.memory = MemoryModule(self.store)
        self.modules = modules or OptionalModules(Path(__file__).resolve().parents[1], data_dir)
        self.handoff = self.daily = None
        if not self.modules.managed: self._learning()

    def _learning(self):
        self.modules.activate_study()
        if self.daily is None:
            from libao_modules.handoff import WebHandoff
            from libao_modules.daily_study import DailyStudy
            self.handoff = WebHandoff(self.study)
            self.daily = DailyStudy(self.study)

    def appearance_theme(self):
        try:
            with self.appearance_path.open('rb') as stream:
                raw = stream.read(4097)
            value = strict_json(raw.decode('utf-8'), max_bytes=4096)
            if (isinstance(value, dict) and value.get('schema_version') == 1
                    and value.get('theme') in ('dark', 'light')):
                return value['theme']
        except (OSError, ValueError, UnicodeError, TypeError):
            pass
        return 'dark'

    def save_appearance(self, theme):
        if not isinstance(theme, str) or theme not in ('dark', 'light'):
            raise ValueError('主题须为 dark 或 light')
        self.appearance_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    dir=self.appearance_path.parent, prefix='appearance-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({'schema_version': 1, 'theme': theme}, stream)
                stream.write('\n')
            os.replace(temporary, self.appearance_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {'theme': theme, 'persisted': True}

    def call(self, value):
        command, p = validate_call(value)
        if command.startswith(('daily.', 'lesson.', 'study.', 'handoff.')): self._learning()
        if command == 'modules.list': return self.modules.snapshot()
        if command == 'daily.workspace':
            return self.daily.workspace()
        if command == 'daily.prompt':
            return self.daily.prompt(p.get('lesson_id'))
        if command == 'daily.parse':
            return self.daily.parse(p['text'])
        if command == 'daily.save':
            return self.daily.save(p['text'])
        if command == 'appearance.set':
            return self.save_appearance(p['theme'])
        if command == 'state.summary':
            installed = self.modules.installed('cet6')
            return {'lessons': self.study.lessons() if installed else [],
                    'progress': self.study.progress_summary() if installed else {},
                    'due_reviews': self.study.due_reviews() if installed else [],
                    'optional_modules': {key: self.modules.installed(key) for key in ('cet6','voice_engine')},
                    'core_features': {'fixed_voice': self.modules.installed('fixed_voice')}}
        if command == 'lesson.import':
            return {'lesson_id': self.study.import_lesson(p['payload'])}
        if command == 'lesson.get':
            return self.study.lesson(p['lesson_id'])
        if command == 'study.evaluate':
            return self.study.evaluate(p['lesson_id'], p['answers'])
        if command == 'study.save':
            return self.study.record_evaluated(p['lesson_id'], p['answers'],
                tags=p.get('tags', []), note=p.get('note', ''), minutes=p.get('minutes', 0),
                next_review=p.get('next_review'))
        if command == 'study.hint':
            return self.study.local_hint(p['lesson_id'], p['question_id'], p.get('level', 0))
        if command == 'study.explain':
            return self.study.local_explanation(p['lesson_id'], p['question_id'])
        if command == 'study.history':
            return self.study.history(p.get('lesson_id'))
        if command == 'handoff.prompt':
            return {'prompt': self.handoff.prepare_prompt(p['lesson_id'], p.get('mode', 'practice'))}
        if command == 'handoff.parse':
            return self.handoff.parse(p['lesson_id'], p['text'])
        if command == 'handoff.commit':
            # The browser cannot request reminder creation or arbitrary tool execution.
            return self.handoff.commit(p['result'], minutes=p.get('minutes', 0),
                verified=p.get('verified', False), review_at=p.get('review_at'))
        if command == 'memory.list':
            return self.memory.records()
        if command == 'reminder.list':
            return self.store.reminders()
        if command == 'backup.export':
            return {'json': self.store.export_json()}
        raise ValueError('不允许的本地接口')
