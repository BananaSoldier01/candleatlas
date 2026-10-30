"""East Money pool backup: synthetic JSON only. No live HTTP, .env, or user database."""
import json
import urllib.error
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import em_market_backup as em
from server import Handler

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'em_pools'
DAY = '2026-10-29'


def load(name):
    return (FIXTURE / name).read_bytes()


def forbidden(text):
    for word in ('买入', '卖出', '荐股', '更准', '胜率', '目标价'):
        if word in text:
            return word
    return None


class PoolTests(unittest.TestCase):
    def setUp(self):
        em.reset_rate_gate()
        self.addCleanup(em.reset_rate_gate)

    def test_default_is_offline(self):
        def boom(*_a, **_k):
            raise AssertionError('network forbidden')
        with patch('em_market_backup._http_get', boom), patch('urllib.request.urlopen', boom):
            result = em.fetch_limit_pool(DAY, sleeper=boom, fetch=boom)
            breadth = em.fetch_market_breadth(sleeper=boom, fetch=boom)
        self.assertEqual(result['source'], 'eastmoney')
        self.assertEqual(result['items'], [])
        self.assertIsNone(result['day'])
        self.assertIn('未联网', result['gaps'][0])
        self.assertIn('getTopicZTPool', result['gaps'][0])
        self.assertIn('不认历史日', breadth['gaps'][0])
        self.assertIsNone(breadth['day'])
        self.assertTrue(result['license_note'])
        self.assertGreaterEqual(em.MIN_INTERVAL_SECONDS, 1)
        self.assertIn(str(int(em.MIN_INTERVAL_SECONDS)), result['rate_limit_note'])

    def test_pool_metadata_is_present_on_every_failure_path(self):
        def fail_fetch(_url):
            raise OSError('synthetic failure')

        cases = (
            ('offline', {}),
            ('bad_json', {'fetch_bytes': b'{bad json'}),
            ('bad_encoding', {'fetch_bytes': b'\xff'}),
            ('json_null', {'fetch_bytes': b'null'}),
            ('json_list', {'fetch_bytes': b'[]'}),
            ('rc_error', {'fetch_bytes': b'{"rc":1}'}),
            ('data_missing', {'fetch_bytes': b'{}'}),
            ('data_null', {'fetch_bytes': b'{"data":null}'}),
            ('data_wrong_shape', {'fetch_bytes': b'{"data":[] }'}),
            ('fetch_error', {'allow_network': True, 'fetch': fail_fetch}),
            ('fetched_bad_json', {'allow_network': True, 'fetch': lambda _url: b'bad json'}),
            ('fetched_non_bytes', {'allow_network': True, 'fetch': lambda _url: 'not bytes'}),
        )
        for kind in ('up', 'break', 'down'):
            for label, kwargs in cases:
                with self.subTest(kind=kind, case=label), patch('em_market_backup._http_get', side_effect=AssertionError('no network')):
                    value = em.fetch_limit_pool(DAY, kind, clock=lambda: 0,
                                                sleeper=lambda _seconds: None, **kwargs)
                    # 模拟调用方直接索引以及 HTTP JSON 序列化，不能依赖 .get() 掩盖漏字段。
                    value = json.loads(json.dumps(value))
                    self.assertIs(value['list_complete'], False)
                    self.assertEqual(value['date_basis'], 'unverified')
                    self.assertEqual(value['requested_day'], DAY)
                    self.assertIsNone(value['upstream_qdate'])
                    self.assertEqual(value['latest_price_unit'], 'CNY')
                    self.assertIsNone(value['day'])
                    self.assertEqual(value['items'], [])
                    self.assertTrue(value['gaps'])
                    self.assertEqual(value['kind'], kind)

    def test_bad_switches_do_not_connect(self):
        def boom(*_a, **_k):
            raise AssertionError('network forbidden')
        with patch('em_market_backup._http_get', boom):
            for kwargs in (
                {'allow_network': 1},
                {'allow_network': 'true'},
                {'fetch_bytes': '{}'},
                {'fetch': 'nope'},
                {'clock': 1},
            ):
                with self.assertRaises(ValueError):
                    em.fetch_limit_pool(DAY, **kwargs)
            with self.assertRaises(ValueError):
                em.fetch_limit_pool('2026/10/29', allow_network=True, fetch=boom)
            with self.assertRaises(ValueError):
                em.fetch_limit_pool(DAY, 'hot', allow_network=True, fetch=boom)

    def test_zt_fixture_keeps_status_and_drops_money_fields(self):
        result = em.fetch_limit_pool(DAY, fetch_bytes=load('zt.json'))
        self.assertEqual(result['day'], DAY)
        self.assertEqual([item['thscode'] for item in result['items']], ['600000.SH', '000001.SZ'])
        first, second = result['items']
        self.assertEqual(first['continue_day_cnt'], 3)
        self.assertEqual(first['limit_up_time'], '09:25:00')
        self.assertEqual(first['last_limit_time'], '09:32:01')
        self.assertEqual(first['open_count'], 1)
        self.assertAlmostEqual(first['latest_price'], 11.55)
        self.assertEqual(second['latest_price'], 10.0)
        self.assertFalse(any('日期未核验' in gap for gap in result['gaps']))
        self.assertIn('milli/1000', '\n'.join(result['notes']))
        self.assertNotIn('fund', first)
        self.assertNotIn('amount', first)
        self.assertNotIn('zttj', first)
        self.assertIsNone(second['limit_up_time'])
        self.assertEqual(second['open_count'], 0)
        self.assertTrue(any('不写成 00:00:00' in gap for gap in result['gaps']))
        self.assertIsNone(forbidden(json.dumps(result, ensure_ascii=False)))
        self.assertTrue(result['license_note'])

    def test_break_and_down_paths_stay_on_their_own_shape(self):
        broken = em.fetch_limit_pool(DAY, 'break', fetch_bytes=load('zb.json'))
        down = em.fetch_limit_pool(DAY, 'down', fetch_bytes=load('dt.json'))
        self.assertEqual(broken['day'], DAY)
        self.assertEqual(down['day'], DAY)
        self.assertEqual([item['thscode'] for item in broken['items']], ['300001.SZ', '920001.BJ'])
        self.assertIsNone(broken['items'][0]['continue_day_cnt'])
        self.assertEqual(broken['items'][0]['open_count'], 2)
        self.assertEqual(down['items'][0]['thscode'], '000002.SZ')
        self.assertEqual(down['items'][0]['continue_day_cnt'], 2)
        self.assertEqual(down['items'][0]['open_count'], 1)
        self.assertIsNone(down['items'][0]['limit_up_time'])
        self.assertNotIn('fund', down['items'][0])

    def test_incomplete_page_is_a_gap_without_another_request(self):
        payload = {'rc': 0, 'data': {'tc': 3, 'pool': [
            {'c': '600000', 'm': 1, 'n': '合成甲', 'lbc': 1},
            {'c': '600000', 'm': 1, 'n': '重复', 'lbc': 2},
            'bad',
            {'c': '11', 'n': '短'},
            {'m': 1, 'n': '无代码'},
            {'c': '000001', 'm': 1, 'n': '市场不符', 'lbc': 0, 'p': 0, 'lbt': 156000},
        ]}}
        calls = []
        result = em.fetch_limit_pool(DAY, allow_network=True, fetch_bytes=json.dumps(payload).encode(), fetch=lambda url: calls.append(url))
        self.assertEqual(calls, [])
        self.assertEqual([item['thscode'] for item in result['items']], ['600000.SH', '000001.SZ'])
        self.assertIsNone(result['items'][1]['continue_day_cnt'])
        self.assertIsNone(result['items'][1]['latest_price'])
        self.assertIsNone(result['items'][1]['last_limit_time'])
        text = '\n'.join(result['gaps'])
        self.assertIn('未自动翻页', text)
        self.assertIn('重复', text)
        self.assertIn('未记为 0', text)
        self.assertIn('市场标记', text)

    def test_page_cap_and_empty_upstream_do_not_invent_rows(self):
        with patch('em_market_backup.PAGE_SIZE', 1):
            capped = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({'data': {'tc': 1, 'pool': [{'c': '600000', 'm': 1, 'n': '合成甲'}]}}).encode())
        self.assertEqual(len(capped['items']), 1)
        self.assertTrue(any('pagesize=1' in gap for gap in capped['gaps']))
        empty = em.fetch_limit_pool(DAY, fetch_bytes=b'{"data": null}')
        self.assertEqual(empty['items'], [])
        self.assertIsNone(empty['day'])
        self.assertFalse(any('空池' in note for note in empty['notes']))
        self.assertTrue(any('null' in gap and '未核验' in gap and '未改试其他来源' in gap for gap in empty['gaps']))
        refused = em.fetch_limit_pool(DAY, fetch_bytes=b'{"rc": 1, "data": {"tc": 1, "pool": [{"c": "600000", "m": 1}]}}')
        self.assertEqual(refused['items'], [])
        self.assertIsNone(refused['day'])
        self.assertIn('未改试其他来源', refused['gaps'][0])

    def test_bytes_win_and_network_failure_names_one_path(self):
        seen = []

        def fetch(url):
            seen.append(url)
            raise OSError('boom')

        offline = em.fetch_limit_pool(DAY, allow_network=True, fetch_bytes=load('zt.json'), fetch=fetch)
        self.assertEqual(seen, [])
        self.assertEqual(len(offline['items']), 2)
        failed = em.fetch_limit_pool(DAY, 'up', allow_network=True, fetch=fetch, clock=lambda: 0, sleeper=lambda _s: None)
        self.assertEqual(failed['items'], [])
        self.assertIsNone(failed['day'])
        self.assertEqual(len(seen), 1)
        self.assertIn('/getTopicZTPool', seen[0])
        self.assertNotIn('/getTopicZBPool', seen[0])
        self.assertNotIn(em.PAGE_QUERY_UT, failed['gaps'][0])
        self.assertIn('OSError', failed['gaps'][0])
        self.assertIn('getTopicZTPool', failed['gaps'][0])
        self.assertIn('未改试其他来源', failed['gaps'][0])
        garbled = em.fetch_limit_pool(DAY, fetch_bytes='不是utf8'.encode('gbk'))
        self.assertIn('未改用其他编码', garbled['gaps'][0])

    def test_rate_limit_uses_injected_clock(self):
        state = {'t': 10.0}
        waits = []

        def clock():
            return state['t']

        def sleeper(wait):
            waits.append(wait)
            state['t'] += wait

        def fetch(_url):
            return b'{"data": null}'

        em.fetch_limit_pool(DAY, allow_network=True, fetch=fetch, clock=clock, sleeper=sleeper)
        em.fetch_market_breadth(allow_network=True, fetch=fetch, clock=clock, sleeper=sleeper)
        self.assertEqual(waits, [1.0])

    def test_breadth_snapshot_merges_single_key_buckets_without_zero_fill(self):
        result = em.fetch_market_breadth(fetch_bytes=load('breadth.json'))
        self.assertEqual(result['kind'], 'breadth')
        self.assertEqual(result['day'], '2026-10-29')
        self.assertIn('不认历史日', '\n'.join(result['notes']))
        item = result['items'][0]
        self.assertEqual(item['bins'], {'-1': 2, '0': 3, '1': 4})
        self.assertIsNone(item['up'])
        self.assertIsNone(item['down'])
        self.assertEqual(item['flat'], 3)
        self.assertIsNone(item['sample'])
        self.assertTrue(any('11 个有效桶' in gap for gap in result['gaps']))
        self.assertFalse(any('未拼接' in gap or '多段' in gap for gap in result['gaps']))
        self.assertNotIn('全市场家数', '\n'.join(result['gaps'] + result['notes']))
        other = em.fetch_market_breadth(fetch_bytes=b'{"data": {"f104": 10, "f105": 3, "qdate": 20260231}}')
        self.assertEqual(other['items'], [])
        self.assertIsNone(other['day'])
        self.assertIn('getTopicZDFenBu', other['gaps'][0])
        self.assertIn('未改读其他接口', other['gaps'][0])
        self.assertTrue(any('无法解析' in note for note in other['notes']))
        flat = em.fetch_market_breadth(fetch_bytes=b'{"data": {"fenbu": {"0": 0, "1": 2}}}')
        self.assertIsNone(flat['items'][0]['up'])
        self.assertEqual(flat['items'][0]['flat'], 0)
        self.assertIsNone(flat['items'][0]['down'])
        self.assertIsNone(flat['items'][0]['sample'])
        self.assertTrue(any('快照日期未核验' in note for note in flat['notes']))

    def test_redirect_off_host_stops(self):
        class Request:
            full_url = 'https://push2ex.eastmoney.com/getTopicZTPool'
        with self.assertRaises(urllib.error.HTTPError) as caught:
            em._SameHostRedirect().redirect_request(Request(), None, 302, 'moved', {}, 'https://quote.eastmoney.com/next')
        self.assertIn('离开', str(caught.exception))
        with self.assertRaises(OSError):
            em._http_get('https://example.com/getTopicZTPool')

    def test_compare_is_a_set_difference_only(self):
        compared = em.compare_pools(
            [{'thscode': '600000.SH'}, {'thscode': '000001.SZ'}, {'thscode': '000001.SZ'}, {'name': '缺代码'}],
            [{'code': '000001', 'm': 0}, {'code': '920001'}, '跳过'],
        )
        self.assertEqual(set(compared), {'only_primary', 'only_backup', 'both', 'notes'})
        self.assertEqual(compared['only_primary'], ['600000.SH'])
        self.assertEqual(compared['only_backup'], ['920001.BJ'])
        self.assertEqual(compared['both'], ['000001.SZ'])
        self.assertIsNone(forbidden('\n'.join(compared['notes'])))
        self.assertIn('不评价来源优劣', '\n'.join(compared['notes']))
        with self.assertRaises(ValueError):
            em.compare_pools(None, [])

    def test_primary_modules_do_not_import_the_backup(self):
        for name in ('market.py', 'rankings.py', 'research.py'):
            text = (ROOT / name).read_text()
            self.assertNotIn('em_market_backup', text)
            self.assertNotIn('getTopicZTPool', text)
        backup = (ROOT / 'em_market_backup.py').read_text()
        self.assertNotIn('push2.eastmoney.com', backup)
        self.assertNotIn('import requests', backup)
        self.assertNotIn('baostock', backup)
        self.assertIn('许可待审', backup)
        market = (ROOT / 'market.py').read_text()
        self.assertIn("'break_rate': len(broken)/len(touched)*100 if up is not None and broken is not None and touched else None", market)

    def test_pool_dates_keep_request_basis_separate_from_qdate(self):
        row = {'c': '600000', 'm': 1, 'n': '合成甲', 'p': 11550}
        def parse(day=DAY, kind='up', **dates):
            body = json.dumps({'data': {'tc': 1, 'pool': [row], **dates}}).encode()
            return em.fetch_limit_pool(day, kind, fetch_bytes=body)

        for kind in ('up', 'break', 'down'):
            for qdate in (20261029, '20261030', '2026-10-30'):
                with self.subTest(kind=kind, qdate=qdate):
                    value = parse(kind=kind, qdate=qdate)
                    self.assertEqual(value['day'], DAY)
                    self.assertEqual(value['date_basis'], 'portal_date_parameter')
                    self.assertEqual(value['requested_day'], DAY)
                    self.assertEqual(value['upstream_qdate'], '2026-10-29' if qdate == 20261029 else '2026-10-30')
                    self.assertTrue(value['list_complete'])
                    self.assertEqual(value['gaps'], [])
                    self.assertEqual(len(value['items']), 1)
                    self.assertIn('非响应日期回显', ' '.join(value['notes']))
            stale = parse(kind=kind, qdate=20261028)
            self.assertIsNone(stale['day'])
            self.assertEqual(stale['items'], [])
            self.assertIn('早于', ' '.join(stale['gaps']))
            self.assertIn(em.POOL_PATHS[kind], ' '.join(stale['gaps']))

        explicit = parse(date='2026-10-29', qdate=20261030)
        self.assertEqual(explicit['day'], DAY)
        self.assertEqual(explicit['date_basis'], 'response_date')
        self.assertEqual(parse(date=20261029)['date_basis'], 'response_date')
        date_only = parse(day='2000-01-01', date=20000101)
        self.assertEqual(date_only['day'], '2000-01-01')
        self.assertEqual(date_only['date_basis'], 'response_date')
        self.assertIsNone(date_only['upstream_qdate'])
        self.assertFalse(date_only['list_complete'])
        self.assertTrue(any('窗口未核验' in gap for gap in date_only['gaps']))
        for date in (20261028, 20261030):
            rejected = parse(date=date, qdate=20261030)
            self.assertEqual(rejected['items'], [])
            self.assertIsNone(rejected['day'])
            self.assertIn('不符', ' '.join(rejected['gaps']))
        for fields in ({'qdate': 20260231}, {'date': '2026-02-31'},
                       {'qdate': None, 'date': 20261029}, {'qdate': True},
                       {'qdate': 20261030, 'date': 'bad'}):
            rejected = parse(**fields)
            self.assertEqual(rejected['items'], [])
            self.assertIn('不是合法公历', ' '.join(rejected['gaps']))
        missing = parse()
        self.assertIsNone(missing['day'])
        self.assertEqual(missing['date_basis'], 'unverified')
        self.assertFalse(missing['list_complete'])
        self.assertEqual(len(missing['items']), 1)
        self.assertIn('日期未核验', ' '.join(missing['gaps']))
        boundary = parse(day='2026-10-22', qdate=20261030)
        self.assertEqual(boundary['day'], '2026-10-22')
        too_old = parse(day='2026-10-21', qdate=20261030)
        self.assertEqual(too_old['items'], [])
        self.assertIn('8 个自然日', ' '.join(too_old['gaps']))
        future = parse(day='2026-10-31', qdate=20261030)
        self.assertEqual(future['items'], [])
        # 显式名单日期也不能绕过门户保留范围。
        self.assertEqual(parse(day='2026-10-21', date=20261021, qdate=20261030)['items'], [])

    def test_pool_query_sort_and_down_fields_follow_portal_contract(self):
        from urllib.parse import parse_qs, urlsplit
        for kind, sort in (('up', 'fbt:asc'), ('break', 'fbt:asc'), ('down', 'fund:asc')):
            seen = []
            def fetch(url):
                seen.append(url)
                return json.dumps({'data': {'qdate': 20261030, 'tc': 1, 'pool': [
                    {'c': '000002', 'm': 0, 'p': 12500, 'oc': 6, 'ocnt': 9, 'days': 2, 'lbt': 100739}
                ]}}).encode()
            result = em.fetch_limit_pool(DAY, kind, allow_network=True, fetch=fetch,
                                         clock=lambda: 0, sleeper=lambda _s: None)
            self.assertEqual(len(seen), 1)
            query = parse_qs(urlsplit(seen[0]).query)
            self.assertEqual(query['sort'], [sort])
            self.assertEqual(query['date'], ['20261029'])
            self.assertTrue(result['list_complete'])
            if kind == 'down':
                self.assertEqual(result['items'][0]['open_count'], 6)
                self.assertEqual(result['items'][0]['continue_day_cnt'], 2)
                self.assertEqual(result['items'][0]['last_limit_time'], '10:07:39')
        for bad in (None, '6', True, -1):
            body = json.dumps({'data': {'qdate': 20261030, 'tc': 1, 'pool': [
                {'c': '000002', 'm': 0, 'oc': bad, 'ocnt': 9},
            ]}}).encode()
            invalid = em.fetch_limit_pool(DAY, 'down', fetch_bytes=body)
            self.assertIsNone(invalid['items'][0]['open_count'])
            self.assertTrue(any('开板次数' in g for g in invalid['gaps']))

    def test_pool_completeness_does_not_hide_count_or_identity_gaps(self):
        row = {'c': '600000', 'm': 1}
        for fields in ({'tc': 2, 'pool': [row]}, {'pool': []}, {'tc': -1, 'pool': []},
                       {'tc': 2, 'pool': [row, row]}, {'tc': 2, 'pool': [row, {'c': 'bad'}]}):
            body = json.dumps({'data': {'qdate': 20261030, **fields}}).encode()
            value = em.fetch_limit_pool(DAY, fetch_bytes=body)
            self.assertFalse(value['list_complete'])
            self.assertTrue(value['gaps'])
        value = em.fetch_limit_pool(DAY, fetch_bytes=b'{"data":{"qdate":20261030,"tc":0,"pool":[]}}')
        self.assertTrue(value['list_complete'])
        self.assertEqual(value['items'], [])
        date_only_empty = em.fetch_limit_pool(DAY, fetch_bytes=b'{"data":{"date":20261029,"tc":0,"pool":[]}}')
        self.assertFalse(date_only_empty['list_complete'])
        self.assertTrue(any('窗口未核验' in g for g in date_only_empty['gaps']))
        self.assertFalse(any('按空池记录' in n for n in date_only_empty['notes']))

    def test_missing_data_is_not_a_verified_empty_pool(self):
        row = {'c': '600000', 'm': 1, 'n': '合成甲'}
        for label, body in (
            ('missing', b'{"rc": 0}'),
            ('null', b'{"rc": 0, "data": null}'),
        ):
            with self.subTest(label=label):
                result = em.fetch_limit_pool(DAY, fetch_bytes=body)
                text = '\n'.join(result['gaps'])
                self.assertEqual(result['items'], [])
                self.assertIsNone(result['day'])
                self.assertIn('未核验', text)
                self.assertIn('未改试其他来源', text)
                self.assertTrue('缺失' in text or 'null' in text)
                self.assertFalse(any('空池' in note for note in result['notes']))
                compared = em.compare_pools([{'thscode': '600000.SH'}], result['items'])
                self.assertEqual(compared['only_primary'], ['600000.SH'])
                self.assertTrue(result['gaps'])

        empty = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({
            'data': {'qdate': 20261029, 'tc': 0, 'pool': []},
        }).encode())
        self.assertEqual(empty['day'], DAY)
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['gaps'], [])
        self.assertTrue(any('空池' in note for note in empty['notes']))

        mismatch = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({
            'data': {'qdate': '2026-10-29', 'tc': 3, 'pool': [row]},
        }).encode())
        self.assertEqual(mismatch['day'], DAY)
        self.assertEqual(len(mismatch['items']), 1)
        self.assertTrue(any('不一致' in gap for gap in mismatch['gaps']))
        self.assertFalse(any('空池' in note for note in mismatch['notes']))

        empty_mismatch = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({
            'data': {'qdate': 20261029, 'tc': 2, 'pool': []},
        }).encode())
        self.assertEqual(empty_mismatch['day'], DAY)
        self.assertEqual(empty_mismatch['items'], [])
        self.assertTrue(any('不一致' in gap for gap in empty_mismatch['gaps']))
        self.assertFalse(any('空池' in note for note in empty_mismatch['notes']))

        invalid_rows = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({
            'data': {'qdate': 20261029, 'tc': 2, 'pool': ['bad', {'c': '11'}]},
        }).encode())
        self.assertEqual(invalid_rows['day'], DAY)
        self.assertEqual(invalid_rows['items'], [])
        self.assertTrue(any('跳过' in gap for gap in invalid_rows['gaps']))
        self.assertFalse(any('空池' in note for note in invalid_rows['notes']))
        self.assertNotIn('未采用名单', '\n'.join(invalid_rows['gaps']))

        unverified_empty = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({
            'data': {'tc': 0, 'pool': []},
        }).encode())
        self.assertIsNone(unverified_empty['day'])
        self.assertEqual(unverified_empty['items'], [])
        self.assertTrue(any('日期未核验' in gap for gap in unverified_empty['gaps']))
        self.assertFalse(any('空池' in note for note in unverified_empty['notes']))

    def test_breadth_requires_all_portal_buckets_for_a_total(self):
        def parse(fenbu, **dates):
            return em.fetch_market_breadth(fetch_bytes=json.dumps({
                'data': {'qdate': 20261030, 'fenbu': fenbu, **dates}
            }).encode())
        full = {str(i): 0 for i in range(-11, 12)}
        full.update({'-11': 7, '-10': 8, '-1': 3, '0': 2, '1': 4, '10': 5, '11': 6})
        result = parse([{k: v} for k, v in full.items()])
        item = result['items'][0]
        self.assertEqual(result['gaps'], [])
        self.assertEqual((item['down'], item['flat'], item['up'], item['sample']), (18, 2, 15, 35))
        self.assertTrue(item['complete'])
        self.assertEqual(item['aggregation_scope'], 'eastmoney_portal_distribution')
        self.assertEqual(item['bin_labels']['11'], '涨停')
        self.assertEqual(item['bin_labels']['-11'], '跌停')
        self.assertIn('未涨停', item['bin_labels']['10'])
        self.assertIn('未跌停', item['bin_labels']['-10'])
        self.assertEqual(parse(full)['items'][0], item)
        # 相同桶去重；不重复计入总体，极端未封板桶与涨跌停桶各计一次。
        duplicate = parse([{k: v} for k, v in full.items()] + [{'11': 6}])
        self.assertEqual(duplicate['items'][0], item)
        self.assertEqual(duplicate['gaps'], [])
        zeros = parse({str(i): 0 for i in range(-11, 12)})
        self.assertEqual(zeros['items'][0]['sample'], 0)
        self.assertTrue(zeros['items'][0]['complete'])
        for key in ('-11', '-10', '-1', '0', '1', '10', '11'):
            fields = dict(full)
            del fields[key]
            missing = parse(fields)
            self.assertIsNone(missing['items'][0]['sample'])
            self.assertFalse(missing['items'][0]['complete'])
            self.assertNotIn(key, missing['items'][0]['bins'])
            self.assertTrue(missing['gaps'])
        partial = parse({'-1': 0, '0': 0, '1': 0})
        self.assertEqual(partial['items'][0]['bins'], {'-1': 0, '0': 0, '1': 0})
        self.assertEqual(tuple(partial['items'][0][k] for k in ('down', 'flat', 'up', 'sample')), (None, 0, None, None))
        self.assertFalse(partial['items'][0]['complete'])
        undated = parse(full, qdate=None)
        self.assertIsNone(undated['day'])
        self.assertFalse(undated['items'][0]['complete'])
        self.assertIsNone(undated['items'][0]['sample'])
        self.assertTrue(undated['gaps'])
        self.assertEqual(undated['items'][0]['bins'], full)
        for dates in ({}, {'qdate': 'bad'}, {'qdate': None}):
            value = em.fetch_market_breadth(fetch_bytes=json.dumps({
                'data': {'fenbu': full, **dates},
            }).encode())
            self.assertIsNone(value['day'])
            self.assertIsNone(value['items'][0]['sample'])
            self.assertFalse(value['items'][0]['complete'])
            self.assertEqual(value['items'][0]['bins'], full)

    def test_breadth_conflicts_invalid_and_unknown_fields_do_not_get_summed(self):
        def parse(fenbu):
            return em.fetch_market_breadth(fetch_bytes=json.dumps({
                'data': {'qdate': 20261030, 'fenbu': fenbu}
            }).encode())
        full = {str(i): 1 for i in range(-11, 12)}
        for bad in ('bad', True, -1, 1.0, None):
            result = parse({**full, '1': bad})
            item = result['items'][0]
            self.assertIsNone(item['up'])
            self.assertEqual(item['down'], 11)
            self.assertNotIn('1', item['bins'])
            self.assertIsNone(item['sample'])
            self.assertTrue(any('无效' in g for g in result['gaps']))
        for key in ('1', '-1', '0'):
            result = parse([{k: v} for k, v in full.items()] + [{key: 2}, {key: 1}])
            item = result['items'][0]
            self.assertNotIn(key, item['bins'])
            self.assertIsNone(item['sample'])
            self.assertFalse(item['complete'])
            self.assertTrue(any('不同的值' in g for g in result['gaps']))
        typed = parse([{'1': 2}, {'1': 2.0}, {'0': 0}])
        self.assertNotIn('1', typed['items'][0]['bins'])
        for unknown in ('12', '-12', '01', '-0', 'total', 'time'):
            result = parse({**full, unknown: 9})
            self.assertNotIn(unknown, result['items'][0]['bins'])
            self.assertEqual(tuple(result['items'][0][k] for k in ('up', 'down', 'flat', 'sample')), (None,) * 4)
            self.assertFalse(result['items'][0]['complete'])
        unknown_conflict = parse([{k: v} for k, v in full.items()] + [{'12': 1}, {'12': 2}])
        self.assertIsNone(unknown_conflict['items'][0]['sample'])
        self.assertFalse(unknown_conflict['items'][0]['complete'])
        only_conflict = parse([{'1': 2}, {'1': 9}])
        self.assertEqual(only_conflict['items'][0]['bins'], {})
        self.assertIsNone(only_conflict['items'][0]['sample'])
        for fenbu in ([], [1, {'1': 2}], [None], [{}], [{'0': 0, '1': 1}], [{'0': 0}, {'1': 1, '2': 2}]):
            rejected = parse(fenbu)
            self.assertEqual(rejected['items'], [])
            self.assertTrue(any('列表结构不支持' in g for g in rejected['gaps']))
        invalid_flat = parse({**full, '0': 'bad'})
        self.assertIsNone(invalid_flat['items'][0]['flat'])
        self.assertTrue(any('平盘' in g for g in invalid_flat['gaps']))

    def test_price_milli_contract_ignores_json_number_type(self):
        self.assertEqual(em._price(10000), 10.0)
        self.assertEqual(em._price(10000.0), 10.0)
        self.assertEqual(em._price(10000), em._price(10000.0))
        self.assertAlmostEqual(em._price(11550), 11.55)
        self.assertAlmostEqual(em._price(11550.0), 11.55)
        for bad in (0, 0.0, -1, -1.5, True, False, '10000', None, float('nan'), float('inf'), float('-inf')):
            self.assertIsNone(em._price(bad), repr(bad))

        def priced(value):
            body = json.dumps({'data': {'qdate': 20261029, 'tc': 1, 'pool': [
                {'c': '600000', 'm': 1, 'n': '合成甲', 'p': value},
            ]}}).encode()
            return em.fetch_limit_pool(DAY, fetch_bytes=body)

        whole = priced(10000)
        fractional = priced(10000.0)
        self.assertEqual(whole['items'][0]['latest_price'], 10.0)
        self.assertEqual(fractional['items'][0]['latest_price'], 10.0)
        self.assertEqual(whole['items'][0]['latest_price'], fractional['items'][0]['latest_price'])
        self.assertEqual(whole['day'], DAY)
        note = '\n'.join(whole['notes'])
        self.assertIn('p 按 milli/1000，整数与浮点同一数值结果一致；已核对门户显示函数和同期报价', note)
        self.assertNotIn('整数最新价', note)
        self.assertNotIn('浮点原样', note)
        for bad in (0, 0.0, True, '10000', None):
            result = priced(bad)
            self.assertEqual(result['day'], DAY)
            self.assertIsNone(result['items'][0]['latest_price'], repr(bad))
            self.assertTrue(any('最新价' in gap and '未记为 0' in gap for gap in result['gaps']))
        missing = em.fetch_limit_pool(DAY, fetch_bytes=json.dumps({'data': {'qdate': 20261029, 'tc': 1, 'pool': [
            {'c': '600000', 'm': 1, 'n': '合成甲'},
        ]}}).encode())
        self.assertIsNone(missing['items'][0]['latest_price'])
        self.assertFalse(any('最新价' in gap for gap in missing['gaps']))


