import inspect
import json
import unittest
import urllib.request

from backup_kline import (
    PHRASE_NO_NET_BAOSTOCK, PHRASE_NO_NET_TENCENT, PHRASE_NO_PACKAGE, PHRASE_SUSPEND,
    PHRASE_UNKNOWN, compare_daily, fetch_daily,
)
from backup_calendar import fetch_calendar
from market import DataError, Market


def _body(symbol, rows, **extra):
    node = {'qfqday': rows, **extra}
    return json.dumps({'code': 0, 'data': {symbol: node}}).encode()


def _row(date, open_, close, high, low, volume):
    return [date, str(open_), str(close), str(high), str(low), str(volume)]


class BackupKlineTests(unittest.TestCase):
    def test_default_does_not_touch_network(self):
        def boom(*args, **kwargs):
            raise AssertionError('network')
        original = urllib.request.urlopen
        urllib.request.urlopen = boom
        try:
            tencent = fetch_daily('600000.SH', '2024-01-05', 5, source='tencent')
            baostock = fetch_daily('600000.SH', '2024-01-05', 5, source='baostock',
                                   baostock_loader=lambda: (_ for _ in ()).throw(AssertionError('import')))
            calendar = fetch_calendar('2024-01-02', '2024-01-05',
                                      baostock_loader=lambda: (_ for _ in ()).throw(AssertionError('import')))
        finally:
            urllib.request.urlopen = original
        self.assertEqual(tencent['items'], [])
        self.assertEqual(tencent['gaps'][0]['reason'], PHRASE_NO_NET_TENCENT)
        self.assertEqual(tencent['source'], 'tencent')
        self.assertEqual(tencent['adjust'], 'forward')
        self.assertEqual(baostock['gaps'][0]['reason'], PHRASE_NO_NET_BAOSTOCK)
        self.assertEqual(calendar['dates'], [])
        self.assertEqual(calendar['source'], 'baostock')
        self.assertIn(PHRASE_NO_NET_BAOSTOCK, calendar['gaps'][0]['reason'])

    def test_tencent_maps_qfq_and_drops_bad_rows(self):
        seen = {}

        def fetch(url):
            seen['url'] = url
            rows = [
                _row('2024-01-02', '10.00', '10.50', '11.00', '9.50', '1000'),
                ['2024-01-03', '10', '12', '11', '9', '100'],
                ['2024-01-04', '10'],
                _row('2024-01-05', '10.50', '10.20', '10.80', '10.00', '800'),
            ]
            return _body('sh600000', rows, day=[_row('2024-01-02', '1', '1', '1', '1', '1')])

        result = fetch_daily('600000.SH', '2024-01-05', 2, source='tencent', fetch_bytes=fetch)
        self.assertIn('web.ifzq.gtimg.cn/appstock/app/fqkline/get', seen['url'])
        self.assertIn('qfq', seen['url'])
        self.assertIn('sh600000', seen['url'])
        self.assertEqual(result['source'], 'tencent')
        self.assertEqual(result['adjust'], 'forward')
        self.assertEqual(result['thscode'], '600000.SH')
        self.assertEqual([item['date'] for item in result['items']], ['2024-01-02', '2024-01-05'])
        self.assertEqual(result['items'][0]['open_price'], 10)
        self.assertEqual(result['items'][0]['close_price'], 10.5)
        self.assertEqual(result['items'][0]['high_price'], 11)
        self.assertEqual(result['items'][0]['low_price'], 9.5)
        self.assertEqual(result['items'][0]['volume'], 1000)
        self.assertTrue(all(item['close_price'] != 1 for item in result['items']))
        self.assertTrue(any(gap['date'] == '2024-01-03' and PHRASE_UNKNOWN in gap['reason'] for gap in result['gaps']))
        self.assertFalse(any(item['date'] == '2024-01-03' for item in result['items']))
        self.assertNotIn(0, [item.get('volume') for item in result['items']])

    def test_tencent_does_not_reuse_unadjusted_day(self):
        def fetch(url):
            return json.dumps({'code': 0, 'data': {'sh600000': {
                'day': [_row('2024-01-02', '1', '1', '1', '1', '1')]}}}).encode()

        result = fetch_daily('600000.SH', '2024-01-05', 2, source='tencent', fetch_bytes=fetch)
        self.assertEqual(result['items'], [])
        self.assertIn('qfqday', result['gaps'][0]['reason'])
        self.assertIn('未改用', result['gaps'][0]['reason'])
        self.assertIn(PHRASE_UNKNOWN, result['gaps'][0]['reason'])

    def test_baostock_suspension_and_forward_flag(self):
        seen = {}

        def query(symbol, start, end, adjustflag):
            seen.update(symbol=symbol, start=start, end=end, adjustflag=adjustflag)
            return [
                {'date': '2024-01-02', 'open': '10', 'high': '11', 'low': '9.5', 'close': '10.5',
                 'volume': '1000', 'tradestatus': '1'},
                {'date': '2024-01-03', 'open': '', 'high': '', 'low': '', 'close': '',
                 'volume': '', 'tradestatus': '0'},
                {'date': '2024-01-04', 'open': '10.5', 'high': '11', 'low': '10', 'close': '10.8',
                 'volume': '0', 'tradestatus': 0},
                {'date': '2024-01-05', 'open': '10.8', 'high': '11.2', 'low': '10.4', 'close': '11',
                 'volume': '900', 'tradestatus': 1},
            ]

        result = fetch_daily('000001.SZ', '2024-01-05', 2, source='baostock', baostock_query=query)
        self.assertEqual(seen['symbol'], 'sz.000001')
        self.assertEqual(seen['adjustflag'], '2')
        self.assertEqual(seen['end'], '2024-01-05')
        self.assertLessEqual(seen['start'], '2024-01-02')
        self.assertEqual(result['source'], 'baostock')
        self.assertEqual(result['adjust'], 'forward')
        self.assertEqual([item['date'] for item in result['items']], ['2024-01-02', '2024-01-05'])
        self.assertTrue(all(PHRASE_SUSPEND in gap['reason'] for gap in result['gaps'] if gap['date'] in ('2024-01-03', '2024-01-04')))
        self.assertFalse(any(item['date'] in ('2024-01-03', '2024-01-04') for item in result['items']))

    def test_baostock_import_failure_is_a_gap(self):
        def loader():
            raise ImportError('mocked missing baostock')

        result = fetch_daily('600000.SH', '2024-01-05', 3, source='baostock',
                             allow_network=True, baostock_loader=loader)
        self.assertEqual(result['items'], [])
        self.assertIn(PHRASE_NO_PACKAGE, result['gaps'][0]['reason'])
        self.assertIn('未登录', result['gaps'][0]['reason'])
        calendar = fetch_calendar('2024-01-02', '2024-01-05', allow_network=True, baostock_loader=loader)
        self.assertEqual(calendar['dates'], [])
        self.assertIn(PHRASE_NO_PACKAGE, calendar['gaps'][0]['reason'])

    def test_fake_session_uses_adjustflag_and_logs_out(self):
        class Result:
            def __init__(self, error_code='0', rows=None, fields=None):
                self.error_code = error_code
                self.fields = fields or []
                self.rows = rows or []
                self.index = 0
            def next(self):
                if self.index >= len(self.rows):
                    return False
                self.index += 1
                return True
            def get_row_data(self):
                return self.rows[self.index - 1]

        class Session:
            def __init__(self):
                self.calls = []
            def login(self):
                self.calls.append('login')
                return Result()
            def logout(self):
                self.calls.append('logout')
            def query_history_k_data_plus(self, symbol, fields, start_date, end_date, frequency, adjustflag):
                self.calls.append(('k', symbol, frequency, adjustflag))
                return Result(rows=[['2024-01-05', '10', '11', '9', '10.5', '100', '1']],
                              fields=['date', 'open', 'high', 'low', 'close', 'volume', 'tradestatus'])

        session = Session()
        result = fetch_daily('600000.SH', '2024-01-05', 1, source='baostock',
                             allow_network=True, baostock_loader=lambda: session)
        self.assertEqual(result['items'][0]['close_price'], 10.5)
        self.assertEqual(result['adjust'], 'forward')
        self.assertEqual(session.calls, ['login', ('k', 'sh.600000', 'd', '2'), 'logout'])

        class Boom(Session):
            def query_history_k_data_plus(self, *args, **kwargs):
                self.calls.append('k')
                raise RuntimeError('upstream')

        failed = Boom()
        broken = fetch_daily('600000.SH', '2024-01-05', 1, source='baostock',
                             allow_network=True, baostock_loader=lambda: failed)
        self.assertEqual(broken['items'], [])
        self.assertIn('query_history_k_data_plus', broken['gaps'][0]['reason'])
        self.assertIn('未改走其他源', broken['gaps'][0]['reason'])
        self.assertEqual(failed.calls, ['login', 'k', 'logout'])

    def test_sources_are_not_stitched(self):
        def tencent(url):
            return _body('sh600000', [
                _row('2024-01-02', '10', '10', '11', '9', '100'),
                _row('2024-01-03', '11', '12', '12', '10', '110'),
            ])

        def query(symbol, start, end, adjustflag):
            return [
                {'date': '2024-01-03', 'open': '11', 'high': '12', 'low': '10', 'close': '11.5',
                 'volume': '110', 'tradestatus': '1'},
                {'date': '2024-01-04', 'open': '9', 'high': '10', 'low': '8', 'close': '9.5',
                 'volume': '120', 'tradestatus': '1'},
            ]

        def banned_query(*args, **kwargs):
            raise AssertionError('baostock should not run')

        def banned_fetch(url):
            raise AssertionError('tencent should not run')

        left = fetch_daily('600000.SH', '2024-01-04', 2, source='tencent',
                           fetch_bytes=tencent, baostock_query=banned_query)
        right = fetch_daily('600000.SH', '2024-01-04', 2, source='baostock',
                            baostock_query=query, fetch_bytes=banned_fetch)
        diff = compare_daily(left, right)
        self.assertNotIn('items', diff)
        self.assertFalse(diff['merged'])
        self.assertEqual(diff['left_source'], 'tencent')
        self.assertEqual(diff['right_source'], 'baostock')
        self.assertEqual(diff['only_left'], ['2024-01-02'])
        self.assertEqual(diff['only_right'], ['2024-01-04'])
        self.assertEqual(diff['value_diffs'], [
            {'date': '2024-01-03', 'field': 'close_price', 'left': 12, 'right': 11.5}])
        self.assertNotIn('2024-01-04', [item['date'] for item in left['items']])
        self.assertNotIn('2024-01-02', [item['date'] for item in right['items']])

    def test_beijing_exchange_is_an_explicit_gap(self):
        def boom(*args, **kwargs):
            raise AssertionError('should not request')
        for source in ('tencent', 'baostock'):
            result = fetch_daily('920001.BJ', '2024-01-05', 5, source=source,
                                allow_network=True, fetch_bytes=boom, baostock_query=boom,
                                baostock_loader=boom)
            self.assertEqual(result['items'], [])
            self.assertTrue(result['gaps'])
            self.assertIn('北交所', result['gaps'][0]['reason'])

    def test_shortfall_does_not_invent_suspension_or_zeros(self):
        def fetch(url):
            return _body('sh600000', [_row('2024-01-02', '10', '10', '11', '9', '100'),
                                      _row('2024-01-04', '10', '10', '11', '9', '100')])
        result = fetch_daily('600000.SH', '2024-01-05', 5, source='tencent', fetch_bytes=fetch)
        self.assertEqual([item['date'] for item in result['items']], ['2024-01-02', '2024-01-04'])
        self.assertFalse(any(item['date'] == '2024-01-03' for item in result['items']))
        self.assertTrue(any(PHRASE_UNKNOWN in gap['reason'] for gap in result['gaps']))
        self.assertFalse(any(PHRASE_SUSPEND in gap['reason'] for gap in result['gaps']))

    def test_market_prices_and_calendar_stay_on_hithink(self):
        prices = inspect.getsource(Market.prices)
        calendar = inspect.getsource(Market.calendar)
        self.assertIn('prices/historical', prices)
        self.assertNotIn('tencent', prices.lower())
        self.assertNotIn('baostock', prices.lower())
        self.assertIn('calendar/trading-days', calendar)
        self.assertNotIn('baostock', calendar.lower())

    def test_rejects_unknown_source(self):
        with self.assertRaises(DataError):
            fetch_daily('600000.SH', '2024-01-05', 5, source='eastmoney')
        with self.assertRaises(TypeError):
            fetch_daily('600000.SH', '2024-01-05', 5)


