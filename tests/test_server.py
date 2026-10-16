import concurrent.futures, http.client, json, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch, Mock
from http.server import ThreadingHTTPServer
from workbench import server

class ServerTests(unittest.TestCase):
    def test_upload_save_range_and_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);jobs=Mock()
            with patch.object(server,'DATA',root),patch.object(server,'JOBS',jobs),patch.object(server.semantic,'settings_dir',return_value=root/'.settings'):
                srv=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);port=srv.server_address[1]
                with patch.object(server,'PORT',port):
                    t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
                    def request(method,path,body=None,headers=None):
                        c=http.client.HTTPConnection('127.0.0.1',port);c.request(method,path,body=body,headers=headers or {});r=c.getresponse();content=r.read();status=r.status;c.close();return status,content
                    try:
                        fake_key='sk-test-only-not-a-real-credential'
                        status,_=request('POST','/api/deepseek',json.dumps({'api_key':fake_key}));self.assertEqual(status,200)
                        status,body=request('GET','/api/deepseek');self.assertEqual(status,200);self.assertNotIn(fake_key.encode(),body);self.assertTrue(json.loads(body)['configured'])
                        status,body=request('POST','/api/projects',json.dumps({'filename':'example.mp4','options':{}}),{'Content-Type':'application/json'});self.assertEqual(status,201);pid=json.loads(body)['id']
                        status,_=request('POST',f'/api/projects/{pid}/video',b'fake upload');self.assertEqual(status,200);self.assertEqual(jobs.submit.call_count,1)
                        self.assertEqual((root/pid/'upload.bin').read_bytes(),b'fake upload')
                        (root/pid/'original.mp4').write_bytes(b'0123456789')
                        status,body=request('GET',f'/p/{pid}/original.mp4',headers={'Range':'bytes=2-5'});self.assertEqual((status,body),(206,b'2345'))
                        status,_=request('POST','/api/projects','{}',{'Origin':'https://untrusted.example'});self.assertEqual(status,403)
                        status,_=request('GET',f'/p/{pid}/%2e%2e/status.json');self.assertEqual(status,403)
                        status,body=request('POST',f'/p/{pid}/export/srt',json.dumps({'content':'example subtitle'}));self.assertEqual(status,200);self.assertEqual((root/pid/'字幕_已修改.srt').read_text(),'example subtitle')
                    finally:srv.shutdown();srv.server_close();t.join()

if __name__=='__main__':unittest.main()
