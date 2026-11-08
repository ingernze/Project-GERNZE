"""Explicit local work-mode CLI. Not a browser/model-callable write endpoint."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from workbench.knowledge_library import KnowledgeWork

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);sub=p.add_subparsers(dest='command',required=True);sub.add_parser('list');sub.add_parser('init')
    c=sub.add_parser('collection');c.add_argument('--title',required=True);c.add_argument('--category',default='course');c.add_argument('--ident');c.add_argument('--expected-revision')
    put=sub.add_parser('put');put.add_argument('--collection-id',required=True);put.add_argument('--title',required=True);put.add_argument('--file',type=Path,required=True);put.add_argument('--origin',required=True);put.add_argument('--source-ref',required=True);put.add_argument('--ident');put.add_argument('--expected-revision');put.add_argument('--related');put.add_argument('--original-file',type=Path)
    for command in ('read','withdraw'):
        c=sub.add_parser(command);c.add_argument('--ident',required=True);c.add_argument('--revision',required=True)
    a=vars(p.parse_args());root=a.pop('workspace');command=a.pop('command');lib=KnowledgeWork(root)
    if command=='init':result=lib.initialize()
    elif command=='list':result=lib.catalog()
    elif command=='collection':result=lib.collection(**a)
    elif command=='put':
        file=a.pop('file')
        if file.suffix.lower() not in ('.md','.txt') or file.stat().st_size>32000:raise ValueError('首期正文接收UTF-8的Markdown/纯文本，单篇32000字节；其他原件先保留来源。')
        a['body']=file.read_text(encoding='utf-8-sig');result=lib.put(**a)
    elif command=='read':result=lib.read(a['ident'],a['revision'])
    else:result=lib.withdraw(a['ident'],a['revision'])
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
