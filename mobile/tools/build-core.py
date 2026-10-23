"""Generate build-only data. Public is default; never mutate private source inputs."""
from pathlib import Path
import argparse,json,os,shutil

def generate(root,mode='public',output=None):
    root=Path(root);stage=Path(output) if output else root/'build/generated'/mode
    stage.mkdir(parents=True,exist_ok=True)
    suffix='' if mode=='private' else '.example'
    source=root/'src/workbench'
    core=source/('companion_core_memory'+suffix+'.json')
    persona=source/('companion_persona'+suffix+'.md')
    # Explicit private builds require both existing owner files; no DB scraping.
    value=json.loads(core.read_text(encoding='utf8'))
    if value.get('schemaVersion')!=1 or type(value.get('entries')) is not list:raise ValueError('invalid_core_input')
    if mode=='public' and value['entries']:raise ValueError('public_core_must_be_empty')
    (stage/'companion_core_memory.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    shutil.copy2(persona,stage/'companion_persona.md')
    web=root/'mobile/www';web.mkdir(parents=True,exist_ok=True)
    shutil.copy2(stage/'companion_core_memory.json',web/'chat-core-memory.json')
    shutil.copy2(stage/'companion_persona.md',web/'chat-persona.txt')
    return stage

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['public','private'],default='private' if os.environ.get('GERNZE_PRIVATE_BUILD')=='1' else 'public')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();stage=generate(Path(__file__).resolve().parents[2],args.mode,args.output)
    print('Generated '+args.mode+' build inputs: '+str(stage))
