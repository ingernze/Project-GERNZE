"""Host-owned L2/L3 beside the journal, never a chat JSON/tool write target.

Only new lm_* tables are created. Summary + working entry share the journal
transaction; approval + replay receipt likewise share one SQLite transaction.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

if __package__:
    from .conversation_store import encoded, stamp
else:
    from conversation_store import encoded, stamp

SCHEMA = (
 'CREATE TABLE IF NOT EXISTS lm_layer_sync_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS lm_remote_sources(key TEXT PRIMARY KEY,revision TEXT NOT NULL,payload TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS lm_sync_conflicts(tier INTEGER NOT NULL,key TEXT NOT NULL,PRIMARY KEY(tier,key))',
 'CREATE TABLE IF NOT EXISTS lm_deferred(id TEXT PRIMARY KEY,payload TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS lm_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
 '''CREATE TABLE IF NOT EXISTS lm_working(key TEXT PRIMARY KEY,revision TEXT NOT NULL,
 body TEXT NOT NULL,source_summary_id TEXT NOT NULL UNIQUE,session_id TEXT NOT NULL,
 source_epoch INTEGER NOT NULL,source_turn_ids TEXT NOT NULL,source_ids TEXT NOT NULL,
 source_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,approved_base_revision TEXT)''',
 '''CREATE TABLE IF NOT EXISTS lm_approved(key TEXT PRIMARY KEY,revision TEXT NOT NULL,
 body TEXT NOT NULL,source_revision TEXT NOT NULL,updated_at TEXT NOT NULL,
 deleted INTEGER NOT NULL DEFAULT 0,reviewed_by TEXT NOT NULL)''',
 '''CREATE TABLE IF NOT EXISTS lm_receipts(key TEXT NOT NULL,source_revision TEXT NOT NULL,
 digest TEXT NOT NULL,action TEXT NOT NULL,processed_at TEXT NOT NULL,
 PRIMARY KEY(key,source_revision))''',
)


def load_core(path=None):
    path = Path(path) if path else Path(__file__).with_name('companion_core_memory.json')
    if not path.exists() and path.name=='companion_core_memory.json':path=path.with_name('companion_core_memory.example.json')
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict or value.get('schemaVersion') != 1 or type(value.get('entries')) is not list or len(value['entries']) > 20:
        raise ValueError('第一层基础资料格式无效。')
    keys=set()
    for e in value['entries']:
        if type(e) is not dict or type(e.get('key')) is not str or not e['key'] or e['key'] in keys or type(e.get('body')) is not str or len(e['body'])>1000:
            raise ValueError('第一层基础资料格式无效。')
        keys.add(e['key'])
    return value


class MemoryLayers:
    def __init__(self, store, *, core_loader=load_core):
        self.store=store;self.core_loader=core_loader
        self.core_loader()  # fail closed, never read private data from other paths
        with store.connection() as db:
            for sql in SCHEMA:db.execute(sql)
            for key,value in {'reviewDays':7,'summaryDays':7,'summaryEnabled':True}.items():
                db.execute('INSERT OR IGNORE INTO lm_meta VALUES (?,?)',(key,encoded(value)))
            self.invalidate_sources(db)
            # Preserve host-verified overflow separately: context barriers may
            # discard lc_summaries while a user reviews the first 200 entries.
            for row in db.execute('SELECT * FROM lc_summaries ORDER BY version').fetchall():
                summary=dict(row)
                if self.source_valid(db,{'session_id':summary['session_id'],'source_turn_ids':summary['source_ids']}):
                    self.ingest(db,summary,defer=True)
            self.backfill(db)
        store.layers=self

    @staticmethod
    def _settings(db):return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM lm_meta')}
    def settings(self):
        with self.store.read_connection() as db:return self._settings(db)
    def configure(self, settings):
        if type(settings) is not dict or set(settings)!={'reviewDays','summaryDays','summaryEnabled'}:raise ValueError('记忆设置字段不匹配。')
        if settings['reviewDays'] is not None and (type(settings['reviewDays']) is not int or not 1<=settings['reviewDays']<=3650):raise ValueError('审查间隔至少1天，或留空按需审查。')
        if type(settings['summaryDays']) is not int or not 1<=settings['summaryDays']<=3650 or type(settings['summaryEnabled']) is not bool:raise ValueError('压缩间隔至少1天。')
        with self.store.connection() as db:
            self.store._owner(db)
            db.executemany('INSERT OR REPLACE INTO lm_meta VALUES (?,?)',[(k,encoded(v)) for k,v in settings.items()])
        return dict(settings)

    @staticmethod
    def source_valid(db, working):
        remote=db.execute('SELECT revision FROM lm_remote_sources WHERE key=?',(working.get('key',''),)).fetchone() if isinstance(working,dict) else None
        if remote and remote[0]==working.get('revision'):return True
        session=db.execute('SELECT deleted FROM lc_sessions WHERE id=?',(working['session_id'],)).fetchone()
        if not session or session['deleted']:return False
        turns=working['source_turn_ids']
        if isinstance(turns,str):turns=json.loads(turns)
        if not isinstance(turns,list) or not 1<=len(turns)<=8 or len(set(turns))!=len(turns):return False
        ids=[]
        for tid in turns:
            turn=db.execute('SELECT status,origin FROM lc_turns WHERE id=? AND session_id=?',(tid,working['session_id'])).fetchone()
            messages=db.execute('SELECT id,role,content FROM lc_messages WHERE turn_id=? AND session_id=?',(tid,working['session_id'])).fetchall()
            if not turn or turn['status']!='complete' or turn['origin']!='user' or len(messages)!=2 or {m['role'] for m in messages}!={'user','assistant'} or any(not m['content'].strip() for m in messages):return False
            ids.extend(m['id'] for m in messages)
        expected=working.get('source_ids') if isinstance(working,dict) else working['source_ids']
        if isinstance(expected,str):expected=json.loads(expected)
        return expected is None or len(expected)==len(ids) and set(expected)==set(ids)

    def invalidate_sources(self,db):
        for working in self._working(db):
            if working['reviewed_action'] or self.source_valid(db,working):continue
            # Retire the exact pending revision; never revoke an approved L2.
            db.execute('INSERT OR IGNORE INTO lm_receipts VALUES (?,?,?,?,?)',(working['key'],working['revision'],'source-invalidated','source_invalidated',stamp()))
            db.execute("UPDATE lm_working SET body='' WHERE key=? AND revision=?",(working['key'],working['revision']))
        for row in db.execute('SELECT id,payload FROM lm_deferred').fetchall():
            summary=json.loads(row['payload'])
            if not self.source_valid(db,{'session_id':summary['session_id'],'source_turn_ids':summary['source_ids']}):db.execute('DELETE FROM lm_deferred WHERE id=?',(row['id'],))

    @staticmethod
    def pending_count(db):
        return db.execute('''SELECT COUNT(*) FROM lm_working w LEFT JOIN lm_receipts r
            ON w.key=r.key AND w.revision=r.source_revision WHERE r.key IS NULL''').fetchone()[0]

    def backfill(self,db):
        for row in db.execute('SELECT id,payload FROM lm_deferred ORDER BY rowid').fetchall():
            summary=json.loads(row['payload'])
            if not self.source_valid(db,{'session_id':summary['session_id'],'source_turn_ids':summary['source_ids']}):
                db.execute('DELETE FROM lm_deferred WHERE id=?',(row['id'],));continue
            if self.pending_count(db)>=200:break
            self.ingest(db,summary)

    def ingest(self, db, summary, *, defer=False):
        """Called only with a locally committed lc_summaries row, in its tx."""
        trusted=db.execute('SELECT * FROM lc_summaries WHERE id=?',(summary['id'],)).fetchone()
        queued=db.execute('SELECT payload FROM lm_deferred WHERE id=?',(summary['id'],)).fetchone()
        if not (trusted is not None and dict(trusted)==summary or queued is not None and json.loads(queued['payload'])==summary):raise ValueError('摘要来源未提交。')
        if not self.source_valid(db,{'session_id':summary['session_id'],'source_turn_ids':summary['source_ids']}):raise ValueError('摘要来源已撤销，不能重新接收。')
        key='summary:'+summary['id']
        if key in {x['key'] for x in self.core_loader()['entries']}:raise ValueError('摘要不能修改第一层。')
        if db.execute('SELECT 1 FROM lm_working WHERE key=?',(key,)).fetchone():return
        if self.pending_count(db)>=200:
            if defer:
                db.execute('INSERT OR IGNORE INTO lm_deferred VALUES (?,?)',(summary['id'],encoded(summary)));return
            raise ValueError('第三层已有200条待审摘要，请先审查；原文仍保留。')
        turns=json.loads(summary['source_ids']);ids=[];source_at=None
        if not isinstance(turns,list) or not turns or len(turns)>8 or len(turns)!=len(set(turns)) or not summary['text'].strip() or len(summary['text'])>1500:raise ValueError('摘要来源范围无效。')
        for tid in turns:
            t=db.execute('SELECT * FROM lc_turns WHERE id=? AND session_id=?',(tid,summary['session_id'])).fetchone()
            msgs=db.execute('SELECT * FROM lc_messages WHERE turn_id=? ORDER BY role DESC',(tid,)).fetchall()
            if not t or t['status']!='complete' or len(msgs)!=2 or t['origin']!='user':raise ValueError('摘要必须来自已保存的完整原文轮次。')
            ids.extend(m['id'] for m in msgs)
            if source_at is None:source_at=msgs[0]['time'] or None
        current=db.execute('SELECT revision FROM lm_approved WHERE key=?',(key,)).fetchone()
        db.execute('INSERT INTO lm_working VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(key,str(uuid.uuid4()),summary['text'],summary['id'],summary['session_id'],summary['epoch'],encoded(turns),encoded(ids),source_at,summary['created_at'],summary['created_at'],current[0] if current else None))
        db.execute('DELETE FROM lm_deferred WHERE id=?',(summary['id'],))

    @staticmethod
    def _working(db):
        result=[]
        for r in db.execute('''SELECT w.*,r.action AS reviewed_action FROM lm_working w LEFT JOIN lm_receipts r
             ON w.key=r.key AND w.revision=r.source_revision ORDER BY w.created_at,w.key'''):
            x=dict(r);x['source_turn_ids']=json.loads(x['source_turn_ids']);x['source_ids']=json.loads(x['source_ids']);result.append(x)
        return result
    def snapshot(self):
        core=self.core_loader()
        with self.store.read_connection() as db:
            working=self._working(db);approved=[dict(r) for r in db.execute('SELECT * FROM lm_approved ORDER BY updated_at DESC,key')];prefs=self._settings(db)
            pending=[w for w in working if not w['reviewed_action'] and self.source_valid(db,w)]
            deferred=db.execute('SELECT COUNT(*) FROM lm_deferred').fetchone()[0]
        with self.store.read_connection() as db:
            conflicts={r['key'] for r in db.execute('SELECT key FROM lm_sync_conflicts')}
        approved=[a for a in approved if a['key'] not in conflicts];pending=[w for w in pending if w['key'] not in conflicts]
        with self.store.read_connection() as db:
            for w in working:
                row=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',('phone3:'+w['key']+':'+w['revision'],)).fetchone()
                if row:w['phoneSource']=json.loads(row[0])
        now=datetime.now(timezone.utc);days=prefs['reviewDays']
        def aged(w):
            try:return (now-datetime.fromisoformat(w['updated_at'].replace('Z','+00:00'))).total_seconds()>=days*86400
            except (ValueError,TypeError):return False
        return {'core':core,'working':working,'approved':approved,'pending':pending,'settings':prefs,'due':days is not None and any(aged(w) for w in pending),'deferredCount':deferred}

    def decide(self, decisions, *, review_guard=None, review_commit=None):
        if type(decisions) is not list or not 1<=len(decisions)<=200:raise ValueError('审查结果需包含1～200项。')
        known=set();items=[];core={e['key'] for e in self.core_loader()['entries']}
        with self.store.connection() as db:
            self.store._owner(db)
            if review_guard is not None:review_guard(db)
            for d in decisions:
                if type(d) is not dict or not {'key','revision','action'}<=d.keys() or set(d)-{'key','revision','action','text'} or type(d['key']) is not str or d['key'] in known or d['key'] in core or d['action'] not in ('approve','correct','reject','defer'):raise ValueError('审查操作无效，第一层不能修改。')
                known.add(d['key'])
                if db.execute('SELECT 1 FROM lm_sync_conflicts WHERE key=?',(d['key'],)).fetchone():raise ValueError('此条存在同步冲突，请先在同步入口选择版本。')
                if d['action']=='correct' and (type(d.get('text')) is not str or not d['text'].strip() or len(d['text'])>1000):raise ValueError('纠正内容须为1～1000字。')
                w=db.execute('SELECT * FROM lm_working WHERE key=?',(d['key'],)).fetchone()
                if not w or w['revision']!=d['revision']:raise ValueError('待审版本已变化，请刷新。')
                if not self.source_valid(db,dict(w)) and not db.execute('SELECT 1 FROM lm_receipts WHERE key=? AND source_revision=?',(w['key'],w['revision'])).fetchone():raise ValueError('待审摘要的原文来源已撤销，请刷新。')
                if d['action']=='defer':continue
                digest=hashlib.sha256(encoded({'action':d['action'],'text':d['text'].strip() if d['action']=='correct' else ''}).encode()).hexdigest()
                receipt=db.execute('SELECT * FROM lm_receipts WHERE key=? AND source_revision=?',(w['key'],w['revision'])).fetchone()
                if receipt:
                    if receipt['digest']!=digest:raise ValueError('该版本已审查，旧结果不能覆盖后续决定。')
                    items.append((d,w,digest,True));continue
                phone=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',('phone3:'+w['key']+':'+w['revision'],)).fetchone()
                remote=db.execute('SELECT 1 FROM lm_remote_sources WHERE key=? AND revision=?',(w['key'],w['revision'])).fetchone()
                if remote and not phone and d['action'] in ('approve','correct'):
                    raise ValueError('远端摘要缺少已绑定的原文来源，请先核对来源；不能批准。')
                if phone and d['action'] in ('approve','correct'):
                    from .phone_archive import PhoneArchive
                    ref=json.loads(phone[0]);source=PhoneArchive(self.store.path).source(ref['device'],ref['sessionId'],ref['start'],ref['end'])
                    if not source['complete']:raise ValueError('手机第四层来源尚未传齐，请先同步原文后审查。')
                a=db.execute('SELECT revision FROM lm_approved WHERE key=?',(w['key'],)).fetchone()
                if (a[0] if a else None)!=w['approved_base_revision']:raise ValueError('第二层已变化，旧审批基线不再适用。')
                items.append((d,w,digest,False))
            applied=0;already=0
            for d,w,digest,replay in items:
                if replay:already+=1;continue
                if d['action'] in ('approve','correct'):
                    db.execute('INSERT OR REPLACE INTO lm_approved VALUES (?,?,?,?,?,0,?)',(w['key'],str(uuid.uuid4()),d['text'].strip() if d['action']=='correct' else w['body'],w['revision'],stamp(),'owner-delegated-review'))
                db.execute('INSERT INTO lm_receipts VALUES (?,?,?,?,?)',(w['key'],w['revision'],digest,d['action'],stamp()));applied+=1
            self.backfill(db)
            result={'applied':applied,'alreadyProcessed':already}
            # Trusted Python callback only; the HTTP/JSON schema cannot supply it.
            # A failed audit write rolls back the entire approval transaction.
            if review_commit is not None:review_commit(db,result)
            return result

    def change_approved(self,key,revision,*,text=None,withdraw=False):
        if type(key) is not str or type(revision) is not str or key in {e['key'] for e in self.core_loader()['entries']}:raise ValueError('不能修改第一层。')
        if not withdraw and (type(text) is not str or not text.strip() or len(text)>1000):raise ValueError('纠正内容须为1～1000字。')
        with self.store.connection() as db:
            self.store._owner(db)
            if db.execute('SELECT 1 FROM lm_sync_conflicts WHERE key=?',(key,)).fetchone():raise ValueError('此条存在同步冲突，请先在同步入口选择版本。')
            a=db.execute('SELECT * FROM lm_approved WHERE key=?',(key,)).fetchone()
            if not a or a['revision']!=revision or a['deleted']:raise ValueError('该条已变化或撤回，请刷新。')
            db.execute('UPDATE lm_approved SET revision=?,body=?,deleted=?,updated_at=? WHERE key=?',(str(uuid.uuid4()),'' if withdraw else text.strip(),int(withdraw),stamp(),key))
        return {'changed':True}

    def context_notes(self):
        core={e['key'] for e in self.core_loader()['entries']}
        with self.store.read_connection() as db:
            return [{'id':r['key'],'revision':r['revision'],'title':'已审核记忆','body':r['body'],'kind':'other','event_date':'','important':False,'chat_enabled':True} for r in db.execute('SELECT * FROM lm_approved WHERE deleted=0 ORDER BY updated_at DESC') if r['key'] not in core and not db.execute('SELECT 1 FROM lm_sync_conflicts WHERE tier=2 AND key=?',(r['key'],)).fetchone()]

    def context_summaries(self, session_id):
        with self.store.read_connection() as db:
            blocked={e['key'] for e in self.core_loader()['entries']}
            blocked.update(r['key'] for r in db.execute('SELECT key FROM lm_approved'))
            result=[]
            for i,w in enumerate(self._working(db)):
                if w['key'] in blocked or w['reviewed_action'] or not self.source_valid(db,w):continue
                remote=db.execute('SELECT payload FROM lm_remote_sources WHERE key=? AND revision=?',(w['key'],w['revision'])).fetchone()
                if not remote and w['session_id']!=session_id:continue
                if db.execute('SELECT 1 FROM lm_sync_conflicts WHERE key=?',(w['key'],)).fetchone():continue
                valid=db.execute('SELECT COUNT(*) FROM lc_messages WHERE allowed=1 AND id IN ('+','.join('?' for _ in w['source_ids'])+')',w['source_ids']).fetchone()[0]
                if remote or valid==len(w['source_ids']):
                    item={'id':w['source_summary_id'],'version':i,'text':w['body'],'source_ids':encoded(w['source_turn_ids'])}
                    if remote:item['source']={'kind':'paired-summary','reference':json.loads(remote[0])}
                    result.append(item)
            return result

    def permission_prompt(self):
        v=self.snapshot();counts={'core':len(v['core']['entries']),'approved':sum(not a['deleted'] for a in v['approved']),'pending':len(v['pending'])}
        return ('\n程序只读存储状态：'+encoded(counts)+'。第一层由构建提供，聊天API不能改；第二层只接收用户或其指派审查流程批准的版本。第三层是第四层原文的待审压缩资料，低于上层，不能当作已经确认的事实。第四层独立保留原文；请求只选取部分历史，不代表其他原文不存在。普通聊天和摘要模型不授予写入第二层的权限；用户委派的电脑独立审查流程可核对原文后批准具体版本。旧主动笔记是只读旧资料，没有自动变为已审记忆。')

    def phone_source(self,key,revision):
        if type(key) is not str or type(revision) is not str:raise ValueError('来源编号无效。')
        with self.store.read_connection() as db:
            w=db.execute('SELECT revision FROM lm_working WHERE key=?',(key,)).fetchone()
            if not w or w[0]!=revision:raise ValueError('候选版本已变化，请刷新。')
            row=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',('phone3:'+key+':'+revision,)).fetchone()
        if not row:raise ValueError('这条没有已配对手机原文来源。')
        from .phone_archive import PhoneArchive
        ref=json.loads(row[0]);return PhoneArchive(self.store.path).source(ref['device'],ref['sessionId'],ref['start'],ref['end'])
