"""Import exported GPT/SoVITS voice pairs; no training, installs or downloads.
Only v2Pro/v2ProPlus full voice exports and optional WAV+transcript are accepted.
"""
from pathlib import Path
import argparse,hashlib,io,json,os,sys,uuid,wave
HOME=Path(__file__).resolve().parent
SUPPORTED={'v2Pro','v2ProPlus'}
MAX_WEIGHT_BYTES=1024*1024*1024
class ImportErrorDetail(ValueError):pass

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def plain(value):
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if hasattr(value,'items'):return {k:plain(v) for k,v in value.items()}
    return value

def load_export(path,kind,home=HOME):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or not 1<=path.stat().st_size<=MAX_WEIGHT_BYTES:
        raise ImportErrorDetail('权重不存在、是链接或体积超出1GB限制：'+path.name)
    # CPU-only structural validation; torch.load never executes arbitrary pickle code.
    sys.path[:0]=[str(home/'engine/GPT_SoVITS'),str(home/'engine')]
    import torch
    import utils
    if hasattr(torch.serialization,'add_safe_globals'):torch.serialization.add_safe_globals([utils.HParams])
    with path.open('rb') as f:header=f.read(2)
    version={b'05':'v2Pro',b'06':'v2ProPlus'}.get(header)
    if header!=b'PK':
        if kind!='sovits' or version is None:raise ImportErrorDetail('不是支持的完整导出权重：'+path.name)
        source=io.BytesIO(b'PK'+path.read_bytes()[2:])
    else:source=str(path)
    try:data=torch.load(source,map_location='cpu',weights_only=True)
    except Exception as exc:raise ImportErrorDetail('无法安全读取权重，请使用完整导出的音色文件：'+path.name) from exc
    if not isinstance(data,dict) or 'weight' not in data or 'config' not in data:
        raise ImportErrorDetail('需要导出的音色权重，不是训练中间检查点：'+path.name)
    config=plain(data['config']);weights=data['weight']
    if not isinstance(config,dict) or not isinstance(weights,dict) or not weights:
        raise ImportErrorDetail('权重结构不完整：'+path.name)
    if not all(isinstance(k,str) and torch.is_tensor(v) for k,v in weights.items()):
        raise ImportErrorDetail('权重必须是张量参数：'+path.name)
    if kind=='gpt':
        embedding=weights.get('model.ar_text_embedding.word_embeddings.weight')
        if embedding is None or embedding.shape[0]!=732 or config.get('model',{}).get('phoneme_vocab_size')!=732:
            raise ImportErrorDetail('当前只适配与V2 Pro系列兼容的GPT权重')
        version='v2'
    else:
        version=version or config.get('model',{}).get('version')
        if version not in SUPPORTED or config.get('data',{}).get('sampling_rate')!=32000:
            raise ImportErrorDetail('当前只适配32kHz的V2 Pro／V2 Pro Plus完整权重')
        if not any(k.startswith('enc_p.') for k in weights):raise ImportErrorDetail('SoVITS权重不完整')
    del weights,data
    return {'version':version,'sha256':digest(path)}

def discover(inputs):
    files=[];seen=set()
    for item in inputs:
        p=Path(item).resolve()
        if not p.exists():raise ImportErrorDetail('文件或文件夹不存在：'+str(p))
        candidates=list(p.rglob('*')) if p.is_dir() else [p]
        if len(candidates)>256:raise ImportErrorDetail('请只拖入一套音色文件，不要拖整合包或运行环境')
        for f in candidates:
            if f.is_symlink() or f.stat().st_file_attributes & 0x400:
                raise ImportErrorDetail('模型包不接受目录链接或文件链接')
            if f.is_file() and f.suffix.lower() in {'.ckpt','.pth','.wav'} and f not in seen:
                files.append(f);seen.add(f)
    groups={ext:[p for p in files if p.suffix.lower()==ext] for ext in ('.ckpt','.pth','.wav')}
    if len(groups['.ckpt'])!=1 or len(groups['.pth'])!=1:
        raise ImportErrorDetail('每次需要且只接受一个GPT .ckpt和一个SoVITS .pth；多个版本请分文件夹导入')
    if len(groups['.wav'])>1:raise ImportErrorDetail('每次最多导入一份参考WAV，请将其他录音移出此包')
    return groups['.ckpt'][0],groups['.pth'][0],groups['.wav'][0] if groups['.wav'] else None

def reference_info(path):
    with wave.open(str(path),'rb') as wav:
        seconds=wav.getnframes()/wav.getframerate()
        if wav.getcomptype()!='NONE' or wav.getsampwidth() not in (2,3,4) or wav.getnchannels() not in (1,2) or not 3<=seconds<=10:
            raise ImportErrorDetail('参考音频需为3—10秒PCM WAV（16／24／32位）')
    meta=path.parent/'reference.json'
    if meta.is_file():
        info=json.loads(meta.read_text(encoding='utf-8-sig'))
        text=info.get('text','');language=info.get('language','all_zh')
    else:
        transcript=path.with_suffix('.txt')
        if not transcript.is_file():raise ImportErrorDetail('参考WAV需要同名.txt逐字文本；不自动猜测转写')
        text=transcript.read_text(encoding='utf-8-sig').strip();language='all_zh'
    if not isinstance(text,str) or not text.strip() or len(text)>500:raise ImportErrorDetail('参考文本需要1—500字逐字转写')
    if language not in ('all_zh','all_en','all_ja'):raise ImportErrorDetail('参考语言目前只接受all_zh／all_en／all_ja')
    return {'text':text.strip(),'language':language,'sha256':digest(path)}

