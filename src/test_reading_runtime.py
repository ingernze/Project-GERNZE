"""Legacy test entry; uses the current v05 Windows acceptance contract."""
import os,runpy,sys,json
from pathlib import Path
root=Path(__file__).parent
os.environ['HECATE_STATE_DIR']=str(root/'verification/reading_v05/legacy_runtime')
sys.argv=[str(root/'deepseek_trial.py'),'--reading-self-test']
runpy.run_path(str(root/'deepseek_trial.py'),run_name='__main__')
report=json.loads((Path(os.environ['HECATE_STATE_DIR'])/'output/reading_v05_results.json').read_text(encoding='utf-8'))
assert report['passed'],report
print(json.dumps({'passed':True,'checks':len(report['checks'])}))
