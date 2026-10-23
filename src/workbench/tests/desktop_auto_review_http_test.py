from pathlib import Path
import sys,tempfile,unittest,threading,json
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from workbench.server import WorkbenchServer

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=WorkbenchServer(Path(self.tmp.name));self.t=threading.Thread(target=self.s.serve,daemon=True);self.t.start()
    def tearDown(self):self.s.stop();self.t.join(2);self.s.server_close();self.tmp.cleanup()
    def post(self,command,params=None,token=None):
        r=Request(self.s.origin+'/api/call',data=json.dumps({'command':command,'params':params or {}}).encode(),headers={'Authorization':'Bearer '+(self.s.token if token is None else token),'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(r,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as e:return e.code,json.load(e)
    def test_status_and_toggle_are_authenticated_and_persisted(self):
        self.assertEqual(self.post('chat.layers.auto_review.status',token='wrong')[0],403)
        code,data=self.post('chat.layers.auto_review.status');self.assertEqual(code,200);self.assertTrue(data['result']['enabled'])
        code,data=self.post('chat.layers.auto_review.configure',{'enabled':False});self.assertEqual(code,200);self.assertFalse(data['result']['enabled'])
        self.assertFalse(self.s.memory_reviewer.status()['enabled'])
    def test_scope_and_types_cannot_open_memory_writes(self):
        self.assertEqual(self.post('chat.layers.auto_review.configure',{'enabled':True,'core':'MODEL-WRITE'})[0],400)
        self.assertEqual(self.post('chat.layers.auto_review.configure',{'enabled':'true'})[0],400)
        self.assertEqual(self.post('chat.layers.auto_review.run')[0],200)
        self.assertEqual(self.s.chat.layers.snapshot()['approved'],[])
        self.assertFalse(self.s.chat.config()['configured'])
if __name__=='__main__':unittest.main(verbosity=2)
