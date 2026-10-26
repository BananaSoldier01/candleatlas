import datetime as dt
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from analysis import Analysis, technical, validate_report
from model_service import ModelService
from tracking import Tracking
from market import DataError


def prices(count=80):
    start=dt.date(2026,1,1)
    return [{'date':(start+dt.timedelta(days=i)).isoformat(),'close_price':10+i,'volume':100} for i in range(count)]


def reply():
    return json.dumps({k:[{'text':'基于给定指标核对趋势，不能确认未来表现。','evidence':['T1']}] for k in ('overview','supporting','opposing','watch')})


class AnalysisTests(unittest.TestCase):
    def test_change1_uses_only_contiguous_valid_tail(self):
        for values, expected in (([],None),([10],None),([10,12],20),
                                 ([10,None,12],None),([10,None,12,9],-25),
                                 ([10,12,None],None)):
            with self.subTest(values=values):
                self.assertEqual(technical([{'date':'2026-03-21','close_price':v} for v in values])['change1'],expected)

    def test_assessment_saved_without_model_and_optional_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=self.engine(tmp)
            rows=prices();rows[-1]['close_price']=rows[-2]['close_price']*.927;rows[-1]['volume']=300
            a.market.prices.return_value={'items':rows}
            def run(identifier):
                with a.db() as db:db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(identifier,'600487.SH','2026-03-21','now','running','test',None,None))
                a.run(identifier,'600487.SH','测试','2026-03-21','',False,{})
                return a.get(identifier)
            d=run('scored');p=d['report']
            self.assertEqual(d['status'],'complete')
            self.assertEqual(p['technical']['change1'],-7.3)
            self.assertEqual(p['assessment']['components']['volume_coord']['score'],12)
            self.assertEqual(p['assessment']['coverage']['components_total'],4)
            with patch('tech_score.evaluate',side_effect=RuntimeError('synthetic failure')):
                failed=run('no-score')
            self.assertEqual(failed['status'],'complete')
            self.assertEqual(failed['report']['technical'],p['technical'])
            self.assertIsNone(failed['report']['assessment'])
            a.model.complete.assert_not_called()

    def test_indicators_and_gaps(self):
        rows=prices();t=technical(rows)
        self.assertEqual(t['ma5'],87);self.assertEqual(t['ma20'],79.5);self.assertEqual(t['rsi14'],100)
        self.assertEqual(t['volume_ratio5'],1);self.assertEqual(t['trend'],'均线多头排列')
        self.assertIsNotNone(t['macd_dif'])
        flat=technical([{**r,'close_price':10} for r in rows]);self.assertEqual(flat['rsi14'],50);self.assertEqual(flat['macd_hist'],0)
        rows[-10]['close_price']=None;t=technical(rows)
        self.assertEqual(t['sample'],9);self.assertIsNone(t['ma20']);self.assertIsNone(t['macd_dif'])
        rows[-1]['close_price']=None;self.assertIsNone(technical(rows)['close'])

    def test_citation_validation(self):
        self.assertEqual(len(validate_report(reply(),{'T1'})),4)
        with self.assertRaises(DataError):validate_report(reply(),{'N1'})
        with self.assertRaises(DataError):validate_report('不是 JSON',{'T1'})
        bad=json.loads(reply());bad['watch'][0]['evidence']=[]
        with self.assertRaises(DataError):validate_report(json.dumps(bad),{'T1'})

    def test_config_secret_preserved_and_origin_change_requires_reentry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.json';m=ModelService(path)
            d=m.save({'base_url':'https://example.com/v1','model':'test','key':'secret-test'})
            self.assertNotIn('secret-test',json.dumps(d));self.assertEqual(path.stat().st_mode&0o777,0o600)
            m.save({'base_url':'https://example.com/v1','model':'second'})
            self.assertEqual(m.read()['key'],'secret-test')
            with self.assertRaises(DataError):m.save({'base_url':'https://other.example/v1','model':'second'})
            with self.assertRaises(DataError):m.save({'base_url':'http://remote.example/v1','model':'second','key':'secret'})
            m.save({'base_url':'http://127.0.0.1:11434/v1','model':'local','clear_key':True})
            self.assertFalse(m.status()['has_key'])

    def engine(self,folder):
        market=Mock();market.calendar.return_value=['2026-03-21'];market.prices.return_value={'items':prices()}
        news=Mock();news.stock.return_value={'items':[{'time':'2026-03-22 10:00:00','title':'Future','url':'https://example.com'},{'time':'2026-03-20 10:00:00','title':'当前标题','url':'https://example.com'}]}
        model=Mock();model.read.return_value={'model':'test-model','base_url':'http://localhost/v1','key':'test-key'};model.complete.return_value=reply()
        return Analysis(Path(folder)/'reports.sqlite3',market,news,Mock(),model)

    def test_pipeline_excludes_future_news_and_historical_financial(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=self.engine(tmp)
            with patch('analysis.today',return_value='2026-09-26'):
                job=a.start({'code':'600487.SH','date':'2026-03-21','name':'测试','report':'2026-1','ai':True})
                for _ in range(100):
                    d=a.get(job['id'])
                    if d['status']!='running':break
                    time.sleep(.01)
            self.assertEqual(d['status'],'complete');self.assertIsNotNone(d['report']['ai'])
            a.themes.financial.assert_not_called()
            messages=a.model.complete.call_args.args[0]
            self.assertNotIn('Future',json.dumps(messages));self.assertNotIn('test-key',json.dumps(d))
            a.model.complete.return_value='invalid'
            job=a.start({'code':'600487.SH','date':'2026-03-21','ai':True})
            for _ in range(100):
                d=a.get(job['id'])
                if d['status']!='running':break
                time.sleep(.01)
            self.assertEqual(d['status'],'partial');self.assertIsNotNone(d['report']['technical']);self.assertIsNone(d['report']['ai'])
            self.assertEqual(len(a.history('600487.SH')['items']),2)

    def test_restart_preserves_materials_and_tracking_schema_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tracking.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE observations (id TEXT PRIMARY KEY,thscode TEXT,name TEXT,date TEXT,note TEXT,createdAt TEXT,active INTEGER)')
                db.execute("INSERT INTO observations VALUES ('old','600487.SH','旧记录','2026-03-21','保留理由','2026-03-21T10:00:00+08:00',1)")
            store=Tracking(path);self.assertEqual(store.list()['items'][0]['note'],'保留理由');self.assertEqual(store.list()['items'][0]['report_id'],'')
            record={'thscode':'600487.SH','name':'测试','date':'2026-03-21','note':'核对报告','report_id':'a'*32}
            saved=store.save(record);self.assertEqual(saved['items'][0]['report_id'],'a'*32)
            a=self.engine(tmp)
            with a.db() as db:db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',('pending','600487.SH','2026-03-21','now','running','准备中',json.dumps({'evidence':[]}),None))
            a=self.engine(tmp);self.assertEqual(a.get('pending')['status'],'interrupted');self.assertEqual(a.get('pending')['report'],{'evidence':[]})
