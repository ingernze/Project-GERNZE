"""Hecate local inference worker. No training, downloads or external API requests."""
import os, sys, json, io, socket, threading, traceback, hashlib, contextlib, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hmac import compare_digest

HOME=Path(__file__).resolve().parent
STATE=HOME/'state';STATE.mkdir(exist_ok=True)
ENGINE=HOME/'engine'
os.chdir(ENGINE)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',GRADIO_ANALYTICS_ENABLED='false',PYTHONDONTWRITEBYTECODE='1',version='v2Pro',language='zh_CN',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',NUMBA_CACHE_DIR=str(STATE/'numba'),NLTK_DATA=str(HOME/'runtime'/'nltk_data'),TORCH_HOME=str(STATE/'torch'))
os.environ['PATH']=str(HOME/'runtime')+os.pathsep+os.environ.get('PATH','')
sys.path[:0]=[str(ENGINE),str(ENGINE/'GPT_SoVITS'),str(ENGINE/'GPT_SoVITS'/'BigVGAN'),str(ENGINE/'tools'),str(ENGINE/'GPT_SoVITS'/'eres2net')]
# Refuse access to the original training installation, even if a hidden absolute
# path survives in an imported package. Shared runtime files are immutable.
rejected=[]
def audit(event,args):
 if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)): return
 p=os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
 if p.startswith(os.path.normcase('D:/ai/')+os.sep) or p.startswith(os.path.normcase('D:/ai/')):
  rejected.append(p);raise PermissionError('Original training directory is unavailable to this worker')
 mode=args[1] if len(args)>1 else None
 if isinstance(mode,str) and any(c in mode for c in 'wax+') and p.startswith(os.path.normcase(str(HOME/'runtime'))+os.sep):
  raise PermissionError('Bundled inference runtime is immutable')
