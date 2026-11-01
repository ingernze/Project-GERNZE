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
    def test_connection_routes_are_authenticated_and_never_return_keys(self):
        class Keys:
            def __init__(self):self.values={}
            def get(self,k):return self.values.get(k,'')
            def set(self,k,v):self.values[k]=v
            def delete(self,k):self.values.pop(k,None)
        self.s.chat.keys=Keys()
        self.assertEqual(self.post('chat.connections.list',token='wrong')[0],403)
        settings={'enabled':True,'endpoint':'https://synthetic.invalid/chat/completions','model':'synthetic','key':'SYNTHETIC-NEVER-RETURN'}
        code,data=self.post('chat.connections.save',{'name':'合成连接','settings':settings})
        self.assertEqual(code,200);ident=data['result']['config']['connection_id']
        self.assertNotIn('SYNTHETIC-NEVER-RETURN',json.dumps(data))
        self.assertEqual(self.post('chat.connections.list')[1]['result']['saved_count'],1)
        self.assertEqual(self.post('chat.connections.select',{'connection_id':'default'})[0],200)
        self.assertEqual(self.post('chat.connections.remove',{'connection_id':ident})[0],200)
        self.assertEqual(self.post('chat.connections.save',{'name':'bad','settings':settings,'key':'extra'})[0],400)

if __name__=='__main__':unittest.main(verbosity=2)
