"""Unregister this one plugin. Personal records and other connectors remain untouched."""
import json
from pathlib import Path
from paths import DATA
catalog=Path.home()/'.agents/plugins/marketplace.json'
if catalog.is_file():
    value=json.loads(catalog.read_text(encoding='utf-8-sig'))
    value['plugins']=[e for e in value.get('plugins',[]) if e.get('name')!='gernze-codex']
    catalog.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
manifest=DATA/'task-reminders.json'
if manifest.is_file():manifest.write_text(json.dumps({'id':'gernze-codex','enabled':False,'capabilities':[]}),encoding='utf-8')
print('已移除本插件入口；本机资料保留。请在Codex插件页关闭/移除已安装的缓存副本，并重启。')
