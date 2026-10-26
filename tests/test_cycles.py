import tempfile
import unittest
from market import Market, DataError

class CycleTests(unittest.TestCase):
    def test_week_ohlc_volume_and_missing_days(self):
        with tempfile.TemporaryDirectory() as folder:
            m=Market(folder)
            m.prices=lambda *a: {'items':[
                {'date':'2026-09-04','open_price':8,'high_price':10,'low_price':7,'close_price':9,'volume':20},
                {'date':'2026-09-07','open_price':10,'high_price':13,'low_price':9,'close_price':12,'volume':30},
                {'date':'2026-09-08','open_price':12,'high_price':15,'low_price':11,'close_price':14,'volume':40},
                {'date':'2026-09-09','open_price':None,'high_price':None,'low_price':None,'close_price':None,'volume':None}], 'end':'2026-09-09'}
            data=m.candles('600519.SH','2026-09-09','week',4)
            self.assertEqual(len(data['items']),2)
            bar=data['items'][-1]
            self.assertEqual([bar[k] for k in ('open_price','high_price','low_price','close_price','volume','missing_days')],[10,15,9,14,70,1])
            self.assertEqual(bar['start_date'],'2026-09-07')
            self.assertEqual(len(m.candles('600519.SH','2026-09-09','month',3)['items']),1)
            with self.assertRaises(DataError):m.candles('600519.SH','2026-09-09','minute',5)
