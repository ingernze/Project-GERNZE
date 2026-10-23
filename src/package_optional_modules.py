"""Build matched, offline Hecate packages; never download or include personal data."""
from pathlib import Path
import argparse, hashlib, json, zipfile

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--voice-home', type=Path)
    parser.add_argument('--version', default='20261007.1')
    args = parser.parse_args()
    src, out = args.source.resolve(), args.output.resolve()
    if out == src or out in src.parents: raise ValueError('Use a separate output directory')
    out.mkdir(parents=True, exist_ok=True)
    catalog = {'schema_version': 1, 'modules': {}}
    summary = {}
    def build(identity, files):
        archive = out / (identity + '.zip'); entries = {}; total = 0
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as z:
            z.writestr('module.json', json.dumps({'schema_version': 1, 'id': identity, 'version': args.version}))
            for name, payload in sorted(files.items()):
                if isinstance(payload, bytes):
                    size = len(payload); sha = hashlib.sha256(payload).hexdigest(); z.writestr('payload/' + name, payload)
                else:
                    size = payload.stat().st_size; sha = digest(payload); z.write(payload, 'payload/' + name)
                entries[name] = {'size': size, 'sha256': sha}; total += size
        catalog['modules'][identity] = {'version': args.version, 'files': entries, 'bytes': total}
        summary[identity] = {'files': len(entries), 'uncompressed_bytes': total, 'zip_bytes': archive.stat().st_size, 'sha256': digest(archive)}
        print(identity, summary[identity], flush=True)
    build('cet6', {'python/libao_modules/' + n: src / 'libao_modules' / n for n in ('daily_study.py', 'handoff.py', 'prompts.py')})
    voice_assets = src / 'assets' / 'voice'
    if not (voice_assets / 'manifest.json').is_file():
        raise FileNotFoundError('骨架缺少固定录音清单：' + str(voice_assets))
    core_files = [p for p in voice_assets.rglob('*') if p.is_file() and p.suffix.lower() in ('.json', '.wav')]
    summary['core_fixed_voice'] = {'bundled_with_base': True, 'files': len(core_files),
                                   'uncompressed_bytes': sum(p.stat().st_size for p in core_files)}
    if args.voice_home:
        home = args.voice_home.resolve(); files = {}
        for folder in ('runtime', 'engine'):
            if not (home / folder).is_dir(): raise FileNotFoundError(home / folder)
            for p in (home / folder).rglob('*'):
                if p.is_symlink() or p.is_junction(): raise ValueError('Voice runtime must not contain links')
                if p.is_file() and '__pycache__' not in p.parts and '.git' not in p.parts and p.suffix.lower() not in ('.pyc', '.pyo'):
                    files[p.relative_to(home).as_posix()] = p
        for name in ('voice_backend.py', 'engine_worker.py', 'voice_cli.py', 'model_importer.py', '导入声音.cmd', '00_导入声音与精简说明.md', 'README_独立语音后端.md'):
            files[name] = home / name
        files['catalog.json'] = json.dumps({'schema_version': 1, 'gpt_options': [], 'sovits_options': [], 'references': [], 'defaults': {}, 'fixed_library': 'fixed_scenes', 'default_volume_percent': 30}, ensure_ascii=False, indent=2).encode()
        files['fixed_scenes/manifest.json'] = b'{"records": []}'
        profile = json.loads((home / 'inference_profile.json').read_text(encoding='utf8'))
        profile.pop('rollback_directory', None)
        files['inference_profile.json'] = json.dumps(profile, ensure_ascii=False, indent=2).encode()
        build('voice_engine', files)
    else:
        catalog['modules']['voice_engine'] = {'version': args.version, 'files': {}, 'bytes': 0, 'available': False}
    (out / 'module_catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf8')
    (out / '模块清单.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')

if __name__ == '__main__': main()
