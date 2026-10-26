"""Default 1/1p observer regression, replay timing and real HTTP contract tests."""
import copy
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import hashlib
import math
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/chan_candidates.json').read_text())
SCENARIOS = {name: item['rows'] for name, item in FIXTURE['scenarios'].items()}


def sample_hash(rows):
    fields = ('date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume')
    return hashlib.sha256(json.dumps([{k: row[k] for k in fields if k in row} for row in rows],
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

from chan_structure import calculate
from chan_candidates import Collector
from market import DataError
from server import Handler

ROWS = SCENARIOS['C01_multi_zs_breakout']
CUTOFF = ROWS[-1]['date']
CLOSED = '2099-01-01'


def calc(rows=ROWS, **kwargs):
    return calculate(rows, kwargs.pop('cutoff', CUTOFF), closed_before=kwargs.pop('closed_before', CLOSED),
                     include_candidates=True, **kwargs)


def strip(value):
    result = copy.deepcopy(value)
    result.pop('candidate_meta', None)
    for frame in result['frames']:
        frame.pop('candidates', None)
        frame.pop('candidate_events', None)
    return result


def signal_frame(frame):
    # A different requested input window has a different provenance hash.
    # Candidate identity, attributes, event timing and first_seen remain exact.
    frame = copy.deepcopy(frame)
    for event in frame['candidate_events']:
        event.pop('sample_id')
    return frame


class ProtocolTests(unittest.TestCase):
    def test_default_and_optin_preserve_structures(self):
        for name, rows in SCENARIOS.items():
            end = rows[-1]['date']
            expected = FIXTURE['scenarios'][name]['baseline']
            self.assertEqual(calculate(rows, end, CLOSED), expected, name)
            self.assertEqual(strip(calc(rows, cutoff=end)), expected, name)

    def test_all_daily_prefixes_with_full_candidate_attributes(self):
        total, targets, nontargets = 0, 0, 0
        for name, rows in SCENARIOS.items():
            full = calc(rows, cutoff=rows[-1]['date'])
            for index, frame in enumerate(full['frames']):
                prefix = calc(rows[:index + 1], cutoff=frame['date'])
                self.assertEqual(signal_frame(prefix['frames'][-1]), signal_frame(frame), (name, frame['date']))
                for event in prefix['frames'][-1]['candidate_events']:
                    self.assertEqual(event['sample_id'], sample_hash(rows[:index + 1]))
                for candidate in frame['candidates']:
                    self.assertEqual(candidate['confirmation'], 'unknown')
                    self.assertTrue(set(candidate['types']) <= {'1', '1p'})
                    self.assertLessEqual(candidate['pivot_date'], candidate['first_seen_at'])
                    self.assertLessEqual(candidate['first_seen_at'], frame['date'])
                    self.assertEqual(candidate['last_seen_at'], frame['date'])
                    targets += candidate['is_target']
                    nontargets += not candidate['is_target']
                for event in frame['candidate_events']:
                    self.assertEqual(event['observed_at'], frame['date'])
                    self.assertEqual(event['confirmation'], 'unknown')
                    self.assertEqual(event['sample_id'], sample_hash(rows))
                total += 1
        self.assertEqual(len(SCENARIOS), 13)
        self.assertEqual(total, 609)
        self.assertGreater(targets, 0)
        self.assertGreater(nontargets, 0)

    def test_future_rows_and_current_bar_excluded(self):
        cutoff = ROWS[39]['date']
        historical = calc(ROWS, cutoff=cutoff)
        self.assertEqual(historical, calc(ROWS[:40], cutoff=cutoff))
        dirty = copy.deepcopy(ROWS)
        for row in dirty[40:]:
            row.update(close_price=99999, high_price=100000, low_price=.1)
        self.assertEqual(historical, calc(dirty, cutoff=cutoff))
        current = calc(ROWS, cutoff=ROWS[-1]['date'], closed_before=cutoff)
        self.assertEqual(current, calc(ROWS[:39], cutoff=ROWS[-1]['date'], closed_before=cutoff))

    def test_gap_context_and_last_bad_bar(self):
        for index in (10, 30, 50):
            rows = copy.deepcopy(ROWS)
            rows[index]['high_price'] = None
            with_gap = calc(rows)
            tail = calc(rows[index + 1:])
            self.assertEqual(with_gap['frames'], tail['frames'])
            self.assertEqual(with_gap['start'], rows[index + 1]['date'])
        rows = copy.deepcopy(ROWS)
        rows[-1]['close_price'] = float('nan')
        self.assertEqual(calc(rows)['frames'], [])

    def test_invalid_rows_do_not_bridge_history(self):
        for bad in (True, float('inf'), float('-inf'), 0, -1):
            rows = copy.deepcopy(ROWS)
            rows[20]['close_price'] = bad
            self.assertEqual(calc(rows)['frames'], calc(rows[21:])['frames'])

    def test_bad_order_dates_and_empty_input(self):
        for rows in (ROWS[::-1], ROWS + ROWS):
            with self.assertRaises(DataError):
                calc(rows)
        bad = copy.deepcopy(ROWS)
        bad[10]['date'] = '2026-01-11x'
        with self.assertRaises(ValueError):
            calc(bad)
        self.assertEqual(calc([])['frames'], [])
        self.assertEqual(calc(ROWS[:4])['frames'][-1]['candidates'], [])

    def test_repeated_calls_do_not_mutate_rows_or_rules(self):
        rows = copy.deepcopy(ROWS)
        before = copy.deepcopy(rows)
        first = calc(rows)
        self.assertEqual(calc(rows), first)
        self.assertEqual(rows, before)
        self.assertEqual(first['rules'], FIXTURE['scenarios']['C01_multi_zs_breakout']['baseline']['rules'])

    def test_full_250_bar_window(self):
        rows = []
        for i in range(250):
            price = 50 + 8 * math.sin(i / 7) + 4 * math.sin(i / 23)
            rows.append(dict(date=(dt.date(2024, 1, 1) + dt.timedelta(days=i)).isoformat(),
                             open_price=price - .2, close_price=price + .2,
                             high_price=price + 1, low_price=price - 1, volume=100))
        result = calc(rows, cutoff=rows[-1]['date'])
        self.assertEqual(result['sample'], 250)
        self.assertEqual(strip(result), calculate(rows, rows[-1]['date'], CLOSED))
        json.dumps(result, allow_nan=False)
        for length in (60, 120, 250):
            prefix = calc(rows[:length], cutoff=rows[length - 1]['date'])
            self.assertEqual(signal_frame(prefix['frames'][-1]), signal_frame(result['frames'][length - 1]))

    def test_candidate_failure_does_not_break_structures_or_claim_empty(self):
        with patch.object(Collector, 'observe', side_effect=RuntimeError('synthetic candidate fault')):
            result = calc()
        self.assertEqual(result['candidate_meta']['status'], 'failed')
        self.assertTrue(all(f['candidates'] is None for f in result['frames']))
        self.assertEqual(strip(result), FIXTURE['scenarios']['C01_multi_zs_breakout']['baseline'])
        with patch.object(Collector, '__init__', side_effect=RuntimeError('synthetic init fault')):
            self.assertEqual(calc()['candidate_meta']['status'], 'failed')
            self.assertNotIn('candidate_meta', calculate(ROWS, CUTOFF, CLOSED))

    def test_unsupported_types_are_not_displayed(self):
        import chan_candidates as observer
        item = {'source': 'bi_bsp', 'is_buy': True, 'pivot_date': ROWS[0]['date'],
                'pivot_price': 10, 'types': ['unknown', '4'], 'is_target': True}
        with patch.object(observer, '_visible_points', return_value=[item]):
            self.assertEqual(Collector(ROWS).observe(None, ROWS[1]['date']),
                             {'candidates': [], 'candidate_events': []})

    def test_late_snapshot_first_seen_is_not_backdated(self):
        # Protocol boundary fixture only; this is not upstream type-coverage evidence.
        import chan_candidates as observer
        point = {'source': 'bi_bsp_1only', 'is_buy': True, 'pivot_date': ROWS[0]['date'],
                 'pivot_price': 10, 'types': ['1p'], 'is_target': False, 'bi_idx': 0,
                 'end_klu_idx': 0, 'stability': 'rewrite_zone'}
        day = ROWS[10]['date']
        with patch.object(observer, '_visible_points', return_value=[point]):
            result = Collector(ROWS).observe(None, day)
        self.assertEqual(result['candidates'][0]['first_seen_at'], day)
        self.assertNotEqual(result['candidates'][0]['first_seen_at'], point['pivot_date'])
        self.assertEqual(result['candidate_events'][0]['observed_at'], day)


class FakeMarket:
    def __init__(self):
        self.calls = []

    def prices(self, code, day, period):
        self.calls.append((code, day, period))
        if code not in ('600000.SH', '600001.SH'):
            raise DataError('unknown synthetic stock')
        return {'items': ROWS if code == '600000.SH' else SCENARIOS['C09_t3a_zs_break']}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.market = FakeMarket()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()

    def get(self, query, code='600000.SH'):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', '/api/chan?code=' + code + '&date=' + CUTOFF + query)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_actual_handler_default_optin_one_market_call(self):
        status, normal = self.get('')
        self.assertEqual(status, 200)
        self.assertNotIn('candidate_meta', normal)
        status, result = self.get('&candidates=1')
        self.assertEqual(status, 200)
        self.assertEqual(result['candidate_meta']['status'], 'ok')
        self.assertEqual(strip(result), normal)
        self.assertEqual(len(self.server.market.calls), 2)
        self.assertTrue(any(f['candidates'] for f in result['frames']))

    def test_bad_flag_rejected_before_upstream(self):
        self.assertEqual(self.get('&candidates=maybe')[0], 400)
        self.assertEqual(self.server.market.calls, [])

    def test_actual_handler_candidate_failure_keeps_structure_response(self):
        with patch.object(Collector, 'observe', side_effect=RuntimeError('fault')):
            status, result = self.get('&candidates=1')
        self.assertEqual(status, 200)
        self.assertEqual(result['candidate_meta']['status'], 'failed')
        self.assertEqual(strip(result), self.get('')[1])

    def test_concurrent_requests_are_independent(self):
        codes = ['600000.SH', '600001.SH', '600000.SH']
        expected = {code: self.get('&candidates=1', code)[1] for code in codes}
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda code: self.get('&candidates=1', code), codes))
        self.assertTrue(all(status == 200 and result == expected[code]
                            for code, (status, result) in zip(codes, results)))
