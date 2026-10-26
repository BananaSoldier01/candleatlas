"""Batch collection counterexamples use frozen metadata, synthetic PDF bytes and fake transports."""
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs

from disclosures import annual_identity
from disclosure_fakes import FIXTURE
from scripts.collect_disclosures import BatchCollector,load_roster,selected_rows
from scripts.official_collect import Collector,sha

class Response(io.BytesIO):
    def __init__(self,body,status=200):super().__init__(body);self.status=status;self.headers={}

class CollectDisclosuresTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.lookup=self.root/'lookup';(self.lookup/'raw').mkdir(parents=True)
        self.stocks=[{'code':'001380.SZ','name':'华纬科技'},{'code':'603558.SH','name':'健盛集团'}]
        stocklist={'stockList':[dict(code=s['code'][:6],zwjc=s['name'],category='A股',orgId='fixture-'+s['code'][:6]) for s in self.stocks]}
        body=json.dumps(stocklist).encode();(self.lookup/'raw/list.bin').write_bytes(body)
        (self.lookup/'ledger.json').write_text(json.dumps({'requests':[{'url':'https://www.cninfo.com.cn/new/data/szse_stock.json','ok':True,'raw':'raw/list.bin','sha256':sha(body),'raw_complete':True}]}))
        self.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def payload(self,code):
        rows={}
        for raw in FIXTURE['index_bytes'].values():
            for row in json.loads(raw)['announcements']:
                if row['secCode']==code:rows[str(row['announcementId'])]=copy.deepcopy(row)
        return {'totalAnnouncement':len(rows),'announcements':list(rows.values())}
    def send(self,request,**kwargs):
        self.calls.append(request)
        if request.get_method()=='POST':
            code=parse_qs(request.data.decode())['stock'][0].split(',')[0]
            return Response(json.dumps(self.payload(code)).encode())
        return Response(b'%PDF-1.7\nSYNTHETIC TRANSPORT\n%%EOF')
    def collector(self,send=None):
        return BatchCollector(self.root/'batch',self.stocks,self.lookup,day=dt.date(2026,10,23),pause_s=0,
            collector_factory=lambda path,**kwargs:Collector(path,transport=send or self.send,**kwargs))
    def test_roster_deduplicates_codes_and_rejects_conflicting_names(self):
        path=self.root/'stocks.json';path.write_text(json.dumps({'stocks':self.stocks+self.stocks}))
        self.assertEqual(load_roster(path),self.stocks)
        path.write_text(json.dumps({'stocks':self.stocks+[dict(code='001380.SZ',name='different')]}))
        with self.assertRaises(ValueError):load_roster(path)
    def test_latest_periods_keep_revisions_and_exclude_abstracts_and_opinions(self):
        payload=self.payload('001380');row=copy.deepcopy(payload['announcements'][0]);row.update(announcementId='9999999',announcementTitle='关于2025年年度报告的独立董事意见');payload['announcements'].append(row);payload['totalAnnouncement']+=1
        periods,rows=selected_rows(payload,'001380.SZ',dt.date(2026,10,23))
        self.assertEqual(periods,['2023','2024']);self.assertEqual(len(rows),3)
        self.assertEqual(annual_identity('2025年年度报告（更新版）'),('2025','revised_report'))
        self.assertEqual(annual_identity('关于2025年年度报告的补充更正公告'),('2025','correction_notice'))
        for title in ('2025年年度报告摘要','2025年年度报告审计意见','2025年年度报告英文版','关于2025年年度报告问询函的回复公告'):
            self.assertIsNone(annual_identity(title))
    def test_incomplete_cross_stock_and_duplicate_indices_are_not_complete(self):
        for kind in ('incomplete','stock','duplicate','identity'):
            payload=self.payload('001380')
            if kind=='incomplete':payload['totalAnnouncement']+=1
            if kind=='stock':payload['announcements'][0]['secCode']='999999'
            if kind=='duplicate':payload['announcements'].append(payload['announcements'][0]);payload['totalAnnouncement']+=1
            if kind=='identity':payload['announcements'][0]['announcementId']='../escape'
            with self.subTest(kind=kind),self.assertRaises(ValueError):selected_rows(payload,'001380.SZ',dt.date(2026,10,23))
    def test_collect_then_resume_does_not_refetch_and_detects_frozen_corruption(self):
        with contextlib.redirect_stdout(io.StringIO()):
            first=self.collector().run();second=self.collector().run()
        self.assertEqual(first['status'],'collected');self.assertEqual(second['status'],'collected')
        self.assertEqual(first['actual_requests'],9);self.assertEqual(len(self.calls),9)
        self.assertTrue(all(r.get_header('X-api-key') is None and r.get_header('Authorization') is None for r in self.calls))
        folder=self.root/'batch/001380.SZ';ledger=json.loads((folder/'ledger.json').read_text());(folder/ledger['requests'][0]['raw']).write_bytes(b'corrupt')
        with contextlib.redirect_stdout(io.StringIO()):result=self.collector().run()
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['stocks'][0]['status'],'failed');self.assertEqual(len(self.calls),9)
    def test_rate_limit_stops_entire_batch_and_resumption_without_new_calls(self):
        def blocked(request,**kwargs):self.calls.append(request);return Response(b'rate limited',429)
        with contextlib.redirect_stdout(io.StringIO()):
            first=self.collector(blocked).run();second=self.collector(blocked).run()
        self.assertEqual(first['status'],'stopped');self.assertEqual(second['status'],'stopped');self.assertEqual(len(self.calls),1)
        self.assertEqual(len(first['stocks']),1);self.assertFalse((self.root/'batch/603558.SH').exists())
    def test_repeated_source_failure_across_stocks_cannot_reset_budget(self):
        def broken(request,**kwargs):self.calls.append(request);return Response(b'maintenance',500)
        with contextlib.redirect_stdout(io.StringIO()):result=self.collector(broken).run()
        self.assertEqual(result['status'],'stopped');self.assertEqual(len(self.calls),2)
    def test_no_execute_is_read_only_dry_run(self):
        import subprocess,sys
        path=self.root/'stocks.json';path.write_text(json.dumps({'stocks':self.stocks+self.stocks}))
        target=self.root/'never-created'
        result=subprocess.run([sys.executable,'-B','-m','scripts.collect_disclosures','--stocks',str(path),
            '--lookup-source',str(self.lookup),'--folder',str(target)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['status'],'dry_run');self.assertFalse(target.exists())
