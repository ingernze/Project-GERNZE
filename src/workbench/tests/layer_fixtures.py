"""Host-committed synthetic source -> working summary -> explicit owner approval."""
import uuid

def approved(chat,body):
    for i in range(4):
        rid=str(uuid.uuid4());chat.store.begin_turn(chat.store.session_id,body,rid)
        chat.store.complete(rid,{'text':'合成来源回答','emotion':'normal','action':'none'},chat.store.epoch(),[])
    view=chat.store.summary_view(chat.store.session_id,keep_recent=1,batch=3)
    assert chat.store.commit_summary(chat.store.session_id,view,view['new_turns'],body)
    w=chat.layers.snapshot()['pending'][-1]
    chat.review_layers([{'key':w['key'],'revision':w['revision'],'action':'approve'}])
    return next(a for a in chat.layers.snapshot()['approved'] if a['key']==w['key'])
