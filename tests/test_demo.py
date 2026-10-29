"""Synthetic read-only demo: no credentials, external I/O, model or user database."""
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch
from demo import Demo,NOTICE
from server import Handler
from analysis import technical


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.demo=Demo();self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http.demo=self.demo
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
    def request(self,path,method='GET',body=None):
        c=HTTPConnection('127.0.0.1',self.http.server_port,timeout=10)
        c.request(method,path,body=json.dumps(body)if body is not None else None,headers={'Origin':f'http://127.0.0.1:{self.http.server_port}','Content-Type':'application/json'})
        r=c.getresponse();text=r.read();status=r.status;c.close();return status,json.loads(text)
    def test_reads_need_no_network_key_or_database(self):
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')),patch('market.load_key',side_effect=AssertionError('key forbidden')),patch('sqlite3.connect',side_effect=AssertionError('database forbidden')):
            observed=self.demo.observed(self.demo.day)
            follow=f'/api/followup?code=600000.SH&observed={observed}&date={self.demo.day}'
            for path in ['/api/calendar','/api/workbench?date='+self.demo.day,'/api/prices?code=600000.SH&date='+self.demo.day+'&context=1','/api/observations','/api/overview?date='+self.demo.day, follow, follow+'&id=demo-record-0']:
                self.assertEqual(self.request(path)[0],200,path)
    def test_post_is_refused_before_any_write(self):
        for path in ['/api/analysis','/api/model-settings/test','/api/model-settings','/api/settings','/api/batch','/api/observations','/api/sync-day','/api/followup']:
            status,d=self.request(path,'POST',{});self.assertEqual(status,403,path);self.assertEqual(d['reason'],'demo_read_only')
    def test_demo_is_clearly_synthetic(self):
        _,r=self.request('/api/runtime');self.assertTrue(r['synthetic']);self.assertTrue(r['read_only']);self.assertEqual(r['mode'],'demo')
        self.assertTrue(all('合成'in s['name']for s in self.demo.quotes(self.demo.day)))
    def test_report_uses_production_calculator_and_delta(self):
        r=self.demo.report('600000.SH',self.demo.day);rows=self.demo.market.prices('600000.SH',self.demo.day,250)['items']
        self.assertEqual(r['report']['technical'],technical(rows));self.assertTrue(r['delta']['rows']);self.assertIsNone(r['report']['ai']);self.assertIn(NOTICE,r['report']['limitations'])
    def test_unknown_date_or_stock_cannot_borrow_data(self):
        for path in ['/api/prices?code=600000.SH&date=2099-01-01','/api/prices?code=600001.SH&date='+self.demo.day]:self.assertEqual(self.request(path)[0],502)
    def test_demo_status_contains_no_key(self):
        for path in ['/api/settings','/api/model-settings']:
            _,d=self.request(path);self.assertFalse(d['configured']);self.assertNotIn('key',d)
    def test_uncovered_feature_remains_missing(self):
        status,d=self.request('/api/intraday');self.assertEqual(status,502);self.assertIn('未覆盖',d['error'])
    def test_report_roundtrip_is_deterministic(self):
        r=self.demo.report('600000.SH',self.demo.day);self.assertEqual(self.request('/api/analysis?id='+r['id'])[1],r);self.assertEqual(self.demo.report('600000.SH',self.demo.day),r)

    def test_followup_review_is_optional_and_synthetic(self):
        observed=self.demo.observed(self.demo.day);day=self.demo.day
        status,plain=self.request(f'/api/followup?code=600000.SH&observed={observed}&date={day}')
        self.assertEqual(status,200);self.assertEqual(set(plain),{'items','baseline','observed','end'})
        status,reviewed=self.request(f'/api/followup?code=600000.SH&observed={observed}&date={day}&id=demo-record-0')
        self.assertEqual(status,200);self.assertEqual(reviewed['items'],plain['items']);self.assertIn('watch_review',reviewed)
        self.assertEqual(len(reviewed['watch_review']['items']),2)
        self.assertIn('前复权',reviewed['watch_review']['note'])
        _,observations=self.request('/api/observations')
        for item in observations['items']:self.assertTrue(1<=len(item['watch_points'])<=2)
        _,desk=self.request('/api/workbench?date='+day)
        for item in desk['items']:self.assertTrue(item['watch_points'])
        report=self.demo.report('600000.SH',day)
        self.assertIsInstance(report['reading_notes'],list)
        self.assertEqual(self.request('/api/analysis?id='+report['id'])[1]['reading_notes'],report['reading_notes'])

    def test_private_files_are_not_served_in_demo(self):
        for path in ['/.env.local','/data/model-config.json','/../settings.py']:
            c=HTTPConnection('127.0.0.1',self.http.server_port,timeout=10);c.request('GET',path);response=c.getresponse();response.read();self.assertEqual(response.status,404);c.close()
