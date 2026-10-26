import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from tracking import Tracking, followup
from rankings import Rankings
from theme_clues import ThemeClues
from market import DataError, TZ


class TrackingTests(unittest.TestCase):
    def test_persist_import_idempotent_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'records.sqlite3';store=Tracking(path)
            record={'id':'legacy-1','thscode':'600487.SH','name':'亨通光电','date':'2026-09-18','note':'观察放量','createdAt':'2026-09-18T10:00:00+08:00'}
            store.save({'action':'import','items':[record]})
            store.save({'action':'import','items':[record]})
            self.assertEqual(len(Tracking(path).list()['items']),1)
            with self.assertRaises(DataError):store.save({'action':'import','items':[{**record,'id':'new'}, {**record,'thscode':'bad'}]})
            self.assertEqual(len(store.list()['items']),1)
            store.save({'action':'archive','id':'legacy-1','archived':True})
            self.assertEqual(store.list()['items'][0]['active'],0)
            store.save({'action':'import','items':[record]})
            self.assertEqual(store.list()['items'][0]['active'],0)

    def test_followup_trading_days_missing_never_forward_filled(self):
        market=Mock();market.calendar.return_value=['2026-09-17','2026-09-18','2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25']
        def quote(day,price):return {'date_ms':int(dt.datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()*1000),'close_price':price}
        market.get.return_value={'item':[quote('2026-09-17',10),quote('2026-09-18',11),quote('2026-09-21',20),quote('2026-09-24',9)]}
        result=followup(market,'600487.SH','2026-09-17','2026-09-24')
        self.assertEqual([x['change'] for x in result['items']],[10,None,-10,None])
        self.assertEqual(result['items'][1]['date'],'2026-09-22')
        self.assertEqual(result['items'][3]['status'],'尚未到期')
        market.get.reset_mock();followup(market,'600487.SH','2026-09-17','2026-09-17');market.get.assert_not_called()

    def test_breadth_partition_missing_and_no_live_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Mock();m.cache_dir=Path(tmp);m.calendar.return_value=['2026-09-18','2026-09-21']
            r=Rankings(m)
            rows=[{'thscode':str(i),'last_price':10,'volume':10,'price_change_ratio_pct':v,'turnover':100} for i,v in enumerate([-6,-5,-3,-1,0,1,3,5,6,None])]
            rows.append({'thscode':'suspended','last_price':10,'volume':0,'price_change_ratio_pct':0})
            stamp=int(dt.datetime.fromisoformat('2026-09-21T15:00:00+08:00').timestamp()*1000)
            r.market_snapshot=Mock(return_value={'items':rows,'timestamp':stamp,'source_date':'2026-09-21','received':11,'universe':12})
            d=r.overview('2026-09-21');self.assertEqual(d['bins'],[2,1,1,1,1,1,2]);self.assertEqual(d['excluded'],2);self.assertEqual(d['turnover_sample'],10)
            with self.assertRaises(DataError):r.overview('2026-09-18')
            self.assertEqual(r.market_snapshot.call_count,1)

    def test_history_retains_departed_members_and_missing_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=Mock();m.cache_dir=Path(tmp);m.calendar.return_value=['2026-09-17','2026-09-18','2026-09-21']
            r=Rankings(m);c=ThemeClues(m,r)
            r.save('2026-09-18-anomaly.json',{'item':[{'thscode':'A','keyword_list':['芯片']},{'thscode':'B','keyword_list':['芯片']}]})
            r.save('2026-09-21-anomaly.json',{'item':[{'thscode':'B','keyword_list':['芯片']},{'thscode':'C','keyword_list':['芯片']}]})
            r.save('2026-09-21-market.json',{'source_date':'2026-09-21','items':[{'thscode':'A','price_change_ratio_pct':-6,'volume':10,'last_price':10}]})
            d=c.history('2026-09-21','topics','芯片')
            self.assertEqual([x['count'] for x in d['items']],[None,2,2]);self.assertEqual((d['entered'],d['left']),(1,1))
            self.assertEqual(d['cohort'][0]['retained'],False);self.assertEqual(d['average'],-6);self.assertEqual(d['sample'],1)
            self.assertEqual(c.history('2026-09-21','concept','chip')['items'][-1]['count'],None)
            m.get.assert_not_called()
