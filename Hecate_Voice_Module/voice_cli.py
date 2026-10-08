import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse,json
from voice_backend import VoiceBackend
p=argparse.ArgumentParser(description='赫宝独立语音后端')
p.add_argument('--list',action='store_true');p.add_argument('--text');p.add_argument('--gpt',choices=['1','2'],default='2');p.add_argument('--sovits',choices=['1','2'],default='2');p.add_argument('--reference',choices=['denia_02','denia_06'],default='denia_06');p.add_argument('--play',action='store_true');p.add_argument('--fixed');p.add_argument('--volume',type=int,default=30)
a=p.parse_args()
with VoiceBackend() as v:
    if a.list:print(json.dumps({'choices':v.selections(),'fixed_scenes':v.fixed_scenes()},ensure_ascii=False,indent=2))
    elif a.fixed:v.play_fixed(a.fixed,a.volume);input('按回车结束播放')
    elif a.text:
        r=v.synthesize(a.text,gpt_id='voice_'+a.gpt,sovits_id='voice_'+a.sovits,reference_id=a.reference);print(json.dumps(r,ensure_ascii=False))
        if a.play:v.play_file(r['path'],a.volume);input('按回车结束播放')
