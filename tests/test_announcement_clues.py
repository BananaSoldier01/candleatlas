import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import Mock

from announcement_clues import AnnouncementClues, normalize_notice, title_keys
from market import DataError
from rankings import Rankings
from scripts.official_collect import Collector
from theme_clues import ThemeClues

DAY, NOTICE = '2026-10-23', '2026-10-22'


def row(i=1, title='2026年三季度报告', day=NOTICE):
    identifier = str(1234000000+i)
    return dict(secCode=f'{600000+i:06d}', secName='测试公司', announcementId=identifier,
                announcementTitle=title, announcementTime=int(dt.datetime.fromisoformat(day+'T12:30:00+08:00').timestamp()*1000),
                adjunctUrl=f'finalpage/{day}/{identifier}.PDF')


class Response(io.BytesIO):
    status = 200
    headers = {'Content-Type':'application/json'}


class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.calls=[];self.mode='normal'
        def transport(request, timeout):
            self.calls.append(request)
            params=parse_qs(request.data.decode());page=int(params['pageNum'][0])
            finance='category_yjyg' in params.get('category',[''])[0]
            count=60 if finance else 150
            start=(page-1)*30
            if self.mode=='duplicate' and page==2:start=0
            rows=[row(start+i+(0 if finance else 100),'2026年三季度报告' if i%2 else '关于股份回购进展的公告') for i in range(1,31)]
            if self.mode=='empty':count=0;rows=[]
            if self.mode=='wrong-day':rows=[row(i,day='2026-10-24')for i in range(1,31)]
            if self.mode=='unmatched':rows=[row(start+i,'股东大会决议公告')for i in range(1,31)]
            if self.mode=='conflict' and page==2:rows[0]=row(101,'2026年三季度报告更正公告')
            return Response(json.dumps(dict(totalAnnouncement=count,announcements=rows,hasMore=True,totalpages=1)).encode())
        self.source=AnnouncementClues(Path(self.tmp.name),lambda folder,max_requests:Collector(folder,max_requests,transport=transport))

    def test_normalizes_identity_source_url_and_conservative_availability(self):
        d=normalize_notice(row(),NOTICE)
        self.assertEqual(d['thscode'],'600001.SH')
        self.assertEqual(d['available_at'],'2026-10-23T00:00:00+08:00')
        self.assertEqual(d['notice_date'],NOTICE)
        self.assertEqual(d['keys'],['cninfo:report'])
        self.assertTrue(d['url'].startswith('https://static.cninfo.com.cn/'))

    def test_stock_prefixes_accept_a_shares_but_exclude_b_shares_and_funds(self):
        for code,suffix in [('000811','SZ'),('301001','SZ'),('600497','SH'),('688001','SH'),('920285','BJ'),('830001','BJ')]:
            self.assertEqual(normalize_notice({**row(),'secCode':code},NOTICE)['thscode'],code+'.'+suffix)
        for code in ['200001','900001','510001','60001','ABCDEF']:
            with self.assertRaises(ValueError):normalize_notice({**row(),'secCode':code},NOTICE)

    def test_mismatched_date_missing_date_and_future_notice_are_rejected(self):
        for patch in [dict(announcementTime=None),dict(announcementTime=True),dict(announcementTime=10**50),dict(announcementTime=row(day='2026-10-24')['announcementTime'])]:
            with self.assertRaises(ValueError):normalize_notice({**row(),**patch},NOTICE)

    def test_url_identity_and_host_cannot_be_forged(self):
        for path in ['https://evil.example/file.pdf','//evil.example/x.pdf','finalpage/2026-10-21/1234000001.PDF','finalpage/2026-10-22/9999999999.PDF','../secret']:
            with self.assertRaises(ValueError):normalize_notice({**row(),'adjunctUrl':path},NOTICE)

    def test_title_rules_do_not_infer_positive_earnings_or_child_company_results(self):
        for title in ['业绩说明会公告','2026年三季度报告（英文版）','中国平安：平安银行2026年第三季度报告','股东大会决议公告','关于签订募集资金监管协议的公告']:
            self.assertEqual(title_keys(title,'中国平安'),[])
        self.assertEqual(title_keys('2026年前三季度业绩预告','测试公司'),['cninfo:forecast'])
        self.assertEqual(title_keys('2026年前三季度业绩快报','测试公司'),['cninfo:express'])
        self.assertEqual(title_keys('2026年第三季度报告更正公告','测试公司'),['cninfo:correction'])

    def test_topic_rules_are_neutral_and_preserve_plans_and_negations_in_original_title(self):
        for title,key in [('关于终止股份回购计划的公告','cninfo:repurchase'),('股东减持计划公告','cninfo:holdings'),('重大项目中标公告','cninfo:contract'),('关于收购资产的公告','cninfo:assets'),('关于投资建设项目的公告','cninfo:investment'),('关于提供担保的公告','cninfo:guarantee')]:
            self.assertIn(key,title_keys(title,'测试公司'))
            self.assertEqual(normalize_notice(row(title=title),NOTICE)['title'],title)

    def test_bounded_pagination_counts_actual_unique_rows_not_reported_page_count(self):
        d=self.source.get(DAY)
        self.assertLessEqual(len(self.calls),50)
        self.assertEqual(d['notice_day'],NOTICE)
        self.assertEqual(d['coverage'][0]['received'],150)
        self.assertTrue(d['coverage'][0]['complete'])
        self.assertFalse(d['limited'])
        self.assertTrue(all(e['available_at'][:10]<=DAY for r in d['item'] for e in r['evidence']))

    def test_all_categories_are_requested_without_seasonal_filter(self):
        self.source.get(DAY)
        self.assertEqual(len(self.calls),5)
        for request in self.calls:
            self.assertEqual(parse_qs(request.data.decode(),keep_blank_values=True)['category'],[''])
            self.assertEqual(parse_qs(request.data.decode())['sortName'],['code'])
            self.assertEqual(parse_qs(request.data.decode())['sortType'],['asc'])

    def test_repeated_whole_page_stops_early_without_retry_on_reload(self):
        self.mode='duplicate';d=self.source.get(DAY)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(d['coverage'][0]['stop'],'repeated_page')
        self.source.get(DAY);self.assertEqual(len(self.calls),2)

    def test_changed_total_stops_with_partial_verified_records(self):
        def send(request,timeout):
            page=int(parse_qs(request.data.decode())['pageNum'][0])
            return Response(json.dumps(dict(totalAnnouncement=60 if page==1 else 61,
                announcements=[row(i) for i in range(1,31)])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY)
        self.assertTrue(d['limited']);self.assertEqual(d['coverage'][0]['received'],30)
        self.assertIn('总量发生变化',d['coverage'][0]['warning'])

    def test_duplicate_across_pages_does_not_stop_when_page_has_new_records(self):
        def send(request,timeout):
            page=int(parse_qs(request.data.decode())['pageNum'][0])
            ids=range(1,31) if page==1 else range(30,60)
            return Response(json.dumps(dict(totalAnnouncement=60,announcements=[row(i)for i in ids])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY);c=d['coverage'][0]
        self.assertEqual((c['received'],c['duplicates'],c['pages']),(59,1,2))
        self.assertTrue(d['limited']);self.assertEqual(c['stop'],'declared_end')

    def test_fifty_page_cap_is_durable_and_segments_have_separate_bound(self):
        calls=[]
        def send(request,timeout):
            q=parse_qs(request.data.decode());page=int(q['pageNum'][0]);calls.append(q)
            empty=q['plate'][0]in ('sz','bj')
            return Response(json.dumps(dict(totalAnnouncement=0 if empty else 2000,
                announcements=[] if empty else [row(i) for i in range((page-1)*30+1,page*30+1)])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY)
        self.assertEqual(sum(q['plate']==['sz;sh;bj']for q in calls),50)
        self.assertLessEqual(len(calls),62);self.assertEqual(d['coverage'][0]['stop'],'page_limit')
        before=len(calls);self.assertTrue(d['limited']);source.get(DAY);source.read(DAY)
        self.assertEqual(len(calls),before)

    def test_mixed_wrong_day_records_are_excluded_and_keep_incomplete(self):
        def send(request,timeout):
            return Response(json.dumps(dict(totalAnnouncement=2,announcements=[row(),row(2,day=DAY)])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY)
        self.assertEqual(d['coverage'][0]['date_rejected'],1)
        self.assertTrue(d['limited']);self.assertEqual(len(d['item']),1)

    def test_short_pages_continue_by_actual_rows_instead_of_requested_page_size(self):
        calls=[]
        def send(request,timeout):
            page=int(parse_qs(request.data.decode())['pageNum'][0]);calls.append(page)
            return Response(json.dumps(dict(totalAnnouncement=40,
                announcements=[row(i)for i in range((page-1)*10+1,page*10+1)])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY)
        self.assertEqual(calls,[1,2,3,4]);self.assertFalse(d['limited'])

    def repair_source(self, mode='normal'):
        calls=[]
        def send(request,timeout):
            q=parse_qs(request.data.decode());calls.append(q)
            if q.get('stock'):
                ids=[1,31];total=2
            else:
                ids=list(range(1,31)) if q['pageNum']==['1'] else [1]+list(range(32,61));total=60
            rows=[{**row(i), 'secCode':'600001','orgId':'990001'}for i in ids]
            if q.get('stock') and mode=='wrong-stock':rows[0]['secCode']='600002'
            if q.get('stock') and mode=='wrong-day':rows[1]=row(31,day=DAY)
            if q.get('stock') and mode=='conflict':rows[0]['announcementTitle']='更改后的业绩预告'
            if q.get('stock') and mode=='large':total=50
            return Response(json.dumps(dict(totalAnnouncement=total,announcements=rows)).encode())
        return AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send)),calls

    def test_issuer_repair_recovers_gap_and_same_budget_replay_is_offline(self):
        source,calls=self.repair_source();d=source.get(DAY)
        self.assertEqual(len(calls),3);self.assertEqual(calls[-1]['stock'],['600001,990001'])
        self.assertEqual(d['repair_added'],1);self.assertEqual(d['unique_verified'],60)
        self.assertTrue(d['pagination_reconciled'])
        source.get(DAY);source.read(DAY);self.assertEqual(len(calls),3)

    def test_issuer_repair_wrong_day_does_not_fill_gap(self):
        source,_=self.repair_source('wrong-day');d=source.get(DAY)
        self.assertEqual(d['repair_added'],0);self.assertFalse(d['pagination_reconciled'])
        self.assertFalse(d['coverage'][-1]['complete'])

    def test_issuer_scope_and_conflicting_content_fail_closed(self):
        for mode in ['wrong-stock','conflict']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory()as folder:
                source,_=self.repair_source(mode);source.directory=Path(folder)
                with self.assertRaises(DataError)as error:source.get(DAY)
                self.assertEqual(error.exception.reason,'invalid_snapshot')

    def test_issuer_partial_query_never_claims_complete(self):
        source,calls=self.repair_source('large');d=source.get(DAY)
        self.assertEqual(len(calls),3);self.assertFalse(d['pagination_reconciled'])
        self.assertFalse(d['coverage'][-1]['complete'])

    def test_observation_days_use_separate_evidence_budgets_and_notice_dates(self):
        calls=[]
        def send(request,timeout):
            q=parse_qs(request.data.decode());notice=q['seDate'][0].split('~')[0];calls.append(notice)
            return Response(json.dumps(dict(totalAnnouncement=1,announcements=[row(day=notice)])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        for day,notice in [('2026-10-20','2026-10-19'),('2026-10-22','2026-10-21'),(DAY,NOTICE)]:
            d=source.get(day);self.assertEqual(d['notice_day'],notice)
            self.assertTrue(all(e['notice_date']==notice and e['available_at'][:10]==day for r in d['item']for e in r['evidence']))
            source.get(day);source.read(day)
        self.assertEqual(calls,['2026-10-19','2026-10-21',NOTICE])

    def test_budget_exhaustion_is_not_reported_as_upstream_query_failure(self):
        with self.assertRaises(DataError)as caught:
            AnnouncementClues.payload(Path(self.tmp.name),{'stop':'budget_exhausted'},'unused')
        self.assertEqual(caught.exception.reason,'budget_exhausted')
        self.assertIn('尚未采集',str(caught.exception))

    def test_wrong_date_out_of_scope_security_cannot_make_totals_reconcile(self):
        def send(request,timeout):
            return Response(json.dumps(dict(totalAnnouncement=2,announcements=[row(),{**row(2,day=DAY),'secCode':'200530'}])).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY);self.assertEqual(d['excluded_non_a'],0)
        self.assertFalse(d['pagination_reconciled'])

    def test_main_scan_and_ordinary_repair_share_fifty_calls_then_segments_are_bounded(self):
        calls=[]
        def send(request,timeout):
            q=parse_qs(request.data.decode());page=int(q['pageNum'][0]);calls.append(q)
            rows=[{**row(i),'secCode':'600001','orgId':'990001'}for i in range((page-1)*30+1,page*30+1)]
            if page==2:rows[0]={**row(1),'secCode':'600001','orgId':'990001'}
            empty=q['plate'][0]in ('sz','bj')
            return Response(json.dumps(dict(totalAnnouncement=0 if empty else 1600,announcements=[] if empty else rows)).encode())
        source=AnnouncementClues(self.tmp.name,lambda f,max_requests:Collector(f,max_requests,transport=send))
        d=source.get(DAY)
        main=[q for q in calls if q['plate']==['sz;sh;bj']]
        self.assertEqual(len(main),50);self.assertTrue(all(not q.get('stock')for q in main))
        self.assertFalse(d['pagination_reconciled']);self.assertIn('尚未采集',d['coverage'][1]['warning'])
        self.assertLessEqual(len(calls),62)
        before=len(calls);source.get(DAY);self.assertEqual(len(calls),before)

    def legacy(self, announcement):
        from urllib.parse import urlencode
        from announcement_clues import INDEX
        folder=Path(self.tmp.name)/DAY
        c=Collector(folder,max_requests=6,transport=lambda *a,**kw:Response(json.dumps(dict(totalAnnouncement=1,announcements=[announcement])).encode()))
        query=self.source.query(NOTICE,'all',1)
        query.update(category='category_yjyg_szsh;category_yjkb_szsh;category_sjdbg_szsh;',sortName='time',sortType='desc')
        c.fetch(INDEX,method='POST',data=urlencode(query))
        return folder

    def test_old_verified_category_samples_are_preserved_and_deduplicated(self):
        self.legacy(row(999))
        d=self.source.get(DAY)
        self.assertEqual(d['legacy_added'],1)
        self.assertIn('600999.SH',[r['thscode']for r in d['item']])
        self.assertEqual(d['unique_verified'],151)
        self.assertEqual(len(self.calls),5)

    def test_legacy_only_history_is_offline_and_missing_new_profile_is_not_zero(self):
        self.legacy(row(999));d=self.source.read(DAY)
        self.assertEqual(self.calls,[]);self.assertTrue(d['limited'])
        self.assertEqual(d['legacy_added'],1);self.assertIsNotNone(d['fetched_at'])

    def test_legacy_sha_and_conflicting_identity_are_rejected(self):
        folder=self.legacy(row(101,'不同的业绩预告'))
        with self.assertRaises(DataError):self.source.get(DAY)
        raw=next((folder/'raw').glob('*.bin'));raw.write_bytes(b'corrupt')
        with self.assertRaises(DataError)as error:self.source.read(DAY)
        self.assertEqual(error.exception.reason,'invalid_snapshot')

    def test_loaded_evidence_is_replayed_without_network(self):
        first=self.source.get(DAY);calls=len(self.calls)
        second=self.source.get(DAY);read=self.source.read(DAY)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(second['snapshot_source'],'local')
        self.assertEqual(first['item'],read['item'])

    def test_duplicate_pages_are_deduplicated_and_never_marked_complete(self):
        self.mode='duplicate';d=self.source.get(DAY)
        self.assertTrue(d['limited']);self.assertEqual(d['coverage'][0]['duplicates'],30)
        self.assertFalse(d['coverage'][0]['complete'])
        ids=[(e['id'],e['thscode']) for r in d['item'] for e in r['evidence']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertLessEqual(len(self.calls),50)

    def test_conflicting_versions_of_same_announcement_fail_closed(self):
        self.mode='conflict'
        with self.assertRaises(DataError) as caught:self.source.get(DAY)
        self.assertEqual(caught.exception.reason,'invalid_snapshot')

    def test_sha_tampering_blocks_both_live_and_offline_replay(self):
        self.source.get(DAY)
        raw=next((Path(self.tmp.name)/DAY).rglob('*.bin'));raw.write_bytes(raw.read_bytes()+b' ')
        for action in [self.source.get,self.source.read]:
            with self.assertRaises(DataError) as caught:action(DAY)
            self.assertEqual(caught.exception.reason,'invalid_snapshot')

    def test_empty_source_is_not_persisted_as_no_market_events(self):
        self.mode='empty'
        with self.assertRaises(DataError) as caught:self.source.get(DAY)
        self.assertEqual(caught.exception.reason,'upstream_empty')

    def test_access_failure_is_not_labelled_as_empty_and_is_not_retried(self):
        calls=[]
        def denied(request,timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url,403,'Forbidden',{},io.BytesIO(b'blocked'))
        source=AnnouncementClues(Path(self.tmp.name),lambda folder,max_requests:Collector(folder,max_requests,transport=denied))
        for _ in range(2):
            with self.assertRaises(DataError) as caught:source.get(DAY)
            self.assertEqual(caught.exception.reason,'source_failed')
        self.assertEqual(len(calls),1)

    def test_all_wrong_day_rows_are_distinct_from_empty_source(self):
        self.mode='wrong-day'
        with self.assertRaises(DataError) as caught:self.source.get(DAY)
        self.assertEqual(caught.exception.reason,'date_mismatch')

    def test_valid_but_unmatched_titles_are_distinct_from_missing_source(self):
        self.mode='unmatched'
        with self.assertRaises(DataError) as caught:self.source.get(DAY)
        self.assertEqual(caught.exception.reason,'no_matching_evidence')

    def test_read_missing_day_never_fetches_and_invalid_paths_are_rejected(self):
        self.assertIsNone(self.source.read('2026-10-22'));self.assertEqual(self.calls,[])
        for day in ['../secret','bad','2026-02-30']:
            with self.assertRaises(DataError):self.source.read(day)

    def test_public_queries_use_only_cninfo_without_credentials_or_models(self):
        self.source.get(DAY)
        for request in self.calls:
            self.assertEqual(request.full_url,'https://www.cninfo.com.cn/new/hisAnnouncement/query')
            headers={k.lower() for k in request.headers}
            self.assertFalse(headers & {'authorization','cookie','x-api-key'})
            self.assertEqual(parse_qs(request.data.decode())['seDate'],[NOTICE+'~'+NOTICE])

    def test_theme_and_finance_fallback_use_verified_title_evidence(self):
        market=Mock(cache_dir=Path(self.tmp.name)/'quotes');market.calendar.return_value=['2026-10-22',DAY]
        market.cache_dir.mkdir();rankings=Rankings(market)
        market.get.return_value=dict(timestamp=int(dt.datetime.fromisoformat('2026-10-24T12:00:00+08:00').timestamp()*1000),item=[])
        themes=ThemeClues(market,rankings,self.source)
        catalog=themes.catalog(DAY,'finance')
        self.assertEqual(catalog['source_kind'],'cninfo');self.assertFalse(catalog['limited'])
        self.assertIn('公告日 '+NOTICE,catalog['source_summary'])
        detail=themes.detail(DAY,'finance','cninfo:report')
        self.assertTrue(detail['items']);self.assertTrue(detail['items'][0]['evidence'])
        self.assertEqual(detail['items'][0]['analysis'],'')
        self.assertIsNone(detail['items'][0]['pct'])
        self.assertIn('上游为空',detail['quote_warning'])
        self.assertFalse((rankings.directory/(DAY+'-anomaly.json')).exists())

    def test_original_valid_source_is_not_overwritten_by_announcement_source(self):
        market=Mock();market.calendar.return_value=[DAY];rankings=Mock()
        rankings.read.return_value=dict(timestamp=row()['announcementTime']+24*3600*1000,item=[dict(thscode='600001.SH',keyword_list=['芯片'])])
        secondary=Mock();catalog=ThemeClues(market,rankings,secondary).catalog(DAY,'topics')
        self.assertEqual(catalog['items'][0]['name'],'芯片');secondary.get.assert_not_called()

    def test_announcement_history_never_mixes_with_anomaly_cohort_or_fetches_missing_days(self):
        self.source.get(DAY);calls=len(self.calls)
        market=Mock();market.calendar.return_value=['2026-10-21','2026-10-22',DAY]
        result=ThemeClues(market,Mock(),self.source).history(DAY,'finance','cninfo:report')
        self.assertEqual(result['tracking_mode'],'announcements')
        self.assertEqual([x['count'] for x in result['items'][:2]],[None,None])
        self.assertGreater(result['items'][-1]['count'],0)
        self.assertNotIn('entered',result);self.assertNotIn('average',result)
        self.assertEqual(len(self.calls),calls)
