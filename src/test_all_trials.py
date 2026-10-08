import os,json
from pathlib import Path
os.environ['HECATE_STATE_DIR']=str(Path(__file__).parent/'all_trials_test_state')
import tray_win32
tray_win32.TRAY_CLASS='HecateAllTrialsTest'
import app
from quota_card import QuotaCard,CardState
from PIL import ImageGrab
pet=app.HecatePet();checks=[]
def check(n,v):checks.append({'check':n,'passed':bool(v)})
def start():
 pop=app.TrayPopup(pet,pet.root.winfo_screenwidth()-20,pet.root.winfo_screenheight()-20)
 pet.tray_popup=pop;pop.update_idletasks()
 x,y=pop.winfo_rootx(),pop.winfo_rooty()
 ImageGrab.grab(bbox=(x,y,x+pop.width,y+pop.height),all_screens=True).save(app.OUTPUT/'tray_menu.png')
 check('menu_on_screen',x>=0 and y>=0 and x+pop.width<=pet.root.winfo_screenwidth())
 e=type('E',(),{'x':100*pop.s,'y':310*pop.s})()
 pop.press(e)
 pop.release(type('E',(),{'x':0,'y':0})())
 check('release_outside_does_not_activate',pop.winfo_exists() and pet.commands.empty())
 i=next(i for i,(_,cmd) in enumerate(pop.items) if cmd=='walk:play')
 pop.activate(i)
def walking():
 check('menu_starts_walk',pet.walk_trial.active)
 pet.set_scale(3);check('walk_scale_retained',pet.walk_trial.active)
 pet.hide();check('hide_cancels_walk',not pet.walk_trial.active and pet.walk_trial.job is None)
 pet.show();pet.walk_trial.start()
def finish():
 if pet.walk_trial.active and pet.walk_trial.remaining>0 and not getattr(pet,'test_waited',0)>50:
  pet.test_waited=getattr(pet,'test_waited',0)+1;pet.root.after(100,finish);return
 check('walk_three_cycles_returns_idle',not pet.walk_trial.active and pet.frame_job is not None)
 c=QuotaCard(pet.root,on_save=lambda v:None,on_delete=lambda:None,on_toggle=lambda:None,on_refresh=lambda:None,on_close=lambda:c.destroy())
 c.render(CardState());c.update_idletasks()
 w,h=c.winfo_width(),c.winfo_height();sw,sh=c.winfo_screenwidth(),c.winfo_screenheight()
 check('quota_under_quarter_screen',w*h<=sw*sh*.25 and h<=sh*.56)
 pet.root.after(400,lambda: capture_card(c))
def capture_card(c):
 x,y=c.winfo_rootx(),c.winfo_rooty();w,h=c.winfo_width(),c.winfo_height()
 ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(app.OUTPUT/'quota_small.png')
 checks.append({'check':'quota_size','passed':True,'width':w,'height':h,'screen':[pet.root.winfo_screenwidth(),pet.root.winfo_screenheight()]})
 c.destroy();pet.quit()
 (app.OUTPUT/'results.json').write_text(json.dumps(checks,indent=2))
pet.root.after(100,start);pet.root.after(500,walking);pet.root.after(4200,finish)
pet.run();print(json.dumps(checks));assert all(x['passed'] for x in checks)
