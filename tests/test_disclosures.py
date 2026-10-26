"""Local disclosure evidence, historical boundaries and real Handler/report integration."""
import copy
import datetime as dt
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
from disclosures import DisclosureStore
from server import Handler
from disclosure_fakes import fixture_bundle,fake_analysis

class DisclosureStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name);self.catalog=fixture_bundle(self.folder/'bundle');self.store=DisclosureStore(self.folder/'bundle')
    def tearDown(self):self.tmp.cleanup()
    def save(self): (self.store.folder/'catalog.json').write_text(json.dumps(self.catalog,ensure_ascii=False))
    def test_four_originals_before_on_after_date_and_two_revisions(self):
        originals=[x for x in self.catalog['documents'] if x['document_kind']=='annual_report']
        self.assertEqual(len(originals),4)
        for doc in originals:
            code=doc['stock_code']+'.'+doc['exchange'];day=doc['notice_date'];period=doc['period_end']
            self.assertEqual(self.store.query(code,day,period)['status'],'not_yet_available')
            after=(dt.date.fromisoformat(day)+dt.timedelta(days=1)).isoformat()
            self.assertEqual(self.store.query(code,after,period)['items'][0]['id'],doc['id'])
        for code,before,after,old,new in [('603558.SH','2025-07-12','2025-07-13','1222880535','1224144675'),
                                        ('001380.SZ','2025-04-28','2025-04-29','1223045300','1223321707')]:
            original=self.store.query(code,before,'2024-4');revised=self.store.query(code,after,'2024-4')
            self.assertEqual(original['items'][0]['id'],old)
            self.assertNotIn(new,json.dumps(original))
            self.assertEqual(revised['items'][0]['id'],new)
            self.assertIn(old,[x['id'] for x in revised['versions']])
    def test_uncached_stock_period_unconfigured_and_invalid_inputs(self):
        self.assertEqual(DisclosureStore(self.folder/'missing').query('603558.SH','2025-01-01','2024-4')['status'],'unconfigured')
        for code in ('600000.SH','603558.SZ'):self.assertEqual(self.store.query(code,'2025-01-01','2024-4')['status'],'uncovered')
        self.assertEqual(self.store.query('603558.SH','2025-01-01','2024-3')['status'],'period_not_covered')
        for code,day,period in [('bad','2025-01-01','2024-4'),('603558.SH','bad','2024-4'),('603558.SH','2025-01-01','2024-5')]:
            with self.assertRaises(ValueError):self.store.query(code,day,period)
    def test_corrupt_pdf_and_index_fail_closed(self):
        doc=self.catalog['documents'][0];path=self.store.folder/doc['pdf_path'];original=path.read_bytes();path.write_bytes(original+b'corrupt')
        self.assertEqual(self.store.query('603558.SH','2025-07-13','2024-4')['status'],'failed')
        path.write_bytes(original)
        proof=next(iter(self.catalog['index_evidence'].values()));(self.store.folder/proof['path']).write_bytes(b'wrong')
        self.assertEqual(self.store.query('603558.SH','2025-07-13','2024-4')['items'],[])
    def test_semantic_tampering_paths_and_orphan_revisions_rejected(self):
        before=copy.deepcopy(self.catalog)
        for field,value in [('stock_code','999999'),('available_at','2000-01-01T00:00:00+08:00'),('period_end','2022-12-31'),
                            ('title','wrong'),('exchange','SH'),('pdf_path','../catalog.json')]:
            self.catalog=copy.deepcopy(before);self.catalog['documents'][0][field]=value;self.save()
            self.assertEqual(self.store.query('603558.SH','2025-07-13','2024-4')['status'],'failed',field)
        self.catalog=copy.deepcopy(before)
        next(x for x in self.catalog['documents'] if x['document_kind']=='revised_report')['previous_report_id']='wrong'
        self.save();self.assertEqual(self.store.query('603558.SH','2025-07-13','2024-4')['status'],'failed')
    def test_public_result_has_no_local_paths_future_urls_or_numeric_values(self):
        result=self.store.query('603558.SH','2025-03-26','2024-4');encoded=json.dumps(result)
        for word in ('pdf_path','request_headers','index_evidence','1224144675','1224144674'):self.assertNotIn(word,encoded)
        self.assertIsNone(result['financial_values'])
        self.assertEqual(result['items'][0]['published_precision'],'date')
    def test_two_stocks_same_period_do_not_mix_corrections(self):
        first=self.store.query('603558.SH','2025-07-13','2024-4');second=self.store.query('001380.SZ','2025-07-13','2024-4')
        self.assertEqual(len(first['items']),2);self.assertEqual(len(second['items']),1)
        self.assertTrue(all(x['stock_code']=='001380' for x in second['items']))

class DisclosureHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.analysis=fake_analysis(Path(self.tmp.name))
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http.disclosures=self.analysis.disclosures;self.http.analysis=self.analysis
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.thread.join(2);self.http.server_close();self.analysis.model.complete.assert_not_called();self.tmp.cleanup()
    def get(self,code='603558.SH',day='2025-03-26',report='2024-4'):
        conn=HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        try:
            conn.request('GET','/api/disclosures?'+urlencode({'code':code,'date':day,'report':report}))
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()
    def test_actual_handler_is_local_only_and_bad_date_is_400(self):
        status,result=self.get();self.assertEqual(status,200);self.assertEqual(result['items'][0]['id'],'1222880535')
        self.assertEqual(self.get(day='bad')[0],400)
        self.analysis.market.prices.assert_not_called();self.analysis.themes.financial.assert_not_called()
    def test_historical_report_saves_filtered_materials_without_current_financial(self):
        with patch('analysis.today',return_value='2026-10-23'):
            job=self.analysis.start({'code':'603558.SH','date':'2025-03-26','name':'合成测试','report':'2024-4','ai':False})
            for _ in range(150):
                result=self.analysis.get(job['id'])
                if result['status']!='running':break
                time.sleep(.01)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['report']['disclosures']['items'][0]['id'],'1222880535')
        self.assertTrue(any(x['id']=='D1' for x in result['report']['evidence']))
        self.analysis.themes.financial.assert_not_called()
        old=json.dumps(result['report']['disclosures'],sort_keys=True)
        (self.http.disclosures.folder/'catalog.json').write_text('{}')
        self.assertEqual(json.dumps(self.analysis.get(job['id'])['report']['disclosures'],sort_keys=True),old)
    def test_corrupt_bundle_does_not_break_technical_report(self):
        (self.http.disclosures.folder/'catalog.json').write_text('{}')
        self.assertEqual(self.get()[1]['status'],'failed')
        with patch('analysis.today',return_value='2026-10-23'):
            job=self.analysis.start({'code':'603558.SH','date':'2025-03-26','report':'2024-4','ai':False})
            for _ in range(150):
                result=self.analysis.get(job['id'])
                if result['status']!='running':break
                time.sleep(.01)
        self.assertEqual(result['status'],'complete');self.assertIsNotNone(result['report']['technical'])
        self.assertEqual(result['report']['disclosures']['status'],'failed')
