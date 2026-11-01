"""Export an explicitly reviewed source snapshot, without user data."""
import argparse,hashlib,json,zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

def checked_source(root,name):
    if not isinstance(name,str) or not name or '\\' in name:
        raise ValueError('Invalid source path')
    rel=PurePosixPath(name)
    if rel.is_absolute() or PureWindowsPath(name).drive or any(part in ('','..','.') for part in name.split('/')):
        raise ValueError('Source path must be canonical and relative: '+name)
    original=root.joinpath(*rel.parts)
    for part in (original,*original.parents):
        if part==root:break
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('Linked source path: '+name)
    source=original.resolve()
    if not source.is_relative_to(root) or not source.is_file():raise ValueError('Invalid source path: '+name)
    return source

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if out==root or root.is_relative_to(out):raise ValueError('Output must not contain the project')
    archive=out.with_suffix('.zip')
    report=out.parent/(out.name+'_files.json')
    if archive.exists() or report.exists():raise ValueError('Archive or report exists')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('Output directory must be empty')
    names=json.loads((root/'source-files.json').read_text(encoding='utf8'))['files']
    if not isinstance(names,list) or not all(isinstance(n,str) for n in names) or len(names)!=len(set(names)) or len(names)!=len(set(n.casefold() for n in names)):
        raise ValueError('Duplicate or invalid source names')
    sources=[(name,checked_source(root,name)) for name in names]
    out.mkdir(parents=True,exist_ok=True);rows=[]
    for name,source in sources:
        raw=source.read_bytes();target=out/name
        if not target.resolve().is_relative_to(out):raise ValueError('Output path outside export')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        if target.read_bytes()!=raw:raise ValueError('Export mismatch: '+name)
        rows.append({'file':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    report.write_text(json.dumps({'files':rows,'bytes':sum(r['bytes'] for r in rows)},ensure_ascii=False,indent=2),encoding='utf8')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for row in rows:z.write(out/row['file'],row['file'])
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP damaged')
        if z.namelist()!=names or any(hashlib.sha256(z.read(row['file'])).hexdigest()!=row['sha256'] for row in rows):
            raise ValueError('ZIP content mismatch')
    print(json.dumps({'files':len(rows),'source_bytes':sum(r['bytes'] for r in rows),'zip_bytes':archive.stat().st_size}))

if __name__=='__main__':main()
