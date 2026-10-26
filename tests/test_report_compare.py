import json
from pathlib import Path
import tempfile
import unittest

from analysis import Analysis
from compare import compare_reports


class ReportCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.a=Analysis(Path(self.tmp.name)/'reports.sqlite3',None,None,None,None)
        self.day='2026-03-21'

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self,day=None,**changes):
        day=day or self.day
        t=dict(close=10,change1=1,change20=5,bias20=2,volume_ratio5=1.2,rsi14=55,
               ma5=10,ma10=9.9,ma20=9.8,ma60=9,macd_dif=.1,macd_dea=.05,
               macd_hist=.1,sample=80,asof=day,method='same-method')
        t.update(changes)
        return dict(code='600487.SH',date=day,generated_at=day+'T16:00:00+08:00',technical=t)

    def insert(self,identifier,day=None,created=None,status='complete',**changes):
        day=day or self.day;p=self.payload(day,**changes)
        with self.a.db() as db:
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',
                       (identifier,'600487.SH',day,created or day+'T16:00:00+08:00',status,'done',json.dumps(p),None))

    def test_first_analysis_and_future_exclusion(self):
        self.insert('future','2026-03-22');self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['status'],'first_analysis')
        self.assertIn('首次分析',delta['status_text'])
        self.assertEqual(delta['rows'],[])

    def test_same_day_versions_use_earlier_created_report(self):
        self.insert('early',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('current')
        self.insert('late',created=self.day+'T18:00:00+08:00',close=11)
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['rule'],'same_day_previous_version')
        self.assertEqual(delta['rows'][0]['old'],9)
        self.assertEqual(delta['rows'][0]['new'],10)

    def test_historical_baseline_precedes_same_day_version(self):
        self.insert('previous','2026-03-20',close=8)
        self.insert('same-day',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['rule'],'same_code_earlier_observation_day_latest')
        self.assertEqual(delta['rows'][0]['old'],8)

    def replace_technical(self,identifier,values):
        with self.a.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM reports WHERE id=?',(identifier,)).fetchone()[0])
            payload['technical']=values;encoded=json.dumps(payload)
            db.execute('UPDATE reports SET payload=? WHERE id=?',(encoded,identifier))
        return encoded

    def test_unusable_complete_history_falls_back_to_valid_same_day_report(self):
        self.insert('bad-history','2026-03-20')
        self.insert('same-good',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('current')
        unusable=[None,{},dict(sample=0,close=None),dict(sample=0,close=10),
                  dict(sample=80,close=None),dict(sample=80,close=0),
                  dict(sample=80,close=float('nan')),dict(sample=80,close=float('inf'))]
        for values in unusable:
            with self.subTest(technical=values):
                encoded=self.replace_technical('bad-history',values)
                delta=self.a.get('current')['delta']
                self.assertEqual(delta['selection']['rule'],'same_day_previous_version')
                self.assertEqual(delta['selection']['old_date'],self.day)
                self.assertEqual(delta['status'],'comparable')
                close=next(r for r in delta['rows']if r['metric']=='close')
                self.assertEqual((close['old'],close['new'],close['diff']),(9,10,1))
                with self.a.db() as db:
                    row=db.execute('SELECT status,payload FROM reports WHERE id=?',('bad-history',)).fetchone()
                self.assertEqual((row['status'],row['payload']),('complete',encoded))

    def test_skips_unusable_latest_history_but_preserves_cross_day_priority(self):
        self.insert('valid-history','2026-03-19',close=8)
        self.insert('bad-history','2026-03-20',sample=0,close=None)
        self.insert('same-good',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['rule'],'same_code_earlier_observation_day_latest')
        self.assertEqual(delta['selection']['old_date'],'2026-03-19')
        self.assertEqual(delta['rows'][0]['old'],8)

    def test_unusable_same_day_version_and_future_version_are_not_baselines(self):
        self.insert('same-good',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('same-bad',created=self.day+'T12:00:00+08:00',sample=0,close=None)
        self.insert('current')
        self.insert('same-future',created=self.day+'T18:00:00+08:00',close=11)
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['rule'],'same_day_previous_version')
        self.assertEqual(delta['rows'][0]['old'],9)

    def test_only_unusable_or_future_history_remains_first_analysis(self):
        self.insert('bad-history','2026-03-20',sample=0,close=None)
        self.insert('future','2026-03-22')
        self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['status'],'first_analysis')
        self.assertEqual(delta['rows'],[])

    def test_valid_history_with_different_method_is_not_skipped_for_matching_same_day(self):
        self.insert('history','2026-03-20',method='other-method',close=8)
        self.insert('same-good',created=self.day+'T10:00:00+08:00',close=9)
        self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['old_date'],'2026-03-20')
        self.assertEqual(delta['status'],'incomparable')
        self.assertTrue(all(r['hide_direction']for r in delta['rows']))

    def test_short_valid_history_is_not_discarded_for_missing_long_window_indicators(self):
        self.insert('short-history','2026-03-20',sample=1,close=9,change1=None,
                    ma5=None,ma10=None,ma20=None,ma60=None,change20=None,bias20=None,
                    volume_ratio5=None,rsi14=None,macd_dif=None,macd_dea=None,macd_hist=None)
        self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['selection']['old_date'],'2026-03-20')
        self.assertEqual(delta['status'],'limited')
        self.assertEqual(delta['rows'][0]['old'],9)

    def test_old_report_missing_change1_and_read_is_non_mutating(self):
        self.insert('old','2026-03-20',change1=None);self.insert('current')
        with self.a.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM reports WHERE id=?',('old',)).fetchone()[0])
            del payload['technical']['change1']
            original=json.dumps(payload)
            db.execute('UPDATE reports SET payload=? WHERE id=?',(original,'old'))
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['status'],'limited')
        row=next(r for r in delta['rows'] if r['metric']=='change1')
        self.assertIsNone(row['old']);self.assertIsNone(row['diff'])
        with self.a.db() as db:
            self.assertEqual(db.execute('SELECT payload FROM reports WHERE id=?',('old',)).fetchone()[0],original)

    def test_window_sensitive_rows_hide_direction(self):
        self.insert('old','2026-03-20',sample=250);self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['status'],'limited')
        for row in delta['rows']:
            if row['metric'] in ('rsi14','macd_hist'):
                self.assertTrue(row['hide_direction'])
                self.assertEqual(row['direction'],'window_sensitive')
        self.assertEqual(len(delta['rows']),8)
        self.assertEqual(len(delta['raw']['deltas']),14)

    def test_different_methods_suppress_all_directions(self):
        self.insert('old','2026-03-20',method='other');self.insert('current')
        delta=self.a.get('current')['delta']
        self.assertEqual(delta['status'],'incomparable')
        self.assertTrue(all(r['hide_direction'] for r in delta['rows']))
        self.assertTrue(all(not r['comparable'] for r in delta['rows']))

    def test_contract_direction_values_cover_real_outputs(self):
        schema=json.loads((Path(__file__).resolve().parents[1]/'contracts/compare.schema.json').read_text())
        allowed=schema['properties']['deltas']['items']['properties']['direction']['enum']
        for changes in ({'sample':250},{'method':'other'},{'change1':None}):
            result=compare_reports(self.payload('2026-03-20',**changes),self.payload())
            self.assertTrue(all(r['direction'] in allowed for r in result['deltas']))
