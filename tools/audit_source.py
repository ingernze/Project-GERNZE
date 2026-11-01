"""Read-only source/export audit. Never stages, deletes, or scans file contents for secrets."""
import argparse,hashlib,json,subprocess,tempfile,zipfile
from pathlib import Path,PurePosixPath,PureWindowsPath
from shutil import copyfile

from export_source import checked_source


EXCLUDED_PROBES=(
 'src/workbench/companion_persona.md','src/workbench/companion_core_memory.json',
 'agent-bridge/settings.local.json','mobile/www/chat-persona.txt',
 'mobile/www/chat-core-memory.json','local-notes/private-note.md',
 '启动版/private-build.zip','mobile/update-publisher/private-releases/private.apk',
 'src/.env','src/__pycache__/cache.pyc','mobile/android/app/build/output.apk',
 'mobile/www/SYNTHETIC_PRIVATE_SENTINEL.txt',
)


def canonical(name):
    return (isinstance(name,str) and bool(name) and '\\' not in name and
            not PurePosixPath(name).is_absolute() and not PureWindowsPath(name).drive and
            all(part not in ('','.', '..') for part in name.split('/')))


def ignore_matches(root,names):
    # Isolate the reviewed project .gitignore from personal/global Git rules.
    with tempfile.TemporaryDirectory(prefix='source-ignore-audit-') as temp:
        temp=Path(temp);copyfile(root/'.gitignore',temp/'.gitignore')
        subprocess.run(['git','init','-q',str(temp)],check=True,capture_output=True)
        proc=subprocess.run(['git','-C',str(temp),'-c','core.excludesFile=',
                             'check-ignore','--no-index','-v','-n','-z','--stdin'],
                            input=b''.join(x.encode('utf-8')+b'\0' for x in names),capture_output=True)
        if proc.returncode not in (0,1):raise RuntimeError('git check-ignore could not inspect rules')
        parts=proc.stdout.split(b'\0')
        if parts[-1]!=b'':raise RuntimeError('Invalid git check-ignore output')
        rows=[tuple(x.decode('utf-8') for x in parts[i:i+4]) for i in range(0,len(parts)-1,4)]
        if len(rows)!=len(names) or [r[3] for r in rows]!=names:
            raise RuntimeError('Incomplete git check-ignore results')
        return {r[3]:bool(r[2]) and not r[2].startswith('!') for r in rows}


def audit(root,snapshot=None,inventory=None,archive=None):
    root=Path(root).resolve();issues=[]
    names=json.loads((root/'source-files.json').read_text(encoding='utf-8'))['files']
    if not isinstance(names,list):raise ValueError('Manifest files must be a list')
    if any(not canonical(n) for n in names):issues.append('noncanonical or invalid path')
    if len(names)!=len(set(n for n in names if isinstance(n,str))):issues.append('duplicate path')
    if len(names)!=len(set(n.casefold() for n in names if isinstance(n,str))):issues.append('case-fold collision')
    clean=[n for n in names if canonical(n)]
    if '.gitignore' not in clean:issues.append('.gitignore not allowlisted')
    omissions={x['path']:x for x in snapshot.get('omitted',[])} if snapshot else {}
    expected={x['path']:x for x in inventory} if inventory else {}
    if inventory and [x['path'] for x in inventory]!=names:issues.append('inventory manifest order mismatch')
    included=0;missing=[];hash_mismatch=[]
    for name in clean:
        try:path=checked_source(root,name)
        except ValueError:
            missing.append(name)
            if name not in omissions:issues.append('missing/linked source: '+name)
            continue
        included+=1
        if name in omissions:issues.append('omission is actually present: '+name)
        if name in expected:
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=expected[name]['sha256'] or len(raw)!=expected[name]['bytes']:
                hash_mismatch.append(name);issues.append('source hash mismatch: '+name)
    if len(set(missing))!=len(omissions) or set(missing)!=set(omissions):
        issues.append('snapshot omission mismatch') if snapshot else None
    if snapshot and snapshot.get('allowlisted_count')!=len(names):issues.append('snapshot allowlist count mismatch')
    # This probes semantics, not just list membership. Nothing reads private files.
    probes=clean+list(EXCLUDED_PROBES)
    matrix=ignore_matches(root,probes)
    for name in clean:
        if matrix[name]:issues.append('allowlisted path ignored: '+name)
    for name in EXCLUDED_PROBES:
        if name in clean or not matrix[name]:issues.append('private/build probe unignored: '+name)
    tracked_status='not_checked_no_git_index';outside=[]
    if (root/'.git').exists():
        proc=subprocess.run(['git','-C',str(root),'ls-files','-z'],capture_output=True)
        if proc.returncode:issues.append('git tracked index unavailable')
        else:
            tracked_status='checked'
            outside=sorted(set(proc.stdout.decode('utf-8').split('\0')[:-1])-set(clean))
            if outside:issues.append('tracked outside allowlist: '+str(len(outside)))
    export_status='not_provided'
    if archive:
        if missing:issues.append('cannot verify export with missing sources')
        else:
            try:
                with zipfile.ZipFile(archive) as z:
                    if z.testzip() is not None or z.namelist()!=names:issues.append('export ZIP names/order/CRC mismatch')
                    for name in clean:
                        if hashlib.sha256(z.read(name)).hexdigest()!=hashlib.sha256((root/name).read_bytes()).hexdigest():
                            issues.append('export hash mismatch: '+name)
                export_status='checked'
            except (OSError,KeyError,zipfile.BadZipFile):issues.append('invalid export ZIP')
    return {'ok':not issues,'issues':issues,'allowlistCount':len(names),'present':included,
            'knownOmitted':len(omissions),'missing':missing,'hashMismatch':hash_mismatch,
            'allowlistedIgnored':sum(matrix[n] for n in clean),
            'excludedProbesIgnored':sum(matrix[n] for n in EXCLUDED_PROBES),
            'excludedProbeCount':len(EXCLUDED_PROBES),'trackedIndex':tracked_status,
            'trackedOutsideAllowlist':outside,'exportArchive':export_status,
            'scope':'manifest paths and fixed synthetic exclusion paths only; no secret scan'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--inventory',type=Path)
    parser.add_argument('--export-archive',type=Path)
    args=parser.parse_args()
    result=audit(args.root,json.loads(args.snapshot.read_text(encoding='utf-8')) if args.snapshot else None,
                 json.loads(args.inventory.read_text(encoding='utf-8')) if args.inventory else None,args.export_archive)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['ok'] else 1)


if __name__=='__main__':main()
