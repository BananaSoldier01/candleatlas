import tempfile
import unittest
from pathlib import Path
from rankings import Rankings, sort_quotes
from market import DataError


def row(code, pct, turnover=100):
    return dict(thscode=code, name=code, price_change_ratio_pct=pct, turnover=turnover, last_price=10, volume=100)


class FakeMarket:
    def __init__(self, directory): self.cache_dir=Path(directory); self.calls=[]
    def calendar(self): return ['2026-09-21','2026-09-22']
    def hot(self, day): return {'items':[dict(thscode='A',name='A',rank=2)]}
    def get(self, endpoint, params, ttl):
        self.calls.append((endpoint,params))
        if endpoint.startswith('meta'): return {'item':[]}
        if endpoint=='prices/snapshot':
            return {'item':[row('A' if params['offset']==0 else 'B', 1)], 'total':501, 'timestamp':1790060400000}
        raise AssertionError(endpoint)


class RankingTests(unittest.TestCase):
    def test_sort_and_invalid_quotes(self):
        rows=[row('A',2,30),row('B',-3,80),row('C',0,10),row('D',None),{**row('E',50),'volume':0}]
        self.assertEqual([r['thscode'] for r in sort_quotes(rows,'gainers')],['A'])
        self.assertEqual([r['thscode'] for r in sort_quotes(rows,'losers')],['B'])
        self.assertEqual(sort_quotes(rows,'turnover')[0]['thscode'],'D')

    def test_history_never_fetches_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMarket(tmp); r=Rankings(m)
            with self.assertRaises(DataError): r.get('2026-09-21','gainers')
            self.assertEqual(r.get('2026-09-21','hot')['items'][0]['rank'],2)
            self.assertEqual(m.calls,[])

    def test_all_code_pages_and_shared_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMarket(tmp); r=Rankings(m)
            d=r.market_snapshot()
            self.assertEqual(d['universe'],501);self.assertEqual(d['received'],2)
            self.assertEqual([p['offset'] for e,p in m.calls if e=='prices/snapshot'],[0,500])
            before=len(m.calls);r.market_snapshot();self.assertEqual(len(m.calls),before)
            self.assertTrue((r.directory/(d['source_date']+'-market.json')).exists())

    def test_failed_pagination_does_not_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMarket(tmp); old=m.get
            def duplicate(endpoint, params, ttl):
                d=old(endpoint,params,ttl)
                if endpoint=='prices/snapshot':d['item'][0]['thscode']='A'
                return d
            m.get=duplicate;r=Rankings(m)
            with self.assertRaises(DataError):r.market_snapshot()
            self.assertEqual(list(r.directory.iterdir()),[])

class MoverTests(unittest.TestCase):
    def test_threshold_full_universe_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=FakeMarket(tmp);r=Rankings(m)
            snapshot={'items':[row('A',5),row('B',-7),row('C',4.9)],'source_date':'2026-09-22','timestamp':1790060400000,'universe':3,'received':3}
            r.market_snapshot=lambda:snapshot
            self.assertEqual([x['thscode'] for x in r.movers('2026-09-22','up',5)['items']],['A'])
            self.assertEqual([x['thscode'] for x in r.movers('2026-09-22','down',7)['items']],['B'])
            self.assertEqual(r.movers('2026-09-22','down',10)['total'],0)
            with self.assertRaises(DataError):r.movers('2026-09-21')
            with self.assertRaises(DataError):r.movers('2026-09-22',threshold=float('nan'))
            snapshot['source_date']='2026-09-21'
            with self.assertRaises(DataError):r.movers('2026-09-22')
