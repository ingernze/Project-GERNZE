import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
"""Contract tests without internet or a configured third-party account."""
import tempfile,unittest,json,threading,wave,io,array,hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from concurrent.futures import CancelledError
from voice_backend import FeatureAPIStore,VoiceBackend,pcm_file
class Tests(unittest.TestCase):
    def test_feature_configuration_and_credential_targets_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=FeatureAPIStore(Path(tmp)/'features.json')
            store.configure('voice_dialogue',enabled=True,endpoint='https://example.invalid/v1/chat/completions',model='voice-model')
            self.assertFalse(store.get('cet6')['enabled']);self.assertFalse(store.get('voice_synthesis')['enabled'])
            self.assertNotEqual(store.target('voice_dialogue'),store.target('cet6'))
            self.assertNotIn('key',json.loads(store.path.read_text())['voice_dialogue'])
            for url in ['http://example.invalid/x','https://secret@example.invalid/x','https://example.invalid/x?key=secret']:
                with self.assertRaises(ValueError):store.configure('voice_dialogue',enabled=True,endpoint=url,model='x')
            with self.assertRaises(ValueError):store.get('../global')
    def test_chat_contract_uses_only_selected_feature(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((body,self.headers.get('Authorization')))
                data=json.dumps({'choices':[{'message':{'content':'local fixture response'}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store=FeatureAPIStore(Path(tmp)/'features.json')
                store.configure('voice_dialogue',enabled=True,endpoint='http://127.0.0.1:'+str(server.server_port)+'/v1/chat/completions',model='fixture')
                with patch.object(store,'key',return_value='local-fixture-key') as key:
                    self.assertEqual(store.chat('voice_dialogue',[{'role':'user','content':'fixture'}]),'local fixture response');key.assert_called_once_with('voice_dialogue')
                    with self.assertRaises(RuntimeError):store.chat('cet6',[{'role':'user','content':'fixture'}])
                self.assertEqual(requests[0][0]['model'],'fixture');self.assertEqual(requests[0][1],'Bearer local-fixture-key')
        finally:server.shutdown();server.server_close();thread.join(timeout=2)
    def test_cancelled_job_cannot_restart_engine(self):
        with VoiceBackend() as backend:
            backend.cancel()
            with patch.object(backend,'start') as start:
                with self.assertRaises(CancelledError):backend.synthesize('取消的任务',_expected_generation=0)
                start.assert_not_called()
    def test_invalid_selection_does_not_start_engine(self):
        with VoiceBackend() as backend:
            with patch.object(backend,'start') as start:
                for arguments in [dict(gpt_id='missing'),dict(sovits_id='missing'),dict(reference_id='missing')]:
                    with self.assertRaises(ValueError):backend.synthesize('测试',**arguments)
                start.assert_not_called()
    def test_volume_30_original_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source.wav';samples=[-32000,-1,0,1,32000]
            with wave.open(str(p),'wb') as w:w.setparams((1,2,32000,0,'NONE',''));w.writeframes(array.array('h',samples).tobytes())
            before=p.read_bytes();out=pcm_file(p,root/'cache',30)
            with wave.open(str(out),'rb') as w:self.assertEqual(list(array.array('h',w.readframes(w.getnframes()))),[round(x*.3) for x in samples])
            self.assertEqual(p.read_bytes(),before)
    def test_fixed_library_and_numbered_weights(self):
        with VoiceBackend() as backend:
            self.assertEqual(len(backend.fixed_scenes()),21)
            options=backend.selections()
            for group in ['gpt_options','sovits_options']:
                self.assertEqual([e['label'] for e in options[group]],['第一套','第二套'])
            self.assertEqual(options['defaults']['gpt_id'],'voice_2')
            for r in backend.fixed_scenes():self.assertTrue(backend.fixed_path(r['id']).exists())
if __name__=='__main__':unittest.main(verbosity=2)
