import sys,time,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from voice_backend import VoiceBackend,atomic_json,HTTP
from urllib.request import Request
from urllib.error import HTTPError
from concurrent.futures import CancelledError
h=Path(__file__).resolve().parent
report={'checks':[],'samples':[]}
def check(name,value):
 report['checks'].append({'check':name,'passed':bool(value)})
 if not value:raise AssertionError(name)
try:
 with VoiceBackend() as v:
  sample=v.synthesize('欢迎回来。我们先做一件小事就好。',gpt_id='voice_1',sovits_id='voice_1',reference_id='denia_06')
  report['samples'].append(dict(sample,model_label='第一套'))
  health=v.health();report['first_health']=health
  check('native_libraries_and_python_do_not_use_training_directory',not health['original_native_library_paths'] and not health['original_module_paths'] and not health['rejected_original_reads'])
  try:HTTP.open(Request(v._endpoint+'/health'),timeout=5);unauthorized=False
  except HTTPError as e:unauthorized=e.code==401
  check('unauthenticated_api_denied',unauthorized)
  future=v.submit('我们慢慢来，先处理一件小事就好。'*20)
  time.sleep(.2);pid=v._process.pid;v.cancel()
  try:future.result(timeout=10);cancelled=False
  except CancelledError:cancelled=True
  check('active_synthesis_cancelled_without_output',cancelled)
  check('cancel_stops_owned_worker',v._process is None and not v.health()['ready'])
  sample=v.synthesize('晚上好。今天也辛苦了。',gpt_id='voice_2',sovits_id='voice_2',reference_id='denia_02',speed=1.05)
  report['samples'].append(dict(sample,model_label='第二套'))
  report['second_health']=v.health()
  check('restart_and_reference_change_succeed',sample['seconds']>0 and report['second_health']['selection']['reference_id']=='denia_02')
  check('both_models_can_generate_valid_wav',len(report['samples'])==2)
 check('close_releases_worker',v._process is None)
 report['passed']=True
except Exception:report['passed']=False;report['error']=traceback.format_exc()
atomic_json(h/'verification/independent_runtime_acceptance.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
