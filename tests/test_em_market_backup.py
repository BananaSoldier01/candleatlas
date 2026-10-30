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

    def test_breadth_snapshot_does_not_zero_fill_or_join_segments(self):
        result = em.fetch_market_breadth(fetch_bytes=load('breadth.json'))
        self.assertEqual(result['kind'], 'breadth')
        self.assertEqual(result['day'], '2026-10-29')
        self.assertIn('不认历史日', '\n'.join(result['notes']))
        item = result['items'][0]
        self.assertEqual(item['up'], 8)
        self.assertEqual(item['down'], 4)
        self.assertIsNone(item['flat'])
        self.assertIsNone(item['sample'])
        self.assertNotEqual(item['up'], 0)
        self.assertNotEqual(item['down'], 0)
        self.assertNotIn('0', item['bins'])
        self.assertTrue(any('未拼接' in gap for gap in result['gaps']))
        self.assertTrue(any('部分' in note or '不完整' in note for note in result['notes']))
        other = em.fetch_market_breadth(fetch_bytes=b'{"data": {"f104": 10, "f105": 3, "qdate": 20260231}}')
        self.assertEqual(other['items'], [])
        self.assertIsNone(other['day'])
        self.assertIn('getTopicZDFenBu', other['gaps'][0])
        self.assertIn('未改读其他接口', other['gaps'][0])
        self.assertTrue(any('无法解析' in note for note in other['notes']))
        flat = em.fetch_market_breadth(fetch_bytes=b'{"data": {"fenbu": {"0": 0, "1": 2}}}')
        self.assertEqual(flat['items'][0]['up'], 2)
        self.assertEqual(flat['items'][0]['flat'], 0)
        self.assertIsNone(flat['items'][0]['down'])
        self.assertIsNone(flat['items'][0]['sample'])
        self.assertTrue(any('部分' in note or '不完整' in note for note in flat['notes']))

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

    def test_response_date_is_checked_before_the_pool_is_kept(self):
        row = {'c': '600000', 'm': 1, 'n': '合成甲', 'p': 11550}
        same_dates = (
            ('up', 'qdate', 20261029),
            ('break', 'qdate', '20261029'),
            ('down', 'qdate', '2026-10-29'),
        )
        for kind, field, value in same_dates:
            with self.subTest(kind=kind, case='same', value=value):
                data = {'tc': 1, 'pool': [row], field: value}
                result = em.fetch_limit_pool(DAY, kind, fetch_bytes=json.dumps({'data': data}).encode())
                self.assertEqual(result['kind'], kind)
                self.assertEqual(result['day'], DAY)
                self.assertEqual([item['thscode'] for item in result['items']], ['600000.SH'])
                self.assertEqual(result['gaps'], [])
                self.assertEqual(result['source'], 'eastmoney')
        fallback = em.fetch_limit_pool(DAY, 'up', fetch_bytes=json.dumps({
            'data': {'date': '2026-10-29', 'tc': 1, 'pool': [row]},
        }).encode())
        self.assertEqual(fallback['day'], DAY)
        self.assertEqual(len(fallback['items']), 1)

        for kind in ('up', 'break', 'down'):
            with self.subTest(kind=kind, case='stale'):
                result = em.fetch_limit_pool(DAY, kind, fetch_bytes=json.dumps({
                    'data': {'qdate': 20261028, 'tc': 1, 'pool': [row]},
                }).encode())
                text = '\n'.join(result['gaps'])
                self.assertIsNone(result['day'])
                self.assertNotEqual(result['day'], DAY)
                self.assertEqual(result['items'], [])
                self.assertIn('2026-10-28', text)
                self.assertIn('早于', text)
                self.assertIn(em.POOL_PATHS[kind], text)
                self.assertIn('未改试其他来源', text)
                self.assertFalse(any('空池' in note for note in result['notes']))
                self.assertEqual(result['source'], 'eastmoney')

        illegal = (('up', 20260231), ('break', '20260231'), ('down', '2026-02-31'))
        for kind, value in illegal:
            with self.subTest(kind=kind, case='illegal', value=value):
                result = em.fetch_limit_pool(DAY, kind, fetch_bytes=json.dumps({
                    'data': {'qdate': value, 'tc': 1, 'pool': [row]},
                }).encode())
                text = '\n'.join(result['gaps'])
                self.assertIsNone(result['day'])
                self.assertEqual(result['items'], [])
                self.assertIn('不是合法公历', text)
                self.assertIn(str(value), text)
                self.assertIn(em.POOL_PATHS[kind], text)
                self.assertIn('未改试其他来源', text)

        for kind in ('up', 'break', 'down'):
            with self.subTest(kind=kind, case='missing'):
                result = em.fetch_limit_pool(DAY, kind, fetch_bytes=json.dumps({
                    'data': {'tc': 1, 'pool': [row]},
                }).encode())
                text = '\n'.join(result['gaps'])
                self.assertIsNone(result['day'])
                self.assertEqual([item['thscode'] for item in result['items']], ['600000.SH'])
                self.assertIn('日期未核验', text)
                self.assertIn(em.POOL_PATHS[kind], text)
                self.assertNotEqual(result['gaps'], [])

        future = em.fetch_limit_pool(DAY, 'down', fetch_bytes=json.dumps({
            'data': {'qdate': 20261030, 'tc': 1, 'pool': [row]},
        }).encode())
        self.assertIsNone(future['day'])
        self.assertEqual(future['items'], [])
        self.assertIn('晚于', '\n'.join(future['gaps']))
        self.assertIn(em.POOL_PATHS['down'], '\n'.join(future['gaps']))

        preferred = em.fetch_limit_pool(DAY, 'up', fetch_bytes=json.dumps({
            'data': {'qdate': 20261028, 'date': '2026-10-29', 'tc': 1, 'pool': [row]},
        }).encode())
        self.assertIsNone(preferred['day'])
        self.assertEqual(preferred['items'], [])
        self.assertIn('2026-10-28', '\n'.join(preferred['gaps']))

        seen = []

        def fetch(url):
            seen.append(url)
            return json.dumps({'data': {'qdate': 20261028, 'tc': 1, 'pool': [row]}}).encode()

        def boom(*_a, **_k):
            raise AssertionError('network forbidden')

        with patch('urllib.request.urlopen', boom), patch('em_market_backup._http_get', boom):
            fetched = em.fetch_limit_pool(DAY, 'up', allow_network=True, fetch=fetch, clock=lambda: 0, sleeper=lambda _s: None)
        self.assertEqual(len(seen), 1)
        self.assertIn('/getTopicZTPool', seen[0])
        self.assertNotIn('/getTopicZBPool', seen[0])
        self.assertIsNone(fetched['day'])
        self.assertEqual(fetched['items'], [])

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

    def test_breadth_directions_stay_unknown_without_a_zero_fill_rule(self):
        def item_of(fenbu):
            result = em.fetch_market_breadth(fetch_bytes=json.dumps({
                'rc': 0, 'data': {'qdate': 20261029, 'fenbu': fenbu},
            }).encode())
            self.assertEqual(result['day'], '2026-10-29')
            self.assertEqual(len(result['items']), 1, result['gaps'])
            return result, result['items'][0]

        result, item = item_of({'-1': 'bad', '0': 1, '1': 2})
        self.assertEqual(item['bins'], {'0': 1, '1': 2})
        self.assertEqual(item['up'], 2)
        self.assertEqual(item['flat'], 1)
        self.assertIsNone(item['down'])
        self.assertIsNone(item['sample'])
        self.assertTrue(any('无效' in gap for gap in result['gaps']))
        self.assertTrue(any('部分' in note or '不完整' in note for note in result['notes']))

        _result, item = item_of({'-1': 4, '0': 1})
        self.assertIsNone(item['up'])
        self.assertEqual(item['down'], 4)
        self.assertEqual(item['flat'], 1)
        self.assertIsNone(item['sample'])

        _result, item = item_of({'0': 5})
        self.assertIsNone(item['up'])
        self.assertIsNone(item['down'])
        self.assertEqual(item['flat'], 5)
        self.assertIsNone(item['sample'])

        result, item = item_of({'-1': 0, '0': 0, '1': 0})
        self.assertEqual((item['up'], item['down'], item['flat'], item['sample']), (0, 0, 0, 0))
        self.assertFalse(any('部分' in note for note in result['notes']))
        self.assertEqual(result['gaps'], [])

        result, item = item_of({'-2': 1, '-1': 3, '0': 4, '1': 5, '11': 6})
        self.assertEqual((item['down'], item['up'], item['flat'], item['sample']), (4, 11, 4, 19))
        self.assertEqual(result['gaps'], [])

        _result, item = item_of({'1': 2, '2': 'bad', '-1': 3, '0': 1})
        self.assertIsNone(item['up'])
        self.assertEqual(item['down'], 3)
        self.assertEqual(item['flat'], 1)
        self.assertEqual(item['bins'], {'1': 2, '-1': 3, '0': 1})
        self.assertIsNone(item['sample'])

        _result, item = item_of({'-1': 0, '0': 0})
        self.assertIsNone(item['up'])
        self.assertEqual(item['down'], 0)
        self.assertEqual(item['flat'], 0)
        self.assertIsNone(item['sample'])

        result, item = item_of([{'-1': 4, '1': 6}, {'-1': 100, '0': 9, '1': 100}])
        self.assertEqual(item['up'], 6)
        self.assertEqual(item['down'], 4)
        self.assertIsNone(item['flat'])
        self.assertIsNone(item['sample'])
        self.assertNotIn('0', item['bins'])
        self.assertTrue(any('未拼接' in gap for gap in result['gaps']))

        result, item = item_of({'0': 'bad', '1': 2, '-1': 3})
        self.assertIsNone(item['flat'])
        self.assertEqual(item['up'], 2)
        self.assertEqual(item['down'], 3)
        self.assertIsNone(item['sample'])
        self.assertNotIn('0', item['bins'])
        self.assertTrue(any('平盘' in gap for gap in result['gaps']))

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
        self.assertIn('p 按 milli/1000，整数与浮点同一数值结果一致；单位未经本仓库真实联网核对', note)
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
        self.assertEqual(payload['compare']['both'], ['000001.SZ'])
        self.assertEqual(payload['compare']['only_primary'], ['600000.SH'])
        self.assertEqual(payload['compare']['only_backup'], ['920001.BJ'])
        self.assertIsNone(forbidden(json.dumps(payload, ensure_ascii=False)))
        self.assertEqual(denied, 403)
        self.assertEqual(body['reason'], 'demo_read_only')
        self.assertEqual(wide, 200)
        self.assertIsNone(breadth['day'])
        self.assertTrue(any('已忽略' in note for note in breadth['notes']))


if __name__ == '__main__':
    unittest.main()
