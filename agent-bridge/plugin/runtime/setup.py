"""Prepare plugin-owned runtime and basic empty data. Never imports a user's persona."""
import argparse,json,os,shutil,subprocess,sys,venv
from paths import ROOT,DATA,python
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--register',action='store_true');args=parser.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    if not python().is_file():venv.EnvBuilder(with_pip=True).create(DATA/'runtime')
    subprocess.check_call([str(python()),'-m','pip','install','-r',str(ROOT/'bridge/requirements.txt')])
    for name in ['persona.md','foundation.json']:
        destination=DATA/name
        if not destination.exists():shutil.copy2(ROOT/'defaults'/name,destination)
    config=DATA/'settings.json'
    if not config.exists():config.write_text(json.dumps({'state_db':str(DATA/'agent-memory.sqlite3'),'persona':str(DATA/'persona.md'),'foundation':str(DATA/'foundation.json'),'desktop_journal':None,'approved_snapshot':None},ensure_ascii=False,indent=2),encoding='utf-8')
    if args.register:
        home=Path.home()
        target=home/'.codex/plugins/gernze-codex'
        target.mkdir(parents=True,exist_ok=True)
        if ROOT.resolve()!=target.resolve():shutil.copytree(ROOT,target,dirs_exist_ok=True)
        catalog=home/'.agents/plugins/marketplace.json';catalog.parent.mkdir(parents=True,exist_ok=True)
        value=json.loads(catalog.read_text(encoding='utf-8-sig')) if catalog.exists() else {'name':'gernze-local','interface':{'displayName':'本机插件'},'plugins':[]}
        plugins=value.setdefault('plugins',[])
        entry={'name':'gernze-codex','source':{'source':'local','path':'./.codex/plugins/gernze-codex'},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Productivity'}
        value['plugins']=[e for e in plugins if e.get('name')!='gernze-codex']+[entry]
        catalog.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('本机依赖与独立资料已准备。重启Codex后启用插件；提醒钩子由宿主要求首次信任。')
if __name__=='__main__':
    from pathlib import Path
    main()
