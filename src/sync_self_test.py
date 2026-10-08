"""Windows host integration checks with isolated data and no account reads."""
import http.client
import json
import os
import time
import threading
import traceback
import win32gui
import win32con
from tray_win32 import SHOW, HIDE, CALLBACK
from tray_popup import TrayPopup


def schedule(pet):
    import app
    checks = []
    servers = []
    def check(name, ok):
        checks.append({'check': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    def call(server, command, params=None, authenticated=True):
        c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        h = {'Content-Type':'application/json', 'Origin':server.origin}
        if authenticated: h['Authorization'] = 'Bearer ' + server.token
        try:
            c.request('POST','/api/call', json.dumps({'command':command,'params':params or {}}),h)
            r=c.getresponse()
            return r.status, json.loads(r.read())
        finally: c.close()
    def guard(fn):
        def wrapped():
            try: fn()
            except Exception:
                checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
                finish()
        return wrapped
    def begin():
        check('startup_uses_2x',pet.scale==2)
        check('credentials_not_read_and_quota_off', not pet.key_present and not pet.quota_enabled)
        pet._cancel_reading()
        s=pet.workbench.open(launch_browser=False);servers.append(s)
        from workbench.server import ASSETS
        for path in ASSETS:
            c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3)
            try:
                c.request('GET',path)
                r=c.getresponse();body=r.read()
                if r.status!=200 or not body:
                    raise AssertionError('packaged_static_resource:' + path)
            finally: c.close()
        check('all_packaged_frontend_resources_served',True)
        code,result=call(s,'memory.list')
        check('four_project_records_loaded',code==200 and len(result['result'])==4)
        check('project_records_not_personality_memories',not s.bridge.memory.confirmed_memories())
        check('same_server_reused',pet.workbench.open(launch_browser=False) is s)
        check('no_unauthenticated_api',call(s,'state.summary',authenticated=False)[0]==403)
        call(s,'appearance.set',{'theme':'light'})
        pet.modules.open()
        check('native_modules_use_existing_root',pet.modules.controller.root is pet.root)
        controller = pet.modules.controller
        check('native_and_workbench_share_learning_database',controller.store.path.resolve() == s.bridge.store.path.resolve())
        daily = controller.window.daily_study
        prompt = daily.prompt()
        check('paper_teacher_waits_for_user_without_quiz', '收到问题后直接讲解' in prompt['prompt'] and '每轮只问一个理解问题' not in prompt['prompt'])
        check('prompt_alone_does_not_count_learning',s.bridge.daily.workspace()['progress']['submission_count'] == 0)
        report = json.loads(prompt['prompt'][prompt['prompt'].rfind('\n{')+1:])
        report.update(scenario='question_help',discussion_completed=True,summary='隔离验收：说明although让步关系',evidence='隔离测试输入，不是真实学习记录',
            user_report={'material':'隔离验收模拟材料','details':'测试疑问：Although it was late, she stayed. 是原因吗？','accuracy':None,'accuracy_basis':''},
            activities=[{'skill':'reading','task':'隔离验收连接词答疑','response':'测试疑问：although是原因吗？','feedback':'模拟反馈：although表示尽管，构成让步关系。'}],review_focus='隔离测试建议，不是真实用户结论')
        report_text = json.dumps(report,ensure_ascii=False)
        controller.window.daily_report_text.insert('1.0',report_text)
        controller.window._daily_save()
        history = s.bridge.daily.workspace()['history']
        check('native_save_visible_in_workbench',len(history)==1 and history[0]['summary']==report['summary'])
        check('paper_report_does_not_invent_accuracy_or_evaluation',history[0]['user_report']['accuracy'] is None and history[0]['local_evaluation'] is None)
        check('next_prompt_uses_saved_paper_context',report['user_report']['details'] in s.bridge.daily.prompt()['prompt'])
        code,result=call(s,'daily.save',{'text':report_text})
        check('save_from_second_entry_does_not_duplicate',code==200 and result['result']['already_saved'] and s.bridge.daily.workspace()['progress']['submission_count']==1)
        before=s.bridge.daily.workspace()['progress']['submission_count']
        pending=s.bridge.daily.prompt();not_finished=json.loads(pending['prompt'][pending['prompt'].rfind('\n{')+1:])
        code,result=call(s,'daily.save',{'text':json.dumps(not_finished,ensure_ascii=False)})
        check('unfinished_template_rejected_without_learning',code==400 and s.bridge.daily.workspace()['progress']['submission_count']==before)
        check('paper_save_keeps_no_automatic_reminders',not s.bridge.store.reminders())
        menu=TrayPopup(pet,pet.root.winfo_screenwidth()-10,pet.root.winfo_screenheight()-10)
        check('workbench_menu_available',any(cmd=='workbench:open' for _,cmd in menu.items))
        reading_box=next(box for box,cmd in menu.items if cmd.startswith('reading:'))
        quota_box=next(box for box,cmd in menu.items if cmd=='quota:open')
        check('manual_reading_is_in_developer_section',reading_box[1] > 392 and quota_box[1] < 378)
        check('menu_preserves_requested_scale',abs(menu.s-0.75*app.ctypes.windll.user32.GetDpiForWindow(menu.winfo_id())/96)<0.05)
        menu.close()
        win32gui.PostMessage(pet.tray.hwnd,win32con.WM_COMMAND,HIDE,0)
        pet.root.after(200,guard(hidden))
    def hidden():
        check('native_tray_message_hides_pet',not pet.visible)
        check('hidden_animation_timers_canceled',all(getattr(pet,n) is None for n in ('frame_job','reading_job','reading_start_job','reading_end_job')))
        win32gui.PostMessage(pet.tray.hwnd,win32con.WM_COMMAND,SHOW,0)
        pet.root.after(200,guard(shown))
    def shown():
        check('native_tray_restores_on_main_thread',pet.visible and threading.get_ident()==pet.ui_thread)
        pet._cancel_reading()
        check('page_close_returns_success',call(servers[-1],'session.close')[0]==200)
        pet.root.after(200,guard(reopen))
    def reopen():
        check('page_close_keeps_pet',pet.visible and not pet.closing)
        s=pet.workbench.open(launch_browser=False);servers.append(s)
        check('theme_survives_service_restart',s.bridge.appearance_theme()=='light')
        check('records_not_duplicated',len(s.bridge.memory.records())==4)
        win32gui.PostMessage(pet.tray.hwnd,CALLBACK,0,win32con.WM_LBUTTONDBLCLK)
        if os.environ.get('HECATE_TEST_WORKBENCH_WINDOW') == '1':
            pet.workbench.open()
            pet.workbench.open()
            pet.workbench.open()
            browser_deadline[0] = time.monotonic() + 18
            pet.root.after(100,guard(browser_ready))
        else:
            pet.root.after(100,finish)
    browser_deadline = [0]
    initial_window = [None]
    def browser_ready():
        window = pet.workbench.window
        if not window.ready.is_set() and time.monotonic() < browser_deadline[0]:
            pet.root.after(100,guard(browser_ready))
            return
        check('actual_browser_window_started',window.hwnd is not None and not window.error)
        check('rapid_three_opens_launch_one_window',window.launch_count == 1 and len(window._windows()) == 1)
        initial_window[0] = window.hwnd
        win32gui.ShowWindow(window.hwnd,win32con.SW_MINIMIZE)
        pet.workbench.open()
        check('reopen_restores_minimized_existing_window',window.hwnd == initial_window[0] and not win32gui.IsIconic(window.hwnd))
        check('reopen_keeps_browser_process_and_service',window.launch_count == 1 and pet.workbench.server is servers[-1])
        check('reopen_brings_existing_workbench_to_foreground',win32gui.GetForegroundWindow() == window.hwnd)
        # Close the owned window, leave enough time for the authenticated pagehide
        # to reclaim its service, then open again with its persisted fake records.
        window.close()
        pet.root.after(6000,guard(browser_reopen))
    def browser_reopen():
        check('browser_close_reclaims_service',not pet.workbench.worker.is_alive())
        server = pet.workbench.open(); servers.append(server)
        browser_deadline[0] = time.monotonic() + 18
        pet.root.after(100,guard(browser_reopened))
    def browser_reopened():
        window = pet.workbench.window
        if not window.ready.is_set() and time.monotonic() < browser_deadline[0]:
            pet.root.after(100,guard(browser_reopened))
            return
        check('actual_closed_workbench_can_reopen',window.hwnd is not None and not window.error)
        check('reopened_workbench_still_one_window',len(window._windows()) == 1 and window.launch_count == 2)
        check('browser_reopen_preserves_learning_data',len(servers[-1].bridge.memory.records()) == 4)
        finish()
    def finish():
        try:
            pet.quit()
            check('exit_releases_server_thread',not pet.workbench.worker.is_alive())
            if pet.workbench.window:
                check('exit_releases_owned_browser_window',not pet.workbench.window._windows())
            check('exit_releases_notification_window',pet.bridge.released)
            check('exit_releases_tray',not pet.tray.is_alive())
        except Exception:
            checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
        app.OUTPUT.mkdir(parents=True,exist_ok=True)
        (app.OUTPUT/'sync_results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    pet.root.after(200,guard(begin))
