"""Explicit read-only monthly/day projection. No SQL/path arguments in bridge."""
from datetime import datetime, timezone, timedelta, date
import re
import json
from .phone_archive import PhoneArchive
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:SHANGHAI=ZoneInfo('Asia/Shanghai');HAS_ZONE=True
except ZoneInfoNotFoundError:SHANGHAI=timezone(timedelta(hours=8));HAS_ZONE=False

def day_of(value):
    if not value or not isinstance(value,str):return None
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None or not HAS_ZONE and dt.year<1992:return None
        return dt.astimezone(SHANGHAI).date().isoformat()
    except (ValueError,OverflowError):return None


class MemoryArchive:
    def __init__(self,chat,*,legacy=None):self.chat=chat;self.store=chat.store;self.layers=chat.layers;self.legacy=legacy

    def history(self,*,limit=1,before=None):
        if type(limit) is not int or not 1<=limit<=20 or before is not None and (type(before) is not int or before<1):raise ValueError('聊天分页无效。')
        with self.store.read_connection() as db:
            sid=self.store.session_id
            where="t.session_id=? AND t.covered=0 AND s.deleted=0 AND t.status<>'deleted'";args=[sid]
            if before is not None:where+=' AND t.seq<?';args.append(before)
            rows=db.execute('SELECT t.* FROM lc_turns t JOIN lc_sessions s ON t.session_id=s.id WHERE '+where+' ORDER BY t.seq DESC LIMIT ?',(*args,limit+1)).fetchall()
            result=[]
            for t in reversed(rows[:limit]):
                msgs={m['role']:dict(m) for m in db.execute('SELECT * FROM lc_messages WHERE turn_id=?',(t['id'],))}
                if 'user' not in msgs:continue
                result.append({'id':t['id'],'seq':t['seq'],'status':t['status'],'input':msgs['user']['content'],'reply':msgs.get('assistant',{}).get('content',''),'createdAt':t['created_at']})
            covered=db.execute('SELECT COUNT(*) FROM lc_turns WHERE session_id=? AND covered=1',(sid,)).fetchone()[0]
            return {'sessionId':sid,'turns':result,'hasMore':len(rows)>limit,'before':result[0]['seq'] if result else None,'compressedTurns':covered}

    def _entries(self):
        entries=[]
        with self.store.read_connection() as db:
            for t in db.execute("SELECT t.* FROM lc_turns t JOIN lc_sessions s ON s.id=t.session_id WHERE s.deleted=0 AND t.status<>'deleted' ORDER BY t.seq"):
                msgs={m['role']:dict(m) for m in db.execute('SELECT * FROM lc_messages WHERE turn_id=?',(t['id'],))}
                user=msgs.get('user');assistant=msgs.get('assistant')
                if not user or not user['content'].strip():continue
                text='你：'+user['content']+'\n\n'+('格莉兹：'+assistant['content'] if assistant else '（这轮回复未完成，仅保留你的原文。）')
                entries.append({'id':'chat:'+t['id'],'kind':'conversation','text':text,'day':day_of(user['time']),'status':'active','sourceRefs':[{'id':t['id'],'label':'第四层原文 · 会话 '+t['session_id'][:8]+' · 轮次 '+str(t['seq'])}],'updatedAt':user['time'] or ''})
            working=self.layers._working(db)
            approved={a['key']:dict(a) for a in db.execute('SELECT * FROM lm_approved')}
            shown=set()
            for w in working:
                if db.execute('SELECT 1 FROM lm_sync_conflicts WHERE key=?',(w['key'],)).fetchone():continue
                a=approved.get(w['key']);tier=2 if a and not a['deleted'] else 3 if not w['reviewed_action'] else None
                if tier is None or tier==3 and not self.layers.source_valid(db,w):continue
                if tier==2:shown.add(w['key'])
                body=a['body'] if tier==2 else w['body'];updated=a['updated_at'] if tier==2 else w['updated_at']
                entries.append({'id':'layer:'+str(tier)+':'+w['key'],'kind':'memory' if tier==2 else 'summary','text':('第二层 · 已审核记忆\n' if tier==2 else '第三层 · 待审摘要\n')+body,'day':day_of(w['source_at']),'status':'active','sourceRefs':[{'id':tid,'label':'来源原文轮次 '+tid[:8]} for tid in w['source_turn_ids']],'updatedAt':updated})
            for key,a in approved.items():
                if key in shown or a['deleted'] or db.execute('SELECT 1 FROM lm_sync_conflicts WHERE key=?',(key,)).fetchone():continue
                remote=db.execute('SELECT value FROM lm_layer_sync_meta WHERE key=?',('source2:'+key+':'+a['revision'],)).fetchone()
                source=json.loads(remote[0]) if remote else {}
                entries.append({'id':'layer:2:'+key,'kind':'memory','text':'第二层 · 已审核记忆\n'+a['body'],'day':day_of(source.get('at')),'status':'active','sourceRefs':[{'id':tid,'label':'配对端来源轮次 '+tid[:8]} for tid in source.get('turnIds',[])],'updatedAt':a['updated_at']})
        for row in PhoneArchive(self.store.path).entries():
            stamp=row['userAt'] or row['assistantAt'];rid='phone:'+row['device']+':'+row['session']+':'+str(row['index'])
            entries.append({'id':rid,'kind':'conversation','text':'手机第四层原文（只读副本）\n你：'+row['user']+'\n\n莉宝：'+row['assistant'],'day':day_of(stamp),'status':'active','sourceRefs':[{'id':rid,'label':'已配对手机 · 会话 '+row['session'][:8]+' · 第'+str(row['index']+1)+'轮'}],'updatedAt':row['assistantAt'] or row['userAt'] or ''})
        return entries

    def months(self):
        months={}
        for e in self._entries():
            if not e['day']:continue
            m=e['day'][:7];v=months.setdefault(m,{'month':m,'days':set(),'entryCount':0});v['days'].add(e['day']);v['entryCount']+=1
        return [{'month':m,'dayCount':len(v['days']),'entryCount':v['entryCount']} for m,v in sorted(months.items(),reverse=True)]
    def days(self,month):
        if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):raise ValueError('月份无效。')
        try:date.fromisoformat(month+'-01')
        except ValueError:raise ValueError('月份无效。') from None
        days={}
        for e in self._entries():
            if e['day'] and e['day'].startswith(month+'-'):days.setdefault(e['day'],[]).append(e)
        return [{'day':d,'entryCount':len(es),'hasSummary':any(e['kind']=='summary' for e in es),'hasOriginal':any(e['kind']=='conversation' for e in es)} for d,es in sorted(days.items())]
    def day(self,day):
        if not isinstance(day,str):raise ValueError('日期无效。')
        try:
            if date.fromisoformat(day).isoformat()!=day:raise ValueError()
        except ValueError:raise ValueError('日期无效。') from None
        return {'day':day,'entries':[{k:v for k,v in e.items() if k!='day'} for e in self._entries() if e['day']==day]}
    def undated(self):return {'entries':[{k:v for k,v in e.items() if k!='day'} for e in self._entries() if e['day'] is None]}
    def status(self):
        with self.store.read_connection() as db:
            raw=db.execute('SELECT COUNT(*) FROM lc_messages m JOIN lc_sessions s ON s.id=m.session_id WHERE s.deleted=0').fetchone()[0]
        phone=len(PhoneArchive(self.store.path).entries())*2
        return {'phoneStoredMessages':phone,'desktopStoredMessages':raw,'timeZone':'Asia/Shanghai','undatedEntries':len(self.undated()['entries']),'storedMessages':raw+phone,'layerSyncEnabled':True}
    def legacy_notes(self):
        # The old sync namespace can still change externally, but never becomes L2.
        if self.legacy is None or not self.legacy.path.is_file():return {'records':[],'readOnly':True,'approved':False}
        db=sqlite3.connect(self.legacy.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'").fetchone():rows=[]
            else:rows=[{'id':r['id'],'title':r['title'],'body':r['body'],'updatedAt':r['updated_at'],'day':day_of(r['updated_at'])} for r in db.execute('SELECT * FROM notes WHERE deleted=0 ORDER BY updated_at DESC')]
            return {'records':rows,'readOnly':True,'approved':False}
        finally:db.close()
