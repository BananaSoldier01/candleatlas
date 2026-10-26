import tempfile
import unittest
from market import Market, DataError, board_counts, align_ranks


class MarketTests(unittest.TestCase):
    def test_categories_preserve_total_and_missing(self):
        counts, unknown = board_counts([{'continue_day_cnt': n} for n in [1, 1, 2, 3, 4, 5, 9, None, 0]])
        self.assertEqual(counts, [2, 1, 1, 1, 2])
        self.assertEqual(unknown, 2)
        self.assertEqual(sum(counts) + unknown, 9)

    def test_trading_days_exclude_weekend_and_keep_missing(self):
        result = align_ranks(['2026-09-18', '2026-09-21', '2026-09-22'],
                             [{'date': '2026-09-18', 'rank': 40}, {'date': '2026-09-19', 'rank': 1},
                              {'date': '2026-09-21', 'rank': 0}])
        self.assertEqual([i['rank'] for i in result], [40, None, None])

    def test_pool_reads_all_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            calls = []
            def fake(endpoint, params, ttl):
                calls.append(params['page'])
                return {'pagination': {'total': 201}, 'item': [
                    {'thscode': str(i)} for i in (range(200) if params['page'] == 1 else [200])]}
            market.get = fake
            self.assertEqual(len(market.pool('2026-09-18')), 201)
            self.assertEqual(calls, [1, 2])

    def test_partial_pool_is_not_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.get = lambda *a, **kw: {'pagination': {'total': 3}, 'item': []}
            with self.assertRaises(DataError):
                market.pool('2026-09-18')

    def test_failed_day_is_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.window = lambda *a: ['2026-09-18']
            def fail(day):
                raise DataError('数据尚未准备')
            market.pool = fail
            self.assertIsNone(market.counts('2026-09-18', 5)['items'][0]['total'])

    def test_selected_list_matches_counts_without_extra_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.window = lambda *a: ['2026-09-17', '2026-09-18']
            calls = []
            def pool(day):
                calls.append(day)
                return [{'thscode': day, 'continue_day_cnt': 2}]
            market.pool = pool
            result = market.counts('2026-09-18', 5)
            self.assertEqual(calls, ['2026-09-17', '2026-09-18'])
            self.assertEqual(result['stocks'][0]['thscode'], '2026-09-18')
            self.assertEqual(len(result['stocks']), result['items'][-1]['total'])

    def test_prices_keep_missing_days_and_exclude_future(self):
        import datetime as dt
        from market import TZ
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.window = lambda *a: ['2026-09-17', '2026-09-18']
            def fake(endpoint, params, ttl):
                self.assertEqual(params['adjust'], 'forward')
                self.assertEqual(dt.datetime.fromtimestamp(params['end']/1000, TZ).date().isoformat(), '2026-09-18')
                return {'item': [{'date_ms': int(dt.datetime(2026, 9, day, tzinfo=TZ).timestamp()*1000),
                                  'close_price': day} for day in (17, 21)]}
            market.get = fake
            result = market.prices('002185.SZ', '2026-09-18')
            self.assertEqual([i['date'] for i in result['items']], ['2026-09-17', '2026-09-18'])
            self.assertEqual([i['close_price'] for i in result['items']], [17, None])

class PriceRangeTests(unittest.TestCase):
    def test_custom_range_excludes_warmup_and_preserves_previous_close(self):
        import datetime as dt
        from market import TZ
        with tempfile.TemporaryDirectory() as directory:
            m = Market(directory)
            m.calendar = lambda: ['2026-09-17', '2026-09-18', '2026-09-21']
            m.get = lambda *a, **k: {'item': [{'date_ms': int(dt.datetime(2026, 9, day, tzinfo=TZ).timestamp()*1000), 'close_price': day} for day in (17, 18, 21)]}
            result = m.prices('600519.SH', '2026-09-21', 20, '2026-09-18')
            self.assertEqual([x['date'] for x in result['items']], ['2026-09-18', '2026-09-21'])
            self.assertEqual(result['previous_close'], 17)
            with self.assertRaises(DataError): m.prices('600519.SH', '2026-09-21', 20, '2026-09-22')
            with self.assertRaises(DataError): m.prices('600519.SH', '2026-09-21', 999)


class PriceContextTests(unittest.TestCase):
    def test_context_uses_one_request_preserves_visible_range_and_prior_close(self):
        import datetime as dt
        from market import TZ
        with tempfile.TemporaryDirectory() as directory:
            market=Market(directory)
            dates=[(dt.date(2026,1,1)+dt.timedelta(days=i)).isoformat() for i in range(100)]
            market.calendar=lambda:dates
            calls=[]
            def fake(endpoint,params,ttl):
                calls.append(params)
                return {'item':[{'date_ms':int(dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),TZ).timestamp()*1000),'close_price':i+10}
                                for i,day in enumerate(dates+['2026-04-11']) if i!=10]}
            market.get=fake
            result=market.prices('000811.SZ',dates[-1],20,include_context=True)
            self.assertEqual(len(calls),1)
            self.assertEqual(result['items'][0]['date'],dates[-20])
            self.assertEqual(result['previous_close'],89)
            self.assertEqual(len(result['context_items']),100)
            self.assertIsNone(result['context_items'][10]['close_price'])
            self.assertLessEqual(result['context_items'][-1]['date'],dates[-1])
            self.assertEqual(dt.datetime.fromtimestamp(calls[0]['start']/1000,TZ).date().isoformat(),dates[0])

    def test_context_is_opt_in_and_does_not_expand_custom_range(self):
        import datetime as dt
        from market import TZ
        with tempfile.TemporaryDirectory() as directory:
            market=Market(directory)
            dates=[(dt.date(2026,1,1)+dt.timedelta(days=i)).isoformat() for i in range(90)]
            market.calendar=lambda:dates
            market.get=lambda *a,**k:{'item':[{'date_ms':int(dt.datetime.combine(dt.date.fromisoformat(day),dt.time(),TZ).timestamp()*1000),'close_price':i+10} for i,day in enumerate(dates)]}
            self.assertNotIn('context_items',market.prices('000811.SZ',dates[-1],20))
            result=market.candles('000811.SZ',dates[-1],'day',20,dates[-3],include_context=True)
            self.assertEqual([r['date'] for r in result['items']],dates[-3:])
            self.assertEqual(len(result['context_items']),90)
            self.assertEqual(result['previous_close'],96)
            with self.assertRaises(DataError):market.candles('000811.SZ',dates[-1],'day',20,'2027-01-01',include_context=True)


if __name__ == '__main__':
    unittest.main()
