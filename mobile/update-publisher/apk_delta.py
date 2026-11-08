"""Reuse exact compressed APK regions. Never unzip or recompress on the phone."""
import hashlib
import json
from pathlib import Path
import re
import struct
import threading
import zipfile

MAGIC = b'GZDELTA1'
HEADER = struct.Struct('>8sQ32sQ32sI')
MAX_SIZE = 536870912
MAX_OPS = 8192
CONTENT_TYPE = 'application/vnd.gernze.apk-delta-v1'


def digest_file(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def signature(path):
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def region_hash(source, start, size):
    source.seek(start)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        block = source.read(min(65536, remaining))
        if not block:
            raise ValueError('truncated APK')
        digest.update(block)
        remaining -= len(block)
    return digest.digest()


def entries(path):
    result = {}
    with zipfile.ZipFile(path) as archive, path.open('rb') as source:
        for item in archive.infolist():
            if item.filename in result:
                raise ValueError('duplicate entry')
            source.seek(item.header_offset)
            header = source.read(30)
            if len(header) != 30 or header[:4] != b'PK\x03\x04':
                raise ValueError('invalid ZIP')
            name_size, extra_size = struct.unpack_from('<HH', header, 26)
            start = item.header_offset + 30 + name_size + extra_size
            if start < 0 or start + item.compress_size > path.stat().st_size:
                raise ValueError('invalid entry region')
            result[item.filename] = (start, item.compress_size, item.CRC, item.file_size, item.compress_type)
    return result


class Plan:
    def __init__(self, base, target, expected_base=None, expected_target=None):
        self.base, self.target = Path(base), Path(target)
        self.base_size = self.base.stat().st_size
        self.target_size = self.target.stat().st_size
        if not 0 < self.base_size <= MAX_SIZE or not 0 < self.target_size <= MAX_SIZE:
            raise ValueError('size limit')
        self.base_signature = signature(self.base)
        self.target_signature = signature(self.target)
        self.base_hash = digest_file(self.base)
        self.target_hash = digest_file(self.target)
        if expected_base and self.base_hash != expected_base:
            raise ValueError('base hash mismatch')
        if expected_target and self.target_hash != expected_target:
            raise ValueError('target hash mismatch')
        old, new = entries(self.base), entries(self.target)
        matched = []
        with self.base.open('rb') as a, self.target.open('rb') as b:
            for name, current in new.items():
                previous = old.get(name)
                if current[1] < 4096 or previous is None or previous[1:] != current[1:]:
                    continue
                if region_hash(a, previous[0], previous[1]) == region_hash(b, current[0], current[1]):
                    matched.append((current[0], current[1], previous[0]))
        self.operations = []
        cursor = 0
        for start, size, old_start in sorted(matched):
            if start < cursor:
                raise ValueError('overlapping entry data')
            if start > cursor:
                self.operations.append((1, cursor, start - cursor))
            self.operations.append((0, old_start, size))
            cursor = start + size
        if cursor < self.target_size:
            self.operations.append((1, cursor, self.target_size - cursor))
        if not self.operations or len(self.operations) > MAX_OPS:
            raise ValueError('operation limit')
        self.wire_size = HEADER.size + sum(17 if kind == 0 else 9 + size for kind, _, size in self.operations)
        self.reused = sum(size for kind, _, size in self.operations if kind == 0)
        if signature(self.base) != self.base_signature or signature(self.target) != self.target_signature:
            raise ValueError('APK changed during planning')

    def blocks(self, check=lambda: None):
        check()
        if signature(self.base) != self.base_signature or signature(self.target) != self.target_signature:
            raise ValueError('APK changed')
        yield HEADER.pack(MAGIC, self.base_size, bytes.fromhex(self.base_hash),
                          self.target_size, bytes.fromhex(self.target_hash), len(self.operations))
        with self.target.open('rb') as source:
            for kind, start, size in self.operations:
                check()
                if kind == 0:
                    yield struct.pack('>BQQ', 0, start, size)
                else:
                    yield struct.pack('>BQ', 1, size)
                    source.seek(start)
                    remaining = size
                    while remaining:
                        check()
                        if signature(self.target) != self.target_signature:
                            raise ValueError('target changed')
                        block = source.read(min(remaining, 65536))
                        if not block:
                            raise ValueError('truncated target')
                        remaining -= len(block)
                        yield block


class DeltaSource:
    """Only frozen, bounded same-app releases in the publisher's private folder."""
    def __init__(self, target, release):
        self.target = Path(target)
        self.release = release
        self.lock = threading.Lock()
        self.cached = None

    def prepare(self, request):
        if type(request) is not dict or set(request) != {'artifactId', 'baseSha256', 'baseSize'}:
            raise ValueError('invalid delta request')
        if request['artifactId'] != self.release['artifactId']:
            raise ValueError('wrong artifact')
        base_hash = request['baseSha256']
        size = request['baseSize']
        if type(base_hash) is not str or not re.fullmatch('[0-9a-f]{64}', base_hash):
            raise ValueError('invalid hash')
        if type(size) is not int or not 0 < size <= MAX_SIZE:
            raise ValueError('invalid size')
        with self.lock:
            if self.cached and self.cached.base_hash == base_hash and self.cached.base_size == size:
                plan = self.cached
                if signature(plan.base) == plan.base_signature and signature(plan.target) == plan.target_signature:
                    return plan
                self.cached = None
            for metadata in list(self.target.parent.glob('*.json'))[:16]:
                if metadata.is_symlink() or metadata.stat().st_size > 16384:
                    continue
                try:
                    info = json.loads(metadata.read_text('utf-8'))
                    base = metadata.with_suffix('.apk')
                    if base.is_symlink() or not base.is_file():
                        continue
                    if (info.get('sha256') != base_hash or info.get('size') != size
                            or info.get('packageName') != self.release['packageName']
                            or info.get('signerCertificateSha256') != self.release['signerCertificateSha256']
                            or type(info.get('versionCode')) is not int
                            or info['versionCode'] >= self.release['versionCode']):
                        continue
                    plan = Plan(base, self.target, base_hash, self.release['sha256'])
                    if plan.wire_size >= self.release['size'] * 0.9:
                        return None
                    self.cached = plan
                    return plan
                except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                    continue
            return None


def retain_release_ids(folder, current):
    """Keep current plus at most two useful upgrade bases, bounded disk use."""
    keep = {current}
    candidates = []
    for path in folder.glob('*.json'):
        try:
            if path.is_symlink() or path.stat().st_size > 16384:
                continue
            value = json.loads(path.read_text('utf-8'))
            if type(value.get('versionCode')) is int:
                candidates.append((value['versionCode'], path.stem))
        except (OSError, ValueError):
            continue
    keep.update(ident for _, ident in sorted(candidates, reverse=True)[:3])
    return keep
