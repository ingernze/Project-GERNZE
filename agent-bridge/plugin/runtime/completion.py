"""Trusted plugin lifecycle hook. Forwards identity only; never reads transcript contents."""
import json,sys,time,uuid
from paths import DATA
def main():
    config=DATA/'notifications.json'
    if not config.is_file():return
    c=json.loads(config.read_text(encoding='utf-8'))
    manifest=DATA/'task-reminders.json'
    if '--start' in sys.argv:
        manifest.write_text(json.dumps({'id':'gernze-codex','enabled':True,'capabilities':['task-reminders-v1']}),encoding='utf-8')
        return
    if not manifest.is_file():return
    event=json.loads(sys.stdin.read(262144))
    if event.get('hook_event_name')!='Stop' or event.get('stop_hook_active'):return
    session=event.get('session_id');turn=event.get('turn_id')
    if not isinstance(session,str) or not session or not isinstance(turn,str) or not turn:return
    sys.path.insert(0,c['publisherCode'])
    from codex_tasks import CodexTasks
    task=str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([session,turn],separators=(',',':'))))
    CodexTasks(c['privateDir'],manifest,c['serverId']).complete(task,int(time.time()*1000))
if __name__=='__main__':
    try:main()
    except Exception:pass
    # Advisory hooks must neither block the task nor expose its content.
    print('{}')