class BackupCalendarTests(unittest.TestCase):
    def test_mock_keeps_trading_days_only(self):
        def query(start, end):
            self.assertEqual((start, end), ('2024-01-05', '2024-01-08'))
            return [
                {'calendar_date': '2024-01-06', 'is_trading_day': '0'},
                {'calendar_date': '2024-01-08', 'is_trading_day': '1'},
                {'calendar_date': '2024-01-05', 'is_trading_day': 1},
                {'calendar_date': '2024-01-07', 'is_trading_day': ''},
            ]

        result = fetch_calendar('2024-01-05', '2024-01-08', baostock_query=query)
        self.assertEqual(result['source'], 'baostock')
        self.assertEqual(result['dates'], ['2024-01-05', '2024-01-08'])
        self.assertTrue(any(gap['date'] == '2024-01-07' and PHRASE_UNKNOWN in gap['reason'] for gap in result['gaps']))
        self.assertNotIn('2024-01-06', result['dates'])

    def test_fake_session_logs_out_and_does_not_invent_weekdays(self):
        class Result:
            error_code = '0'
            fields = ['calendar_date', 'is_trading_day']
            def __init__(self):
                self.rows = [['2024-01-06', '0']]
                self.index = 0
            def next(self):
                if self.index >= len(self.rows):
                    return False
                self.index += 1
                return True
            def get_row_data(self):
                return self.rows[self.index - 1]

        class Session:
            def __init__(self):
                self.calls = []
            def login(self):
                self.calls.append('login')
                return Result()
            def logout(self):
                self.calls.append('logout')
            def query_trade_dates(self, start_date, end_date):
                self.calls.append(('dates', start_date, end_date))
                return Result()

        session = Session()
        result = fetch_calendar('2024-01-06', '2024-01-08', allow_network=True, baostock_loader=lambda: session)
        self.assertEqual(result['dates'], [])
        self.assertNotIn('2024-01-08', result['dates'])
        missing = [gap for gap in result['gaps'] if gap['date'] == '2024-01-08']
        self.assertEqual(len(missing), 1)
        self.assertIn('未按周末或工作日规则补入', missing[0]['reason'])
        self.assertIn(PHRASE_UNKNOWN, missing[0]['reason'])
        self.assertEqual(session.calls[0], 'login')
        self.assertEqual(session.calls[1][0], 'dates')
        self.assertEqual(session.calls[-1], 'logout')

    def test_demo_prices_do_not_call_backup_sources(self):
        from demo import Demo
        demo = Demo()
        payload = demo.get('/api/prices', {'code': ['600000.SH'], 'date': [demo.day], 'period': ['20']})
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('tencent', text)
        self.assertNotIn('baostock', text)
        self.assertEqual(payload['adjust'], 'forward')
        self.assertTrue(payload['items'])
