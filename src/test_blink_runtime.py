import os,json,time
from pathlib import Path
os.environ['HECATE_STATE_DIR']=str(Path(__file__).parent/'blink_test_state')
import app
pet=app.HecatePet()
results=[]
started=time.monotonic()
def check(name,condition):
 results.append({'check':name,'passed':bool(condition)})
def cycle():
 check('cycle_returned_to_idle',pet.frame_index==0)
 pet._drag_begin(type('E',(),{'x_root':100,'y_root':100})())
 check('drag_open_no_timer',pet.frame_index==0 and pet.frame_job is None)
 pet._drag_end(None)
 check('release_restarts_timer',pet.frame_job is not None)
 pet.hide()
 check('hidden_open_no_timer',pet.frame_index==0 and pet.frame_job is None)
 pet.show()
 check('show_open_timer',pet.frame_index==0 and pet.frame_job is not None)
 Path(app.OUTPUT/'blink_runtime_results.json').write_text(json.dumps(results,indent=2))
 pet.quit()
original=pet._next_frame
seen=[]
def observe():
 original()
 seen.append(pet.frame_index)
pet._next_frame=observe
pet._cancel_frame();pet._schedule_next_frame()
def finish():
 check('full_sequence',seen==[1,2,3,4,5,0])
 cycle()
pet.root.after(4350,finish)
pet.run()
assert all(r['passed'] for r in results),results
print(json.dumps(results))
