"""Opt-in source workbench with a dedicated profile and credential namespace.

No migration/copy of the installed profile, automatic network call or public
server. Existing first-layer/persona source files are used read-only as usual.
"""
from contextlib import closing,contextmanager
import argparse,hashlib,json,sqlite3,threading,uuid
from pathlib import Path

FORMAT='gernze-research-preview-v1'
MARKER='research-preview.json'


def prepare_profile(value):
    path=Path(value)
    if not path.is_absolute():raise ValueError('测试资料目录必须是绝对路径。')
    for part in (path,*path.parents):
        if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('测试目录不能使用链接或联接。')
    path=path.resolve();marker=path/MARKER
    if path.exists() and not path.is_dir():raise ValueError('测试资料目录不是文件夹。')
    if marker.is_symlink():raise ValueError('测试资料标记不能是链接。')
    if marker.exists():
        if marker.stat().st_size>4096:raise ValueError('测试资料标记不受支持。')
        doc=json.loads(marker.read_text('utf-8'))
        if type(doc) is not dict or set(doc)!={'format','id'} or doc['format']!=FORMAT:raise ValueError('测试资料标记不受支持。')
        if type(doc['id']) is not str or str(uuid.UUID(doc['id']))!=doc['id']:raise ValueError('测试资料身份不受支持。')
    else:
        if path.exists() and any(path.iterdir()):raise ValueError('请选择新的空文件夹，不能把原版资料目录直接作为研究测试目录。')
        path.mkdir(parents=True,exist_ok=True);doc={'format':FORMAT,'id':str(uuid.uuid4())}
        with marker.open('x',encoding='utf-8') as stream:json.dump(doc,stream,ensure_ascii=False)
    journal=path/'workbench/chat-sessions.sqlite3'
    for child in (path/'workbench',journal,path/'workbench_browser_sessions',path/'preview.lock'):
        if child.is_symlink() or getattr(child,'is_junction',lambda:False)():raise ValueError('测试资料与窗口目录不能使用链接或联接。')
    if journal.exists():
        # Existing test journals are attached only at the current supported
        # schema. In particular, do not turn a copied ordinary v1 DB into v4.
        with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0]!=4:raise ValueError('现有测试会话版本不兼容，请保留原资料并使用新测试目录。')
            meta=dict(db.execute("SELECT key,value FROM rc_meta WHERE key IN ('schema','summary_schema','phone_summary_schema')"))
            if meta!={'schema':'2','summary_schema':'2','phone_summary_schema':'1'}:raise ValueError('现有测试研究结构不兼容，请使用新测试目录。')
    return path,doc['id']


class PreviewKeys:
    """Scope every operation, including default connections and key deletion."""
    def __init__(self,path,ident,backend=None):
        from workbench.companion_chat import WindowsKeys
        self.backend=backend if backend is not None else WindowsKeys()
        identity=str(Path(path).resolve()).casefold()+':'+str(uuid.UUID(ident))
        self.prefix='Hecate/ResearchPreview/'+hashlib.sha256(identity.encode()).hexdigest()[:32]+'/'
    def target(self,target):return self.prefix+hashlib.sha256(target.encode()).hexdigest()
    def get(self,target):return self.backend.get(self.target(target))
    def set(self,target,key):return self.backend.set(self.target(target),key)
    def delete(self,target):return self.backend.delete(self.target(target))


