import datetime as dt
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

from market import DataError
from rankings import Rankings
from theme_clues import ThemeClues


DAY = '2026-10-23'
PREVIOUS = '2026-10-22'
OTHER = '2026-10-24'


def stamp(day):
    return int(dt.datetime.fromisoformat(day + 'T15:00:00+08:00').timestamp() * 1000)


def quote(day=DAY):
    return dict(source_date=day, timestamp=stamp(day), first_timestamp=stamp(day),
                universe=2, received=2, fetched_at=0,
                items=[dict(thscode='600497.SH', name='驰宏锌锗', price_change_ratio_pct=6,
                            turnover=200, last_price=10, volume=100),
                       dict(thscode='000811.SZ', name='冰轮环境', price_change_ratio_pct=-7,
                            turnover=100, last_price=20, volume=100)])


def anomaly(day=DAY, empty=False):
    return dict(timestamp=stamp(day), item=[] if empty else [
        dict(thscode='600497.SH', stock_name='驰宏锌锗', keyword_list=['业绩增长', '金属'],
             analysis_content='来源解读，非已核实原因')])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.market = Mock(cache_dir=Path(self.tmp.name))
        self.market.calendar.return_value = [PREVIOUS, DAY]
        self.rankings = Rankings(self.market)
        self.rankings.market_snapshot = Mock(return_value=quote(OTHER))
        self.clues = ThemeClues(self.market, self.rankings)

    def test_movers_prefer_matching_local_snapshot_without_fetching_latest(self):
        self.rankings.save(DAY + '-market.json', quote())
        self.assertEqual(self.rankings.movers(DAY, 'up')['items'][0]['thscode'], '600497.SH')
        self.rankings.market_snapshot.assert_not_called()

    def test_anomaly_prefers_matching_local_archive_without_upstream(self):
        self.rankings.save(DAY + '-anomaly.json', anomaly())
        self.market.get.return_value = anomaly(OTHER, empty=True)
        self.assertEqual(self.clues.catalog(DAY, 'topics')['items'][0]['count'], 1)
        self.market.get.assert_not_called()

    def test_both_mover_directions_overview_and_quote_rankings_share_local_data(self):
        self.rankings.save(DAY + '-market.json', quote())
        self.assertEqual(self.rankings.movers(DAY, 'down')['items'][0]['thscode'], '000811.SZ')
        self.assertEqual(self.rankings.overview(DAY)['up'], 1)
        self.assertEqual(self.rankings.get(DAY, 'gainers')['items'][0]['thscode'], '600497.SH')
        self.assertIn('本地快照', self.rankings.get(DAY, 'turnover')['note'])
        self.rankings.market_snapshot.assert_not_called()

    def test_historical_local_data_never_fetches_latest(self):
        self.rankings.save(PREVIOUS + '-market.json', quote(PREVIOUS))
        self.assertEqual(self.rankings.movers(PREVIOUS)['snapshot_source'], 'local')
        self.rankings.market_snapshot.assert_not_called()

    def test_missing_historical_snapshot_has_distinct_reason_without_upstream(self):
        with self.assertRaises(DataError) as caught:
            self.rankings.movers(PREVIOUS)
        self.assertEqual(caught.exception.reason, 'not_collected')
        self.rankings.market_snapshot.assert_not_called()

    def test_latest_without_local_data_may_use_matching_upstream(self):
        self.rankings.market_snapshot.return_value = quote()
        result = self.rankings.movers(DAY)
        self.assertEqual(result['snapshot_source'], 'upstream')
        self.assertEqual(result['total'], 1)
        self.rankings.market_snapshot.assert_called_once()

    def test_wrong_day_upstream_cannot_be_relabelled_or_saved_as_observation_day(self):
        with self.assertRaises(DataError) as caught:
            self.rankings.movers(DAY)
        self.assertEqual(caught.exception.reason, 'date_mismatch')
        self.assertIn(DAY, str(caught.exception)); self.assertIn(OTHER, str(caught.exception))
        self.assertFalse((self.rankings.directory / (DAY + '-market.json')).exists())

    def test_local_filename_and_source_date_do_not_override_actual_timestamp(self):
        data = quote(); data['timestamp'] = stamp(OTHER)
        self.rankings.save(DAY + '-market.json', data)
        with self.assertRaises(DataError) as caught:
            self.rankings.movers(DAY)
        self.assertEqual(caught.exception.reason, 'date_mismatch')
        self.rankings.market_snapshot.assert_not_called()

    def test_cross_day_first_page_is_rejected_even_with_matching_last_page(self):
        data = quote(); data['first_timestamp'] = stamp(PREVIOUS)
        self.rankings.market_snapshot.return_value = data
        with self.assertRaises(DataError): self.rankings.movers(DAY)

    def test_empty_upstream_snapshot_is_not_a_zero_mover_day(self):
        data = quote(); data['items'] = []
        self.rankings.market_snapshot.return_value = data
        with self.assertRaises(DataError) as caught:
            self.rankings.movers(DAY)
        self.assertEqual(caught.exception.reason, 'upstream_empty')

    def test_raw_empty_page_is_distinct_and_not_archived(self):
        self.market.get.return_value = dict(item=[], total=0, timestamp=stamp(DAY))
        with self.assertRaises(DataError) as caught:
            Rankings.market_snapshot(self.rankings)
        self.assertEqual(caught.exception.reason, 'upstream_empty')
        self.assertEqual(list(self.rankings.directory.iterdir()), [])

    def test_valid_snapshot_below_threshold_is_a_real_empty_filter_result(self):
        self.rankings.save(DAY + '-market.json', quote())
        result = self.rankings.movers(DAY, 'up', 10)
        self.assertEqual(result['total'], 0); self.assertEqual(result['items'], [])

    def test_missing_historical_anomaly_does_not_fetch_current(self):
        with self.assertRaises(DataError) as caught:
            self.clues.catalog(PREVIOUS, 'topics')
        self.assertEqual(caught.exception.reason, 'not_collected')
        self.market.get.assert_not_called()

    def test_matching_upstream_anomaly_is_saved_only_under_actual_day(self):
        self.market.get.return_value = anomaly()
        self.assertEqual(self.clues.catalog(DAY, 'finance')['snapshot_source'], 'upstream')
        self.assertEqual(self.rankings.read(DAY + '-anomaly.json')['timestamp'], stamp(DAY))

    def test_same_day_empty_anomaly_is_not_archived_or_claimed_as_no_events(self):
        self.market.get.return_value = anomaly(empty=True)
        with self.assertRaises(DataError) as caught:
            self.clues.catalog(DAY, 'topics')
        self.assertEqual(caught.exception.reason, 'upstream_empty')
        self.assertIsNone(self.rankings.read(DAY + '-anomaly.json'))

    def test_wrong_day_empty_anomaly_explains_both_date_and_empty_result(self):
        self.market.get.return_value = anomaly(OTHER, empty=True)
        with self.assertRaises(DataError) as caught:
            self.clues.catalog(DAY, 'topics')
        self.assertEqual(caught.exception.reason, 'date_mismatch')
        self.assertIn('空清单', str(caught.exception))
        self.assertIsNone(self.rankings.read(DAY + '-anomaly.json'))

    def test_wrong_day_local_anomaly_is_rejected(self):
        self.rankings.save(DAY + '-anomaly.json', anomaly(OTHER))
        with self.assertRaises(DataError) as caught:
            self.clues.catalog(DAY, 'topics')
        self.assertEqual(caught.exception.reason, 'date_mismatch')
        self.market.get.assert_not_called()

    def test_valid_anomaly_without_finance_keyword_is_not_missing_data(self):
        data = anomaly(); data['item'][0]['keyword_list'] = ['金属']
        self.rankings.save(DAY + '-anomaly.json', data)
        self.assertEqual(self.clues.catalog(DAY, 'finance')['items'], [])
        self.market.get.assert_not_called()

    def test_sector_detail_reuses_observation_day_quotes_not_latest_quotes(self):
        self.rankings.save(DAY + '-market.json', quote())
        self.market.get.side_effect = [dict(timestamp=stamp(OTHER), item=[dict(thscode='metal.TI', name='金属')]),
                                       dict(timestamp=stamp(OTHER), item=[dict(thscode='600497.SH', name='驰宏锌锗')])]
        result = self.clues.detail(DAY, 'concept', 'metal.TI')
        self.assertEqual(result['items'][0]['pct'], 6)
        self.assertEqual(result['quote_timestamp'], stamp(DAY))
        self.assertEqual(result['quote_source'], 'local')
        self.assertEqual(result['quote_warning'], '')
        self.rankings.market_snapshot.assert_not_called()

    def test_quote_failure_keeps_real_anomaly_but_leaves_percentages_missing(self):
        self.rankings.save(DAY + '-anomaly.json', anomaly())
        result = self.clues.detail(DAY, 'topics', '金属')
        self.assertEqual(result['items'][0]['analysis'], '来源解读，非已核实原因')
        self.assertIsNone(result['items'][0]['pct'])
        self.assertIsNone(result['quote_timestamp'])
        self.assertIn('日期不符', result['quote_warning'])
        self.assertIn('显示缺失', result['note'])

    def test_empty_sector_catalog_and_historical_membership_are_distinct(self):
        self.market.get.return_value = dict(item=[], timestamp=stamp(OTHER))
        with self.assertRaises(DataError) as caught: self.clues.catalog(DAY, 'concept')
        self.assertEqual(caught.exception.reason, 'upstream_empty')
        with self.assertRaises(DataError) as caught: self.clues.catalog(PREVIOUS, 'concept')
        self.assertEqual(caught.exception.reason, 'not_collected')

    def test_http_error_preserves_reason_for_all_three_conditions(self):
        from server import Handler
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.rankings = self.rankings
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            scenarios = [(PREVIOUS, quote(), 'not_collected'), (DAY, quote(OTHER), 'date_mismatch')]
            empty = quote(); empty['items'] = []; scenarios.append((DAY, empty, 'upstream_empty'))
            for day, snapshot, reason in scenarios:
                with self.subTest(reason=reason):
                    self.rankings.market_snapshot.return_value = snapshot
                    url = f'http://127.0.0.1:{server.server_port}/api/movers?date={day}'
                    with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(url, timeout=3)
                    with caught.exception as response: result = json.load(response)
                    self.assertEqual(caught.exception.code, 502)
                    self.assertEqual(result['reason'], reason); self.assertTrue(result['error'])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
