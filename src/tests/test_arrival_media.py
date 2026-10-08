import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from workbench.server import WorkbenchServer, STATIC

class ArrivalMediaChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='hebao-arrival-',dir=Path(__file__).resolve().parents[1]/'verification/arrival_v23')
        cls.server=WorkbenchServer(cls.tmp.name)
        cls.worker=threading.Thread(target=cls.server.serve,daemon=True)
        cls.worker.start()
        cls.media=(STATIC/'arrival_v23.webm').read_bytes()
    @classmethod
    def tearDownClass(cls):
        cls.server.stop();cls.worker.join(9);cls.server.server_close();cls.tmp.cleanup()
    def get(self,path='/arrival_v23.webm',headers=None,method='GET'):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            c.request(method,path,headers=headers or {})
            r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def test_full_media_exact_and_local_csp(self):
        status,headers,body=self.get()
        self.assertEqual((status,body),(200,self.media))
        self.assertEqual(headers['Content-Type'],'video/webm')
        self.assertIn("media-src 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Accept-Ranges'],'bytes')
    def test_head_has_size_without_body(self):
        status,headers,body=self.get(method='HEAD')
        self.assertEqual((status,len(body)),(200,0))
        self.assertEqual(int(headers['Content-Length']),len(self.media))
    def test_closed_open_suffix_and_clamped_ranges(self):
        size=len(self.media)
        for value,start,end in [('bytes=0-1023',0,1023),('bytes=1024-',1024,size-1),('bytes=-256',size-256,size-1),('bytes=10-999999999',10,size-1)]:
            with self.subTest(value=value):
                status,h,body=self.get(headers={'Range':value})
                self.assertEqual(status,206)
                self.assertEqual(body,self.media[start:end+1])
                self.assertEqual(h['Content-Range'],f'bytes {start}-{end}/{size}')
    def test_invalid_or_multi_ranges_fail_bounded(self):
        for value in ['bytes=999999999-','bytes=10-1','bytes=-0','bytes=-','bytes=0-1,5-8','items=0-1','bytes=foo-bar']:
            with self.subTest(value=value):
                status,h,body=self.get(headers={'Range':value})
                self.assertEqual((status,body),(416,b''))
                self.assertEqual(h['Content-Range'],f'bytes */{len(self.media)}')
    def test_exit_reclaims_stalled_video_workers(self):
        server=WorkbenchServer(Path(self.tmp.name)/'close_case')
        worker=threading.Thread(target=server.serve,daemon=True);worker.start()
        c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        c.request('GET','/arrival_v23.webm');r=c.getresponse();r.read(1024)
        server.stop();worker.join(2);server.server_close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(server.request_workers,{})
        r.close();c.close()
    def test_cross_site_and_path_escape_still_rejected(self):
        self.assertEqual(self.get(headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.get(headers={'Origin':'https://example.invalid'})[0],403)
        self.assertEqual(self.get(path='/../arrival_v23.webm')[0],404)
        self.assertEqual(self.get(path='/private.webm')[0],404)
    def test_page_assets_and_api_after_skipped_transfer(self):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        c.request('GET','/arrival_v23.webm');r=c.getresponse();r.read(1024)
        # Keep the video reader stalled: page and API must still respond.
        for path in ['/','/arrival.js','/arrival.css','/arrival_bootstrap.js']:
            self.assertEqual(self.get(path=path)[0],200)
        stalled_c,stalled_r=c,r
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            c.request('POST','/api/call',json.dumps({'command':'state.summary','params':{}}),{'Content-Type':'application/json','Authorization':'Bearer '+self.server.token})
            r=c.getresponse();self.assertEqual(r.status,200);self.assertIn('result',json.loads(r.read()))
        finally:
            c.close();stalled_r.close();stalled_c.close()

if __name__=='__main__':unittest.main()