def install_file(source,target,expected,home):
    target=target.resolve();home=home.resolve()
    if home not in target.parents:raise ImportErrorDetail('导入目标超出语音模块目录')
    if target.exists():
        if digest(target)!=expected:raise ImportErrorDetail('已有导入文件校验不一致，保留原文件并停止')
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    pending=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with Path(source).open('rb') as reader,pending.open('xb') as writer:
            for chunk in iter(lambda:reader.read(1024*1024),b''):writer.write(chunk)
        if digest(pending)!=expected:raise ImportErrorDetail('导入复制校验失败')
        os.replace(pending,target)
    finally:pending.unlink(missing_ok=True)

def _import_voice_locked(inputs,label=None,home=HOME):
    home=Path(home).resolve()
    gpt,sovits,ref=discover(inputs)
    g=load_export(gpt,'gpt',home);s=load_export(sovits,'sovits',home)
    reference=reference_info(ref) if ref else None
    catalog_path=home/'catalog.json'
    if not catalog_path.is_file():raise ImportErrorDetail('语音模块目录不完整')
    catalog=json.loads(catalog_path.read_text(encoding='utf-8-sig'))
    label=(label or gpt.parent.name).strip()[:40]
    if not label:label='导入声音'
    result={'label':label,'version':s['version'],'reference_added':False,'already_present':True}
    assets=[]
    for group,src,info,kind,ext in [('gpt_options',gpt,g,'gpt','.ckpt'),('sovits_options',sovits,s,'sovits','.pth')]:
        existing=next((r for r in catalog[group] if r.get('sha256')==info['sha256'] and r.get('version')==s['version']),None)
        if existing:identity=existing['id']
        else:
            identity='import_'+kind+'_'+info['sha256'][:16]
            rel='models/导入声音/'+identity+ext
            assets.append((src,home/rel,info['sha256']))
            catalog[group].append({'id':identity,'label':label+'（'+s['version']+'）','path':rel,'sha256':info['sha256'],'version':s['version']})
            result['already_present']=False
        result[kind+'_id']=identity
    if reference:
        existing=next((r for r in catalog['references'] if r.get('sha256')==reference['sha256']),None)
        if existing:
            if existing['text']!=reference['text'] or existing['language']!=reference['language']:
                raise ImportErrorDetail('同一参考音频已有不同转写；保留原记录，请先核对')
            result['reference_id']=existing['id']
        else:
            identity='import_ref_'+reference['sha256'][:16];rel='references/导入参考/'+identity+'.wav'
            assets.append((ref,home/rel,reference['sha256']))
            catalog['references'].append(dict(reference,id=identity,label=label+' · 参考音频',path=rel))
            result['reference_added']=True;result['reference_id']=identity;result['already_present']=False
    else:result['reference_id']=catalog['defaults']['reference_id']
    # Check and fully write assets before registering them; defaults and current voices remain intact.
    for source,target,expected in assets:install_file(source,target,expected,home)
    if not result['already_present']:
        backup=home/'state'/'import_catalog_backups';backup.mkdir(parents=True,exist_ok=True)
        (backup/(uuid.uuid4().hex+'.json')).write_bytes(catalog_path.read_bytes())
        pending=catalog_path.with_name('catalog.'+uuid.uuid4().hex+'.tmp')
        try:
            pending.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8');os.replace(pending,catalog_path)
        finally:pending.unlink(missing_ok=True)
    result['source_files_preserved']=True
    return result

def import_voice(inputs,label=None,home=HOME):
    # Serialize catalog edits from two independently launched import windows.
    import msvcrt
    home=Path(home).resolve();state=home/'state';state.mkdir(exist_ok=True)
    with (state/'import.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise ImportErrorDetail('另一个导入正在进行，请等待它完成')
        try:return _import_voice_locked(inputs,label,home)
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def main():
    parser=argparse.ArgumentParser(description='莉宝音色导入：拖入一套GPT/SoVITS成品文件')
    parser.add_argument('paths',nargs='*');parser.add_argument('--name');args=parser.parse_args()
    inputs=args.paths
    if not inputs:
        inbox=HOME/'模型导入'
        children=[p for p in inbox.iterdir() if p.is_dir() or p.suffix.lower() in {'.ckpt','.pth','.wav'}]
        inputs=children
    if not inputs:raise ImportErrorDetail('请把一套.ckpt、.pth及可选参考WAV+同名txt放入模型导入，或把音色文件夹拖到导入声音.cmd上')
    result=import_voice(inputs,args.name)
    print('已识别：'+result['label']+' / '+result['version'])
    print('此声音已在列表中，无需重复复制。' if result['already_present'] else '导入完成。重新启动莉宝后，在文字转语音中选择新增GPT／SoVITS和参考音频。')
    if not result['reference_added']:print('参考音频沿用已有选项；使用新音色时建议准备配套参考音频和逐字文本。')
    print('原文件保留，原第一套和第二套声音不变。')
if __name__=='__main__':
    try:main()
    except Exception as exc:print('未导入：'+str(exc));sys.exit(1)
