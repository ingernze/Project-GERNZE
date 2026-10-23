import http.client,json,tempfile,threading,unittest
from workbench.server import WorkbenchServer
class VoiceEntryChecks(unittest.TestCase):
    def run_server(self,callback):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        server=WorkbenchServer(tmp.name,voice_notify=callback)
        worker=threading.Thread(target=server.serve,daemon=True);worker.start()
        def stop():server.stop();worker.join(9);server.server_close()
        self.addCleanup(stop);return server
    def call(self,s,command,params=None,auth=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=3)
        headers={'Content-Type':'application/json','Origin':origin or s.origin}
        if auth:headers['Authorization']='Bearer '+s.token
        try:
            c.request('POST','/api/call',json.dumps({'command':command,'params':params or {}}),headers)
            r=c.getresponse();return r.status,json.loads(r.read())
        finally:c.close()
    def test_available_and_finite_routes_queue_only(self):
        events=[];s=self.run_server(events.append)
        self.assertEqual(self.call(s,'voice.available'),(200,{'result':{'available':True}}))
        self.assertEqual(events,[])
        for event in ('open','fixed','text','api','scene_sleep','scene_wake','scene_stop'):
            self.assertEqual(self.call(s,'voice.'+event),(200,{'result':{'queued':True}}))
        self.assertEqual(events,['open','fixed','text','api','scene_sleep','scene_wake','scene_stop'])
    def test_standalone_reports_unavailable_and_rejects_open(self):
        s=self.run_server(None)
        self.assertFalse(self.call(s,'voice.available')[1]['result']['available'])
        self.assertEqual(self.call(s,'voice.text')[0],400)
    def test_auth_origin_params_and_unknown_command_cannot_dispatch(self):
        events=[];s=self.run_server(events.append)
        self.assertEqual(self.call(s,'voice.text',auth=False)[0],403)
        self.assertEqual(self.call(s,'voice.text',origin='https://example.invalid')[0],403)
        for command,params in [('voice.text',{'path':'secret'}),('voice.shell',{}),('voice.generate',{'text':'x'})]:
            self.assertEqual(self.call(s,command,params)[0],400)
        self.assertEqual(events,[])
