from pathlib import Path
import sys,tempfile,unittest,threading,json,uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from workbench.server import WorkbenchServer

class HTTPChecks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='gernze-alignment-');self.s=WorkbenchServer(Path(self.tmp.name));self.t=threading.Thread(target=self.s.serve,daemon=True);self.t.start()
 def tearDown(self):self.s.stop();self.t.join(2);self.s.server_close();self.tmp.cleanup()
 def post(self,command,params={},token=None,origin=None):
  h={'Content-Type':'application/json','Authorization':'Bearer '+(self.s.token if token is None else token)}
  if origin:h['Origin']=origin
  req=Request(self.s.origin+'/api/call',data=json.dumps({'command':command,'params':params}).encode(),headers=h,method='POST')
  try:
   with urlopen(req,timeout=3) as r:return r.status,json.load(r)
  except HTTPError as e:return e.code,json.load(e)
 def test_read_only_books_and_layer_status_are_finite_dtos(self):
  code,v=self.post('chat.books.months');self.assertEqual((code,v['result']),(200,[]))
  code,v=self.post('chat.layers.get');self.assertEqual(code,200);self.assertEqual(v['result']['settings']['reviewDays'],7);self.assertNotIn('path',v['result'])
  self.assertEqual(self.post('chat.books.days',{'month':'../private'})[0],400)
  self.assertEqual(self.post('chat.books.day',{'day':'2026-02-30'})[0],400)
  self.assertEqual(self.post('chat.books.months',{'sql':'SELECT * FROM lc_messages'})[0],400)
 def test_old_write_and_core_or_sync_bypass_are_denied(self):
  for command,params in [('memory.save',{'title':'x','body':'x','decision':'adopted'}),('chat.memory.save',{'note':{}}),('chat.layers.core.set',{'entries':[]}),('chat.layers.decide',{'decisions':[{'key':'forged','revision':'fake','action':'approve'}]})]:self.assertEqual(self.post(command,params)[0],400)
  self.assertEqual(self.s.chat.layers.snapshot()['approved'],[])
 def test_wrong_capability_and_cross_origin_are_rejected(self):
  self.assertEqual(self.post('chat.layers.get',token='wrong')[0],403);self.assertEqual(self.post('chat.layers.get',origin='https://other.invalid')[0],403)
 def test_actual_component_routes_and_cover_asset_are_served(self):
  for path,mime in [('/memory-books.js','text/javascript'),('/memory-books.css','text/css'),('/alignment.css','text/css'),('/assets/cover-10.png','image/png')]:
   with urlopen(self.s.origin+path,timeout=3) as r:self.assertEqual(r.status,200);self.assertIn(mime,r.headers['Content-Type']);self.assertGreater(len(r.read()),100)
  with self.assertRaises(HTTPError):urlopen(self.s.origin+'/assets/',timeout=3)
if __name__=='__main__':unittest.main(verbosity=2)
