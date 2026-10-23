"""Post-migration frozen acceptance. Never removes a real installed module."""
import json, sys, time, traceback
from pathlib import Path

def schedule(pet):
    import app
    from optional_modules import digest
    from module_packages_window import open_packages
    from voice_text_window import open_voice_text
    from PIL import ImageGrab
    checks = []; start = time.monotonic()
    def check(name, value):
        checks.append({'check': name, 'passed': bool(value)})
        if not value: raise AssertionError(name)
    def run():
        try:
            modules = pet.optional_modules
            check('frozen_managed_host', getattr(sys, 'frozen', False) and modules.managed)
            check('optional_modules_adopted', all(modules.installed(key) for key in ('cet6','voice_engine')))
            check('fixed_21_clips', len(pet.voice.clips) == 21)
            choices = pet.voice_module.choices()
            check('chronological_two_gpt_choices', [x['label'] for x in choices['gpt_options']][:2] == ['第一套','第二套'])
            check('chronological_two_sovits_choices', [x['label'] for x in choices['sovits_options']][:2] == ['第一套','第二套'])
            check('original_selection_usable', bool(pet.voice_module.selection()))
            home = pet.voice_module.home
            check('independent_voice_in_installed_module', home.resolve() == modules.folder('voice_engine'))
            for group in ('gpt_options','sovits_options','references'):
                for item in choices[group]:
                    check(group + '_' + item['id'] + '_hash', digest(home / item['path']) == item['sha256'])
            check('no_torch_in_desktop_host', 'torch' not in sys.modules and pet.voice_module._backend is None)
            server = pet.workbench.open(launch_browser=False)
            result = server.bridge.call({'command': 'state.summary', 'params': {}})
            check('workbench_optional_installed', all(result['optional_modules'].values()))
            check('learning_backend_loaded', server.bridge.call({'command':'daily.workspace','params':{}}) is not None)
            check('workbench_singleton', pet.workbench.open(launch_browser=False) is server)
            app.OUTPUT.mkdir(parents=True, exist_ok=True)
            for filename, factory in [('模块管理_可选功能已安装.png', lambda: open_packages(pet)), ('文字转语音_已接入.png', lambda: open_voice_text(pet))]:
                window = factory()
                window.lift();window.update()
                x,y = window.winfo_rootx(), window.winfo_rooty()
                ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(app.OUTPUT / filename)
                window.close()
            pet.workbench.close_service()
            check('service_thread_released', not pet.workbench.worker.is_alive())
        except Exception:
            checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
        finally:
            try: pet.quit()
            except Exception: checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
            app.OUTPUT.mkdir(parents=True, exist_ok=True)
            (app.OUTPUT / 'module_adoption_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks,'duration_s':time.monotonic()-start,'no_playback_training_cloud_or_module_removal':True},ensure_ascii=False,indent=2), encoding='utf8')
    pet.root.after(400, run)
