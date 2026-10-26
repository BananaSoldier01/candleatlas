"""Counterexamples for bounded, dated market and issuer gap supplements."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs

from announcement_clues import normalize_notice
from announcement_segments import PROFILE, fill_segments, market_of
from market import DataError
from scripts.official_collect import Collector
from test_announcement_clues import row, Response, NOTICE, DAY


def raw(i,code,day=NOTICE):return {**row(i,day=day),'secCode':code,'orgId':'org'+code}


class SegmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.calls=[];self.mode='normal'
        self.sh=[raw(1,'600001'),raw(2,'600002'),raw(3,'600001')]
        self.sz=[raw(4,'000001')];self.bj=[raw(5,'920001'),raw(6,'920002')]
        self.base=[self.sh[0],self.sh[1],self.sz[0],self.bj[0]]
        def send(request,timeout):
            q=parse_qs(request.data.decode());self.calls.append(q)
            market=q['plate'][0];page=int(q['pageNum'][0]);codes=[x.split(',')[0]for x in q.get('stock',[''])[0].split(';') if x]
            rows={'sh':self.sh[:2],'sz':self.sz,'bj':self.bj}[market];total={'sh':3,'sz':1,'bj':2}[market]
            if codes:rows=[r for r in self.sh if r['secCode']in codes];total=len(rows)
            if self.mode=='ignored'and market=='sz':rows=self.sh;total=3
            if self.mode=='wrong-stock'and codes:rows=[raw(7,'600003')];total=1
            if self.mode=='wrong-day'and codes:rows=[{**r,'announcementTime':row(day=DAY)['announcementTime']}if r['announcementId']==self.sh[2]['announcementId']else r for r in rows]
            if self.mode=='conflict'and codes:rows=[{**r,'announcementTitle':'不同的业绩预告'}if r['announcementId']==self.sh[0]['announcementId']else r for r in rows]
            if self.mode=='totals'and market=='sh'and not codes:total=4
            if self.mode=='reverse-tail'and market=='bj':rows=[self.bj[0]]if page==1 else [self.bj[1]]
            if self.mode=='rate-limit':
                response=Response(b'blocked');response.status=429;return response
            return Response(json.dumps(dict(totalAnnouncement=total,announcements=rows)).encode())
        self.factory=lambda folder,max_requests:Collector(folder,max_requests,transport=send)

    def run_fill(self,collect=True,targets=None):
        docs={}
        for r in self.base:
            d=normalize_notice(r,NOTICE);docs[(d['id'],r['secCode'])]=d
        result=fill_segments(self.folder,self.factory,docs,set(),targets or {('600001','org600001')},NOTICE,6,collect=collect)
        return result,docs

    def test_920_prefix_is_beijing_not_shanghai(self):
        self.assertEqual(market_of('920001'),'bj');self.assertEqual(market_of('900001'),'sh')
        self.assertEqual(market_of('200530'),'sz')

    def test_market_and_issuer_segments_fill_only_verified_gap(self):
        r,docs=self.run_fill()
        self.assertTrue(r['reconciled']);self.assertEqual(r['added'],2);self.assertEqual(len(docs),6)
        self.assertEqual(r['market_counts'],{'sz':1,'sh':3,'bj':2});self.assertEqual(len(self.calls),4)
        self.run_fill();self.run_fill(collect=False);self.assertEqual(len(self.calls),4)

    def test_multi_issuer_batch_reduces_requests_and_checks_all_members(self):
        r,_=self.run_fill(targets={('600001','org600001'),('600002','org600002')})
        self.assertTrue(r['reconciled']);batch=[q['stock'][0]for q in self.calls if q.get('stock')]
        self.assertEqual(batch,['600001,org600001;600002,org600002'])

    def test_unresolved_reverse_boundary_gets_only_one_extra_page(self):
        self.mode='reverse-tail';r,_=self.run_fill()
        self.assertTrue(r['reconciled']);self.assertEqual(len(self.calls),5)
        self.assertEqual([q['pageNum']for q in self.calls if q['plate']==['bj']],[['1'],['2']])

    def test_wrong_date_never_makes_count_reconcile(self):
        self.mode='wrong-day';r,docs=self.run_fill()
        self.assertFalse(r['reconciled']);self.assertEqual(len(docs),5)
        self.assertTrue(all(d['notice_date']==NOTICE for d in docs.values()))

    def test_ignored_market_filter_wrong_issuer_and_conflicts_fail_closed(self):
        for mode in ['ignored','wrong-stock','conflict']:
            self.mode=mode
            with self.subTest(mode=mode),tempfile.TemporaryDirectory()as folder:
                self.folder=Path(folder)
                with self.assertRaises(DataError)as caught:self.run_fill()
                self.assertEqual(caught.exception.reason,'invalid_snapshot')

    def test_drifting_market_totals_do_not_claim_complete(self):
        self.mode='totals';r,_=self.run_fill()
        self.assertFalse(r['reconciled']);self.assertIn('不一致',r['coverage'][-1]['warning'])

    def test_offline_missing_segments_do_not_fetch_or_mark_zero_complete(self):
        r,docs=self.run_fill(collect=False)
        self.assertEqual(self.calls,[]);self.assertFalse(r['reconciled']);self.assertEqual(len(docs),4)
        self.assertFalse((self.folder/PROFILE/'ledger.json').exists())

    def test_hash_tamper_is_rejected_even_during_offline_merge(self):
        self.run_fill();p=next((self.folder/PROFILE/'raw').glob('*.bin'));p.write_bytes(b'bad')
        with self.assertRaises(DataError)as caught:self.run_fill(collect=False)
        self.assertEqual(caught.exception.reason,'invalid_snapshot')

    def test_access_limit_stops_all_other_segment_requests_and_reload(self):
        self.mode='rate-limit';r,_=self.run_fill();self.assertFalse(r['reconciled'])
        self.run_fill();self.assertEqual(len(self.calls),1)

    def test_twelve_request_budget_does_not_restart_for_new_segments(self):
        calls=[];base=[];targets=set()
        for code in range(600001,600016):
            targets.add((str(code),'org'+str(code)))
            base.extend(raw(code*100+i,str(code))for i in range(30))
        def send(request,timeout):
            q=parse_qs(request.data.decode());calls.append(q);codes=[x.split(',')[0]for x in q.get('stock',[''])[0].split(';')if x]
            if q['plate']!=['sh']:rows=[];total=0
            elif codes:rows=[raw(int(codes[0])*100+i,codes[0])for i in range(31)];total=31
            else:rows=base[:30];total=465
            return Response(json.dumps(dict(totalAnnouncement=total,announcements=rows)).encode())
        factory=lambda f,max_requests:Collector(f,max_requests,transport=send)
        def run():
            docs={(str(r['announcementId']),r['secCode']):normalize_notice(r,NOTICE)for r in base}
            return fill_segments(self.folder,factory,docs,set(),targets,NOTICE,465,collect=True)
        r=run();self.assertEqual(len(calls),12);self.assertFalse(r['reconciled'])
        self.assertTrue(any('12次上限'in c['warning']for c in r['coverage']))
        run();self.assertEqual(len(calls),12)