sys.addaudithook(audit)
original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex
def local_connect(self,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'): raise PermissionError('Inference worker cannot access the internet')
 return original_connect(self,address)
def local_connect_ex(self,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'): return 10013
 return original_connect_ex(self,address)
socket.socket.connect=local_connect;socket.socket.connect_ex=local_connect_ex
# Only one worker may occupy the GPU for this voice module.
import msvcrt
worker_lock=open(STATE/'engine.lock','a+b');worker_lock.seek(0);worker_lock.write(b'0');worker_lock.flush();worker_lock.seek(0)
msvcrt.locking(worker_lock.fileno(),msvcrt.LK_NBLCK,1)
CATALOG=json.loads((HOME/'catalog.json').read_text(encoding='utf8'))
def item(group,identity):
 for entry in CATALOG[group]:
  if entry['id']==identity: return entry
 raise ValueError('Unknown selection')
verified=set()
def path_for(entry):
 p=(HOME/entry['path']).resolve()
 if HOME not in p.parents: raise ValueError('Asset path must stay within voice module')
 if p not in verified:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
  if h.hexdigest()!=entry['sha256']:raise ValueError('Asset checksum mismatch')
  verified.add(p)
 return str(p)
import torch
import soundfile as sf
import numpy as np
import yaml
import utils
if hasattr(torch.serialization,'add_safe_globals'):torch.serialization.add_safe_globals([utils.HParams])
old_load=torch.load
def safe_load(*args,**kwargs):
 kwargs['weights_only']=True
 return old_load(*args,**kwargs)
torch.load=safe_load
torch.set_num_threads(2)
if not torch.cuda.is_available():raise RuntimeError('GPU runtime unavailable; worker will not silently change to CPU')
torch.cuda.set_per_process_memory_fraction(.75,0)
import text.g2pw as g2pw
original_g2pw=g2pw.G2PWPinyin.__init__
def local_g2pw(self,*args,**kwargs):
 kwargs['model_dir']=str(ENGINE/'GPT_SoVITS'/'text'/'G2PWModel')
 kwargs['model_source']=str(ENGINE/'GPT_SoVITS'/'pretrained_models'/'chinese-roberta-wwm-ext-large')
 return original_g2pw(self,*args,**kwargs)
g2pw.G2PWPinyin.__init__=local_g2pw
import sv
sv.sv_path=str(ENGINE/'GPT_SoVITS'/'pretrained_models'/'sv'/'pretrained_eres2netv2w24s4ep4.ckpt')
from TTS_infer_pack.TTS import TTS,TTS_Config
selection=dict(CATALOG['defaults'])
config_path=STATE/'tts_infer.yaml'
initial_version=item('sovits_options',selection['sovits_id'])['version']
if initial_version not in ('v2Pro','v2ProPlus'):raise ValueError('Only V2 Pro-series full models are supported')
custom={'device':'cuda','is_half':True,'version':initial_version,'t2s_weights_path':path_for(item('gpt_options',selection['gpt_id'])),'vits_weights_path':path_for(item('sovits_options',selection['sovits_id'])),'bert_base_path':str(ENGINE/'GPT_SoVITS'/'pretrained_models'/'chinese-roberta-wwm-ext-large'),'cnhuhbert_base_path':str(ENGINE/'GPT_SoVITS'/'pretrained_models'/'chinese-hubert-base')}
config_path.write_text(yaml.safe_dump({'custom':custom},allow_unicode=True),encoding='utf8')
pipeline=TTS(TTS_Config(str(config_path)))
assert pipeline.configs.version==initial_version
mutex=threading.Lock()
TOKEN=os.environ.pop('HECATE_VOICE_TOKEN')

def diagnostics():
 import ctypes
 from ctypes import wintypes
 original_prefix=os.path.normcase(os.path.abspath('D:/ai'))+os.sep
 files=[str(getattr(m,'__file__','')) for m in tuple(sys.modules.values())]
 bad=[p for p in files if os.path.normcase(os.path.abspath(p)).startswith(original_prefix)]
 kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
 kernel.GetCurrentProcess.restype=wintypes.HANDLE
 psapi.EnumProcessModules.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.HMODULE),wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
 kernel.GetModuleFileNameW.argtypes=[wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD]
 modules=(wintypes.HMODULE*2048)();needed=wintypes.DWORD();native=[]
 if not psapi.EnumProcessModules(kernel.GetCurrentProcess(),modules,ctypes.sizeof(modules),ctypes.byref(needed)):raise RuntimeError('Native module verification failed')
 for handle in modules[:min(len(modules),needed.value//ctypes.sizeof(wintypes.HMODULE))]:
  buffer=ctypes.create_unicode_buffer(32768)
  if kernel.GetModuleFileNameW(handle,buffer,len(buffer)):native.append(buffer.value)
 bad_native=[p for p in native if os.path.normcase(os.path.abspath(p)).startswith(original_prefix)]
 return {'ready':True,'pid':os.getpid(),'selection':selection,'model_version':pipeline.configs.version,'rejected_original_reads':list(rejected),'original_module_paths':bad,'original_native_library_paths':bad_native,'native_library_count':len(native),'home':str(HOME)}

def synthesize(body):
 text_value=body.get('text','')
 if not isinstance(text_value,str) or not text_value.strip() or len(text_value)>500:raise ValueError('Text must contain 1 to 500 characters')
 allowed={'text','gpt_id','sovits_id','reference_id','speed','seed','temperature','top_p'}
 if set(body)-allowed:raise ValueError('Unknown synthesis field')
 target={k:body.get(k,CATALOG['defaults'][k]) for k in ('gpt_id','sovits_id','reference_id')}
 g=item('gpt_options',target['gpt_id']);s=item('sovits_options',target['sovits_id']);r=item('references',target['reference_id'])
 if g['version']!=s['version']:raise ValueError('GPT and SoVITS versions differ')
 gp,sp,rp=path_for(g),path_for(s),path_for(r)
 speed=float(body.get('speed',1));temp=float(body.get('temperature',1));top_p=float(body.get('top_p',1));seed=int(body.get('seed',20261006))
 if not .7<=speed<=1.3 or not .5<=temp<=1.5 or not .1<=top_p<=1 or not 0<=seed<=2147483647:raise ValueError('Sampling parameters outside supported range')
 # The official pipeline logs the full text. Keep private user text out of worker logs.
 with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink):
  if target['sovits_id']!=selection['sovits_id']:pipeline.init_vits_weights(sp)
  if target['gpt_id']!=selection['gpt_id']:pipeline.init_t2s_weights(gp)
  selection.update(target)
  request={'text':text_value,'text_lang':'all_zh','ref_audio_path':rp,'aux_ref_audio_paths':[rp],'prompt_lang':r['language'],'prompt_text':r['text'],'top_k':15,'top_p':top_p,'temperature':temp,'text_split_method':'cut5','batch_size':1,'speed_factor':speed,'seed':seed,'parallel_infer':True,'repetition_penalty':1.35,'return_fragment':False,'super_sampling':False,'fragment_interval':.3}
  parts=list(pipeline.run(request))
 if not parts:raise RuntimeError('No audio returned')
 sr=parts[0][0]
 if any(x[0]!=sr for x in parts):raise RuntimeError('Sample rate changed during synthesis')
 samples=np.concatenate([x[1] for x in parts])
 if samples.ndim!=1 or not np.isfinite(samples).all() or not len(samples):raise RuntimeError('Invalid audio')
 output=io.BytesIO();sf.write(output,samples,sr,format='WAV',subtype='PCM_16')
 return output.getvalue()

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send_payload(self,status,data,kind='application/json'):
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def authorized(self):
  value=self.headers.get('Authorization','')
  return compare_digest(value,'Bearer '+TOKEN)
 def do_GET(self):
  if not self.authorized():self.send_payload(401,b'{"error":"unauthorized"}');return
  if self.path!='/health':self.send_payload(404,b'{}');return
  self.send_payload(200,json.dumps(diagnostics(),ensure_ascii=False).encode('utf8'))
 def do_POST(self):
  if not self.authorized():self.send_payload(401,b'{"error":"unauthorized"}');return
  if self.path!='/tts':self.send_payload(404,b'{}');return
  try:n=int(self.headers.get('Content-Length','0'))
  except ValueError:n=0
  if not 1<=n<=16384:self.send_payload(400,b'{"error":"body_size"}');return
  if not mutex.acquire(False):self.send_payload(409,b'{"error":"busy"}');return
  try:
   body=json.loads(self.rfile.read(n).decode('utf8'))
   if not isinstance(body,dict):raise ValueError('Object expected')
   audio=synthesize(body)
   self.send_payload(200,audio,'audio/wav')
  except ValueError:
   self.send_payload(400,b'{"error":"invalid_request_or_asset"}')
  except Exception as e:
   traceback.print_exc()
   self.send_payload(500,b'{"error":"inference_failed_restart_required"}')
   # A failed weight switch may leave partial state. Exit, never reuse it.
   threading.Timer(.5,lambda:os._exit(2)).start()
  finally:mutex.release()

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
ready=STATE/(os.environ.pop('HECATE_VOICE_READY')+'.json')
ready.write_text(json.dumps(dict(diagnostics(),port=server.server_port),ensure_ascii=False),encoding='utf8')
server.serve_forever()
