import json
import tempfile
import unittest
from intraday import Intraday, parse_bars
from market import DataError

class IntradayTests(unittest.TestCase):
    def test_parse_and_invalid(self):
        row={'day':'2026-09-22 15:00:00','open':'10','high':'12','low':'9','close':'11','volume':'100'}
        self.assertEqual(parse_bars('=('+json.dumps([row])+');')[0]['close'],11)
        for rows in ([], [row,row], [{**row,'close':'NaN'}], [{**row,'low':'13'}]):
            with self.assertRaises(DataError):parse_bars('=('+json.dumps(rows)+');')

    def test_selected_cutoff_missing_day_and_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            m=Intraday(folder)
            dates=['2026-09-15','2026-09-16','2026-09-17','2026-09-18','2026-09-21','2026-09-22']
            m.bars=lambda *a:{'fetched_at':0,'items':[{'time':day+' 15:00','close':10+i} for i,day in enumerate(dates) if day!='2026-09-18']}
            d=m.series('600519.SH','2026-09-21','five',1,120,dates)
            self.assertEqual(d['last_time'],'2026-09-21 15:00')
            self.assertEqual(d['missing_dates'],['2026-09-18'])
            with self.assertRaises(DataError):m.series('600519.SH','2026-09-18','intraday',1,120,dates)
            d=m.series('600519.SH','2026-09-22','intraday',1,120,dates)
            self.assertEqual(len(d['items']),1)
            self.assertEqual(d['previous_close'],14)

    def test_minute_count_and_unsupported_market(self):
        with tempfile.TemporaryDirectory() as folder:
            m=Intraday(folder)
            with self.assertRaises(DataError):m.bars('920001.BJ',1)
            with self.assertRaises(DataError):m.bars('600519.SH',2)
            m.bars=lambda *a:{'fetched_at':0,'items':[{'time':f'2026-09-22 10:{i:02d}','close':10} for i in range(60)]}
            d=m.series('600519.SH','2026-09-22','minute',5,60,['2026-09-22'])
            self.assertEqual(len(d['items']),60)
            self.assertEqual(d['interval'],5)
