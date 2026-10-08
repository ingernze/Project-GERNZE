"""Pinned offline module packages. No download, pip, account access or data deletion."""
from pathlib import Path, PurePosixPath
import hashlib, importlib, json, os, shutil, stat, sys, tempfile, threading, zipfile

IDS = {'cet6': '中国英语六级学习', 'fixed_voice': '固定场景语音', 'voice_engine': '本地文字转语音'}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('模块包含不安全的路径')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') or x.endswith((' ', '.')) for x in name.split('/')):
        raise ValueError('模块包含不安全的路径')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{x}{n}' for x in ('COM', 'LPT') for n in range(1, 10)}
    if any(x.split('.')[0].upper() in reserved for x in p.parts): raise ValueError('模块包含保留文件名')
    return p

class OptionalModules:
    def __init__(self, resource_root, data_dir, *, install_root=None):
        self.resources = Path(resource_root).resolve()
        self.data = Path(data_dir).resolve()
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else self.resources
        self.root = Path(install_root or base / '可选模块').resolve()
        self.retained = self.data / 'module_retained'
        catalog_path = self.resources / 'module_catalog.json'
        self.managed = catalog_path.is_file()
        self.catalog = json.loads(catalog_path.read_text(encoding='utf8')) if self.managed else {}
        if self.managed and (self.catalog.get('schema_version') != 1 or set(self.catalog.get('modules', {})) != set(IDS)):
            raise ValueError('模块目录版本不兼容')
        self._lock = threading.RLock()

    def folder(self, identity):
        if identity not in IDS: raise ValueError('未知模块')
        path = (self.root / identity).resolve()
        if path.parent != self.root: raise ValueError('模块目录不安全')
        return path

    def installed(self, identity):
        if not self.managed: return True
        if not self.catalog['modules'][identity].get('available',True): return False
        try:
            receipt = json.loads((self.folder(identity) / '.installed.json').read_text(encoding='utf8'))
            expected = self.catalog['modules'][identity]
            return receipt == {'id': identity, 'version': expected['version'], 'catalog_hash': self.catalog_hash(identity)}
        except (OSError, ValueError): return False

    def catalog_hash(self, identity):
        return hashlib.sha256(json.dumps(self.catalog['modules'][identity], sort_keys=True).encode()).hexdigest()

    def snapshot(self):
        return {'managed': self.managed, 'items': [
            {'id': key, 'title': title, 'installed': self.installed(key),
             'bytes': self.catalog.get('modules', {}).get(key, {}).get('bytes', 0)} for key, title in IDS.items()]}

    def activate_study(self):
        if not self.installed('cet6'): raise ValueError('请先安装中国英语六级学习模块；原有记录仍然保留。')
        if self.managed:
            folder = self.folder('cet6')
            for name, info in self.catalog['modules']['cet6']['files'].items():
                if digest(folder / name) != info['sha256']: raise ValueError('学习模块文件已变化，请重新安装。')
            import hebao_modules
            path = str(folder / 'python' / 'hebao_modules')
            if path not in hebao_modules.__path__: hebao_modules.__path__.append(path)
            importlib.invalidate_caches()

    def fixed_home(self):
        if not self.managed: return self.resources / 'assets' / 'voice'
        return self.folder('fixed_voice') / 'voice' if self.installed('fixed_voice') else self.resources / '_voice_not_installed'

    def voice_home(self):
        if not self.installed('voice_engine'): raise FileNotFoundError('本地文字转语音模块尚未安装，请到模块中心安装。')
        return self.folder('voice_engine')

    def install(self, archive):
        if not self.managed: raise ValueError('当前是兼容版，请使用独立模块候选启动版。')
        with self._lock, zipfile.ZipFile(archive) as z:
            if len(z.infolist()) > 80000: raise ValueError('模块文件数量异常')
            names = [x.filename for x in z.infolist()]
            if len(names) != len(set(n.casefold() for n in names)): raise ValueError('模块包含重复路径')
            for item in z.infolist():
                safe_name(item.filename)
                if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError('模块包含不支持的条目')
            if 'module.json' not in names or z.getinfo('module.json').file_size > 4096: raise ValueError('缺少模块说明')
            meta = json.loads(z.read('module.json').decode('utf8'))
            identity = meta.get('id')
            if identity not in IDS: raise ValueError('未知模块')
            spec = self.catalog['modules'][identity]
            if not spec.get('available',True): raise ValueError('此启动版尚未提供该模块，请使用配套发布包。')
            if meta != {'schema_version': 1, 'id': identity, 'version': spec['version']}:
                raise ValueError('模块版本与当前启动版不匹配')
            expected = spec['files']
            if set(names) != {'module.json'} | {'payload/' + n for n in expected}: raise ValueError('模块文件清单不匹配')
            for name, info in expected.items():
                safe_name(name)
                if z.getinfo('payload/' + name).file_size != info['size']: raise ValueError('模块文件大小不匹配')
            target = self.folder(identity)
            self.root.mkdir(parents=True, exist_ok=True)
            prior = self.root / ('.previous-' + identity)
            if prior.exists(): raise ValueError('上一次安装尚未恢复，请保留文件并联系维护者。')
            staging = Path(tempfile.mkdtemp(prefix='.install-', dir=self.root)).resolve()
            swapped = False
            try:
                for name, info in expected.items():
                    output = staging / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    h = hashlib.sha256()
                    with z.open('payload/' + name) as src, output.open('wb') as dst:
                        for block in iter(lambda: src.read(1024 * 1024), b''):
                            h.update(block); dst.write(block)
                    if h.hexdigest() != info['sha256']: raise ValueError('模块校验失败，未替换现有模块')
                if target.exists(): self._preserve(identity, target)
                self._restore(identity, staging)
                (staging / '.installed.json').write_text(json.dumps({'id': identity, 'version': spec['version'], 'catalog_hash': self.catalog_hash(identity)}), encoding='utf8')
                if target.exists(): target.rename(prior)
                try: staging.rename(target); swapped = True
                except BaseException:
                    if prior.exists(): prior.rename(target)
                    raise
                if prior.exists(): shutil.rmtree(prior)
                return {'id': identity, 'installed': True}
            finally:
                if not swapped and staging.exists(): shutil.rmtree(staging)

    def _preserve(self, identity, folder):
        expected = self.catalog['modules'][identity]['files']
        # Keep imported weights, references, outputs, settings and any user-modified file.
        for path in folder.rglob('*'):
            if path.is_symlink() or path.is_junction(): raise ValueError('模块目录包含链接，未移除')
            if not path.is_file() or path.name == '.installed.json': continue
            name = path.relative_to(folder).as_posix()
            info = expected.get(name)
            if info is None or path.stat().st_size != info['size'] or digest(path) != info['sha256']:
                out = self.retained / identity / name
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, out)

    def _restore(self, identity, staging):
        # Restore data only, never executable code from a changed/unrecognized installation.
        saved = self.retained / identity
        if identity != 'voice_engine' or not saved.exists(): return
        for name in ('models', 'references', 'state'):
            folder = saved / name
            if folder.is_dir(): shutil.copytree(folder, staging / name, dirs_exist_ok=True)
        if (saved / 'catalog.json').is_file(): shutil.copy2(saved / 'catalog.json', staging / 'catalog.json')

    def uninstall(self, identity):
        if not self.managed: raise ValueError('兼容版资源不由此入口移除。')
        with self._lock:
            folder = self.folder(identity)
            if folder.exists():
                self._preserve(identity, folder)
                shutil.rmtree(folder)
            return {'id': identity, 'installed': False, 'personal_data_preserved': True}

def manager(resource_root, data_dir):
    return OptionalModules(resource_root, data_dir)
