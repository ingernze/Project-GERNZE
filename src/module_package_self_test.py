"""Frozen empty-host acceptance; uses only own isolated installation and data."""
import json,os,sys,traceback,time
from pathlib import Path
def schedule(pet):
    import app
    from workbench.bridge import Bridge
    from module_packages_window import open_packages
    from PIL import ImageGrab
    checks=[];started=time.monotonic()
    def check(name,value):
        checks.append({'check':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def run():
        try:
            modules=pet.optional_modules
            check('frozen_base',getattr(sys,'frozen',False) and modules.managed)
            check('initial_optional_modules_absent',all(not modules.installed(key) for key in ('cet6','fixed_voice','voice_engine')))
            check('no_fixed_audio_in_base',not (app.ROOT/'assets/voice').exists() and not pet.voice.clips)
            check('no_engine_or_personal_models_in_base',not (Path(sys.executable).parent/'Hecate_Voice_Module').exists())
            server=pet.workbench.open(launch_browser=False);bridge=server.bridge
            check('base_reports_modules_absent',bridge.call({'command':'state.summary','params':{}})['optional_modules']['cet6'] is False)
            try:bridge.call({'command':'daily.workspace','params':{}})
            except ValueError:check('direct_learning_call_denied',True)
            else:check('direct_learning_call_denied',False)
            packs=Path(os.environ['HECATE_TEST_PACKAGES'])
            modules.install(packs/'cet6.zip')
            check('learning_installed',modules.installed('cet6'))
            workspace=bridge.call({'command':'daily.workspace','params':{}})
            check('external_learning_python_loaded',workspace is not None and 'hebao_modules.daily_study' in sys.modules)
            check('loaded_from_installed_payload',str(modules.folder('cet6')) in sys.modules['hebao_modules.daily_study'].__file__)
            with bridge.store.connection() as db:
                check('blank_personal_sessions',db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0)
            record=bridge.memory.add(kind='project_log',title='隔离验收记录',body='移除后必须保留',decision='candidate',source='acceptance',memory_confirmed=False)
            modules.uninstall('cet6')
            check('learning_removed',not modules.installed('cet6'))
            try:bridge.call({'command':'daily.workspace','params':{}})
            except ValueError:check('loaded_module_also_denied_after_remove',True)
            else:check('loaded_module_also_denied_after_remove',False)
            check('user_record_preserved',any(row['id']==record for row in bridge.memory.records()))
            modules.install(packs/'cet6.zip');check('learning_reinstalled',bridge.call({'command':'daily.workspace','params':{}}) is not None)
            modules.install(packs/'fixed_voice.zip');pet.voice_module.close();pet.reload_optional_voice()
            check('all_approved_audio_loaded',len(pet.voice.clips)==21)
            modules.uninstall('fixed_voice');pet.voice_module.close();pet.reload_optional_voice()
            check('fixed_audio_removed_without_playback',not pet.voice.clips)
            modules.uninstall('cet6')
            window=open_packages(pet);window.update_idletasks()
            check('single_native_manager',open_packages(pet) is window)
            app.OUTPUT.mkdir(parents=True,exist_ok=True)
            x,y=window.winfo_rootx(),window.winfo_rooty()
            ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height())).save(app.OUTPUT/'模块管理_空白启动包.png')
            check('manager_button_visible',window.install_button.winfo_rooty()+window.install_button.winfo_height()<=y+window.winfo_height())
            window.close();pet.workbench.close_service()
            check('service_released',not pet.workbench.worker.is_alive())
        except Exception:checks.append({'check':'unexpected_error','passed':False,'error':traceback.format_exc()})
        finally:
            try:pet.quit()
            except Exception:checks.append({'check':'exit_error','passed':False,'error':traceback.format_exc()})
            app.OUTPUT.mkdir(parents=True,exist_ok=True)
            (app.OUTPUT/'module_package_results.json').write_text(json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks,'duration_s':time.monotonic()-started,'no_network_or_gpu_synthesis':True},ensure_ascii=False,indent=2),encoding='utf8')
    pet.root.after(400,run)