def seed_samples(server,ident):
    from workbench.research_import import ResearchImporter
    base=uuid.UUID(ident);revision=lambda value:str(uuid.uuid5(base,value))
    importer=ResearchImporter(server.chat.store.path)
    for category,name,body in [
        ('encounter','【测试样例】研究资料与事实','这是一份合成研究资料。参考资料不等于用户现实经历，未核实结论应保留不确定性。'),
        ('course','【测试样例】向量线性组合','给定向量v₁到vₙ及标量a₁到aₙ，a₁v₁+…+aₙvₙ称为这些向量的线性组合。此条仅用于测试课程选材，不代表用户正在修读这门课程。')]:
        with server.chat.store.read_connection() as db:
            marker=db.execute("SELECT value FROM rc_meta WHERE key='import_schema'").fetchone()
            if marker and marker[0]!='1':raise ValueError('测试资料导入结构不受支持。')
            # Samples are installed once. Do not rewrite or revive anything the
            # test user has corrected, withdrawn or otherwise made unavailable.
            if marker and db.execute('SELECT 1 FROM rc_import_items WHERE namespace=? AND external_id=?',(ident,'preview-'+category)).fetchone():continue
        item={'id':'preview-'+category,'revision':revision('sample-'+category),'previous':None,'title':name,'body':body,
              'source_text':body,'source_ref':'合成测试样例，不是作者资料','review_status':'unverified',
              'review_scope':'仅用于检查入口与引用，不是已核实研究成果。'}
        importer.apply({'format':'gernze-research-import-v1','namespace':ident,'items':[item]},category=category,
                       courses=(revision('sample-course'),) if category=='course' else (),source_kind='companion')


@contextmanager
def preview_server(profile,*,samples=False,keys_backend=None,voice_notify=None,entrance=None,behavior_call=None,modules=None,module_notify=None):
    from workbench.server import WorkbenchServer
    from workbench.owner_memory import file_gate
    path,ident=prepare_profile(profile)
    with file_gate(path/'preview.lock'):
        # Recheck after obtaining the process lock before constructing a writer.
        path,ident=prepare_profile(path)
        server=WorkbenchServer(path,research_enabled=True,chat_keys=PreviewKeys(path,ident,keys_backend),start_auto_review=False,voice_notify=voice_notify,entrance=entrance,behavior_call=behavior_call,modules=modules,module_notify=module_notify)
        try:
            server.research_preview=True
            server.memory_reviewer.configure(False)
            if samples:seed_samples(server,ident)
            from workbench.research_shelf_sync import ResearchShelfSync
            server.research_shelf_sync=ResearchShelfSync(path,ident,server.chat.store.path)
            server.research_shelf_sync.refresh()
            server.memory_reviewer.start()
            yield server
        finally:
            server.stop();server.server_close()


def main(argv=None):
    parser=argparse.ArgumentParser(description='启动独立研究测试工作台；不会迁移原版资料。')
    parser.add_argument('--profile',required=True,type=Path,help='新的空目录或本工具创建的测试目录（绝对路径）')
    parser.add_argument('--samples',action='store_true',help='添加两份明确标注的合成测试资料，重复启动不重复添加')
    args=parser.parse_args(argv)
    from workbench_window import WorkbenchWindow
    worker=None;window=None
    try:
        with preview_server(args.profile,samples=args.samples) as server:
            worker=threading.Thread(target=server.serve,name='research-preview',daemon=True);worker.start()
            try:
                window=WorkbenchWindow(args.profile,lambda *a,**k:None,on_closed=server.stop)
                if not window.open(server.launch_url):raise RuntimeError('研究测试窗口未能打开。')
                if not window.ready.wait(17) or window.error or not window.hwnd:raise RuntimeError('研究测试窗口未能就绪。')
                print('已启动独立研究测试版。连接需单独设置，自动审查已暂停；关闭测试窗口后可照常使用原版。',flush=True)
                worker.join()
            finally:
                try:
                    if window:window.close()
                finally:
                    server.stop();worker.join(9)
                    if worker.is_alive():raise RuntimeError('测试工作台仍在退出，请稍后再启动。')
    except KeyboardInterrupt:return 0
    except Exception as error:
        # Do not print arbitrary provider/OS exception text, URLs or secrets.
        print('研究测试版未能启动或退出。请检查目录是否为独立测试目录，以及桌面依赖是否齐全。'+
              (' '+str(error) if type(error) is ValueError and str(error).startswith(('测试','请选择','现有测试')) else ''),flush=True)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