class ApiTests(unittest.TestCase):
    def setUp(self):
        em.reset_rate_gate()
        self.addCleanup(em.reset_rate_gate)
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.demo = None
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.shutdown)
        self.addCleanup(self.http.server_close)

    def request(self, path):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=10)
        connection.request('GET', path)
        response = connection.getresponse()
        body = response.read()
        status = response.status
        connection.close()
        return status, json.loads(body)

    def test_failure_metadata_survives_http(self):
        for kind in ('up', 'break', 'down'):
            for case in ('offline', 'bad_json', 'fetch_error'):
                with self.subTest(kind=kind, case=case):
                    failure = OSError('synthetic fetch failure') if case == 'fetch_error' else None
                    with patch('em_market_backup._http_get', return_value=b'{bad', side_effect=failure), patch('em_market_backup._acquire'):
                        flag = '' if case == 'offline' else '&allow_network=1'
                        status, body = self.request(f'/api/backup/em-pools?date={DAY}&kind={kind}{flag}')
                    self.assertEqual(status, 200)
                    self.assertIs(body['list_complete'], False)
                    self.assertEqual(body['date_basis'], 'unverified')
                    self.assertEqual(body['requested_day'], DAY)
                    self.assertIsNone(body['upstream_qdate'])
                    self.assertEqual(body['latest_price_unit'], 'CNY')
                    self.assertIsNone(body['day'])
                    self.assertEqual(body['items'], [])
                    self.assertTrue(body['gaps'])

    def test_live_route_stays_offline_until_flag_and_uses_one_host(self):
        def boom(*_a, **_k):
            raise AssertionError('network forbidden')
        with patch('em_market_backup._http_get', boom), patch('urllib.request.urlopen', boom):
            status, payload = self.request(f'/api/backup/em-pools?date={DAY}&kind=up')
            breadth, snapshot = self.request(f'/api/backup/em-pools?kind=breadth&date={DAY}')
            bad, _error = self.request('/api/backup/em-pools?date=20261029&kind=up&allow_network=1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['source'], 'eastmoney')
        self.assertIsNone(payload['day'])
        self.assertIn('未联网', payload['gaps'][0])
        self.assertEqual(breadth, 200)
        self.assertTrue(any('已忽略' in note for note in snapshot['notes']))
        self.assertEqual(bad, 400)
        seen = []

        def fetch(url):
            seen.append(url)
            return load('zb.json')

        with patch('em_market_backup._http_get', fetch):
            status, payload = self.request(f'/api/backup/em-pools?date={DAY}&kind=break&allow_network=1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['kind'], 'break')
        self.assertEqual(payload['day'], DAY)
        self.assertEqual(payload['items'][0]['thscode'], '300001.SZ')
        self.assertIn('/getTopicZBPool', seen[0])
        self.assertNotIn('/getTopicZTPool', seen[0])

    def test_stale_pool_date_is_not_adopted_over_http(self):
        calls = []
        body = json.dumps({
            'rc': 0,
            'data': {
                'qdate': 20261028,
                'tc': 1,
                'pool': [{'c': '600000', 'm': 1, 'n': '合成甲', 'p': 10000}],
            },
        }).encode()

        def fetch(url):
            calls.append(url)
            return body

        def boom(*_a, **_k):
            raise AssertionError('real network forbidden')

        with patch('em_market_backup._http_get', fetch), patch('urllib.request.urlopen', boom):
            status, payload = self.request(f'/api/backup/em-pools?date={DAY}&kind=up&allow_network=1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['source'], 'eastmoney')
        self.assertEqual(payload['kind'], 'up')
        self.assertEqual(payload['items'], [])
        self.assertIsNone(payload['day'])
        text = '\n'.join(payload['gaps'])
        self.assertIn('2026-10-28', text)
        self.assertIn('/getTopicZTPool', text)
        self.assertIn('未改试其他来源', text)
        self.assertFalse(any('空池' in note for note in payload['notes']))
        self.assertEqual(len(calls), 1)
        self.assertIn('/getTopicZTPool', calls[0])
        self.assertIn('date=20261029', calls[0])
        self.assertNotIn('/getTopicZBPool', calls[0])
        self.assertNotIn('/getTopicDTPool', calls[0])

    def test_history_and_partial_distribution_metadata_survive_http(self):
        pool = json.dumps({'data': {'qdate': 20261030, 'tc': 1, 'pool': [
            {'c': '000002', 'm': 0, 'oc': 3, 'days': 2, 'p': 12500},
        ]}}).encode()
        partial = json.dumps({'data': {'qdate': 20261030, 'fenbu': [
            {'-1': 2}, {'0': 1}, {'1': 3},
        ]}}).encode()
        calls = []

        def fetch(url):
            calls.append(url)
            return partial if 'getTopicZDFenBu' in url else pool

        with patch('em_market_backup._http_get', fetch), patch('em_market_backup._acquire'):
            status, body = self.request(f'/api/backup/em-pools?date={DAY}&kind=down&allow_network=1')
            wide, breadth = self.request(f'/api/backup/em-pools?date={DAY}&kind=breadth&allow_network=1')
        self.assertEqual(status, 200)
        self.assertEqual((body['day'], body['requested_day'], body['upstream_qdate']), (DAY, DAY, '2026-10-30'))
        self.assertEqual(body['date_basis'], 'portal_date_parameter')
        self.assertTrue(body['list_complete'])
        self.assertEqual(body['latest_price_unit'], 'CNY')
        self.assertEqual(body['items'][0]['latest_price'], 12.5)
        self.assertEqual(body['items'][0]['open_count'], 3)
        self.assertIn('sort=fund%3Aasc', calls[0])
        self.assertEqual(wide, 200)
        self.assertEqual(breadth['day'], '2026-10-30')  # 不伪装成请求的历史日。
        self.assertFalse(breadth['items'][0]['complete'])
        self.assertIsNone(breadth['items'][0]['sample'])
        self.assertTrue(breadth['gaps'])
        self.assertEqual(len(calls), 2)

    def test_demo_compare_is_synthetic_and_research_is_untouched(self):
        from demo import Demo
        self.http.demo = Demo()
        day = self.http.demo.day

        def boom(*_a, **_k):
            raise AssertionError('network forbidden')

        with patch('urllib.request.urlopen', boom), patch('em_market_backup._http_get', boom):
            before = self.request(f'/api/research?date={day}')
            status, payload = self.request(f'/api/backup/em-pools?date={day}&kind=up')
            denied, body = self.request(f'/api/backup/em-pools?date={day}&kind=up&allow_network=1')
            after = self.request(f'/api/research?date={day}')
            wide, breadth = self.request(f'/api/backup/em-pools?kind=breadth&date={day}')
        self.assertEqual(before[0], 200)
        self.assertEqual(before[1], after[1])
        self.assertNotIn('eastmoney', json.dumps(before[1]))
        self.assertEqual(status, 200)
        self.assertEqual(payload['source'], 'synthetic-demo')
        self.assertTrue(payload['synthetic'])
        self.assertEqual(payload['requested_day'], day)
        self.assertEqual(payload['date_basis'], 'synthetic_demo')
        self.assertFalse(payload['list_complete'])
        self.assertIsNone(payload['upstream_qdate'])
        self.assertEqual(payload['latest_price_unit'], 'CNY')
        self.assertEqual(payload['compare']['both'], ['000001.SZ'])
        self.assertEqual(payload['compare']['only_primary'], ['600000.SH'])
        self.assertEqual(payload['compare']['only_backup'], ['920001.BJ'])
        self.assertIsNone(forbidden(json.dumps(payload, ensure_ascii=False)))
        self.assertEqual(denied, 403)
        self.assertEqual(body['reason'], 'demo_read_only')
        self.assertEqual(wide, 200)
        self.assertIsNone(breadth['day'])
        self.assertTrue(any('已忽略' in note for note in breadth['notes']))
        for kind in ('up', 'break', 'down'):
            value = em.synthetic_demo(kind, day)
            self.assertEqual(value['requested_day'], day)
            self.assertEqual(value['date_basis'], 'synthetic_demo')
            self.assertFalse(value['list_complete'])
            self.assertIsNone(value['upstream_qdate'])
            self.assertEqual(value['latest_price_unit'], 'CNY')


if __name__ == '__main__':
    unittest.main()
