import datetime as dt
import tempfile
import unittest
from market import Market, DataError, TZ
from research import themes, promotions


class ResearchTests(unittest.TestCase):
    def test_theme_dedup_and_multi_membership(self):
        groups = themes([{'thscode': 'A', 'limit_up_reason': '芯片+芯片+算力', 'continue_day_cnt': 3},
                         {'thscode': 'B', 'limit_up_reason': '芯片', 'continue_day_cnt': 1}])
        self.assertEqual([(g['name'], g['count']) for g in groups], [('芯片', 2), ('算力', 1)])
        self.assertEqual(groups[0]['height'], 3)

    def test_promotion_only_exact_increment(self):
        previous = [{'thscode': c, 'continue_day_cnt': n} for c, n in [('A', 2), ('B', 3), ('C', 2), ('D', 1)]]
        current = [{'thscode': c, 'continue_day_cnt': n} for c, n in [('A', 3), ('C', 5), ('D', 2)]]
        result = {r['thscode']: r['status'] for r in promotions(previous, current)}
        self.assertEqual(result, {'A': '晋级', 'B': '未入当日涨停池', 'C': '计数待核对'})

    def test_research_missing_source_not_zero_and_unique_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.window = lambda *a: ['2026-09-18', '2026-09-21']
            def pool(day, kind):
                if kind == 'down': raise DataError('上游失败')
                return [{'thscode': 'A', 'continue_day_cnt': 2}, {'thscode': 'B', 'continue_day_cnt': 3}] if kind == 'up' else [{'thscode': 'B'}, {'thscode': 'C'}]
            market.pool = pool
            result = market.research('2026-09-21')
            self.assertIsNone(result['summary']['down'])
            self.assertAlmostEqual(result['summary']['break_rate'], 200/3)
            self.assertEqual(len(result['errors']), 2)

    def test_review_uses_next_trading_day_and_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            market = Market(directory)
            market.calendar = lambda: ['2026-09-18', '2026-09-21', '2026-09-22']
            market.get = lambda *a, **kw: {'item': [
                {'date_ms': int(dt.datetime(2026,9,d,tzinfo=TZ).timestamp()*1000), 'close_price': p}
                for d,p in [(18,10),(21,11)]]}
            pending = market.review('600519.SH', '2026-09-18', '2026-09-18')
            self.assertEqual(pending['status'], '等待下一交易日')
            result = market.review('600519.SH', '2026-09-18', '2026-09-22')
            self.assertEqual(result['next_date'], '2026-09-21')
            self.assertAlmostEqual(result['change'], 10)
            market.get = lambda *a, **kw: {'item': []}
            self.assertIsNone(market.review('600519.SH', '2026-09-18', '2026-09-22')['change'])


if __name__ == '__main__':
    unittest.main()
