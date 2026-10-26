"""Transport counterexamples use only temporary files and fake openers."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from scripts.official_collect import Collector

URL='https://www.sse.com.cn/public'
class Response(io.BytesIO):
    def __init__(self,body=b'ok',status=200,headers=None):
        super().__init__(body);self.status=status;self.headers=headers or {}

class OfficialCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_post_headers_body_retained_and_replayed(self):
        calls=[]
        def send(request,**kw):
            calls.append(request);return Response(b'{"announcements":[]}')
        collector=Collector(self.folder,transport=send)
        result=collector.fetch(URL,method='POST',data='stock=600000',headers={'Referer':'https://www.sse.com.cn/','Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(calls[0].get_header('Referer'),'https://www.sse.com.cn/')
        self.assertEqual(calls[0].data,b'stock=600000')
        self.assertEqual(result['request_body_utf8'],'stock=600000')
        self.assertEqual(collector.replay()['matched'],1)
        self.assertEqual(Collector(self.folder).data['requests'][0],result)
    def test_error_body_frozen_and_failure_stop_enforced(self):
        calls=[]
        def send(request,**kw):
            calls.append(request)
            raise urllib.error.HTTPError(URL,500,'error',{'Content-Type':'text/html'},io.BytesIO(b'maintenance'))
        collector=Collector(self.folder,transport=send)
        result=collector.fetch(URL)
        self.assertEqual((self.folder/result['raw']).read_bytes(),b'maintenance')
        self.assertFalse(result['ok']);self.assertEqual(collector.replay()['status'],'pass')
        collector.fetch(URL)
        self.assertEqual(collector.fetch(URL)['stop'],'repeated_source_failure')
        self.assertEqual(len(calls),2)
    def test_redirects_count_and_budget_does_not_grow(self):
        calls=[]
        def send(request,**kw):
            calls.append(request);return Response(b'redirect',302,{'Location':URL+'/next'})
        collector=Collector(self.folder,max_requests=2,transport=send)
        self.assertEqual(collector.fetch(URL)['stop'],'budget_exhausted')
        self.assertEqual(len(calls),2)
        for _ in range(3): collector.fetch(URL)
        self.assertEqual(len(collector.data['requests']),2)
        self.assertEqual(collector.replay()['matched'],2)
    def test_forbidden_and_rate_limit_stop_without_retry(self):
        for status in (401,402,403,429):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                calls=[]
                def send(*a,**k): calls.append(1);return Response(b'blocked',status)
                collector=Collector(folder,transport=send);collector.fetch(URL)
                self.assertEqual(collector.fetch(URL)['stop'],'access_or_rate_limit')
                self.assertEqual(calls,[1])
    def test_crash_reservation_counts_missing_response_and_hash_tamper_fails(self):
        def crash(*a,**kw): raise KeyboardInterrupt()
        collector=Collector(self.folder,transport=crash)
        with self.assertRaises(KeyboardInterrupt): collector.fetch(URL)
        self.assertEqual(Collector(self.folder).replay()['status'],'unverified')
        collector.transport=lambda *a,**kw:Response();result=collector.fetch(URL)
        (self.folder/result['raw']).write_bytes(b'corrupt')
        self.assertEqual(collector.replay()['status'],'failed')
    def test_credentials_and_external_redirect_rejected(self):
        collector=Collector(self.folder,transport=lambda *a,**kw:Response(b'',302,{'Location':'https://example.com/'}))
        with self.assertRaises(ValueError): collector.fetch(URL,headers={'Cookie':'secret'})
        with self.assertRaises(ValueError): collector.fetch(URL+'?token=secret')
        with self.assertRaises(ValueError): collector.fetch(URL)
        self.assertEqual(len(collector.data['requests']),1)
        self.assertEqual(collector.replay()['matched'],1)
    def test_http_200_challenge_is_not_pdf_and_stops(self):
        import gzip
        collector=Collector(self.folder,transport=lambda *a,**kw:Response(gzip.compress(b'<script>challenge</script>')))
        first=collector.fetch(URL+'.PDF')
        self.assertEqual(first['result'],'unexpected_content')
        self.assertFalse(first['ok'])
        collector.fetch(URL,expect='pdf')
        self.assertEqual(collector.fetch(URL,expect='pdf')['stop'],'repeated_source_failure')
        self.assertEqual(collector.replay()['matched'],2)
    def test_oversized_response_retains_explicitly_incomplete_bytes(self):
        collector=Collector(self.folder,transport=lambda *a,**kw:Response(b'%PDF-abcdefghijk'))
        result=collector.fetch(URL,expect='pdf',max_bytes=10)
        self.assertEqual(result['result'],'response_too_large')
        self.assertFalse(result['raw_complete'])
        self.assertEqual(collector.replay()['status'],'incomplete')
        self.assertEqual(collector.replay()['matched'],1)
    def test_cli_defaults_to_dry_run_without_writing_or_network(self):
        import subprocess
        import sys
        result=subprocess.run([sys.executable,'-B','-m','scripts.official_collect','--folder',str(self.folder),'--url',URL],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual(json.loads(result.stdout)['status'],'dry_run')
        self.assertEqual(list(self.folder.iterdir()),[])
