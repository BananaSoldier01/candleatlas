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
        self.assertEqual([item['thscode'] for item in result['items']], ['600000.SH', '000001.SZ'])
        first, second = result['items']
        self.assertEqual(first['continue_day_cnt'], 3)
        self.assertEqual(first['limit_up_time'], '09:25:00')
        self.assertEqual(first['last_limit_time'], '09:32:01')
        self.assertEqual(first['open_count'], 1)
        self.assertAlmostEqual(first['latest_price'], 11.55)
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
        self.assertTrue(any('空池' in note for note in empty['notes']))
        refused = em.fetch_limit_pool(DAY, fetch_bytes=b'{"rc": 1, "data": {"tc": 1, "pool": [{"c": "600000", "m": 1}]}}')
        self.assertEqual(refused['items'], [])
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
        self.assertNotIn('0', item['bins'])
        self.assertTrue(any('未拼接' in gap for gap in result['gaps']))
        other = em.fetch_market_breadth(fetch_bytes=b'{"data": {"f104": 10, "f105": 3, "qdate": 20260231}}')
        self.assertEqual(other['items'], [])
        self.assertIsNone(other['day'])
        self.assertIn('getTopicZDFenBu', other['gaps'][0])
        self.assertIn('未改读其他接口', other['gaps'][0])
        self.assertTrue(any('无法解析' in note for note in other['notes']))
        flat = em.fetch_market_breadth(fetch_bytes=b'{"data": {"fenbu": {"0": 0, "1": 2}}}')
        self.assertEqual(flat['items'][0]['flat'], 0)
        self.assertEqual(flat['items'][0]['sample'], 2)

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
        self.assertEqual(payload['items'][0]['thscode'], '300001.SZ')
        self.assertIn('/getTopicZBPool', seen[0])
        self.assertNotIn('/getTopicZTPool', seen[0])

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
