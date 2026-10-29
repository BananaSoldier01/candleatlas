import json
from pathlib import Path
import tempfile
import unittest
from analysis import Analysis
from tracking import Tracking
from workbench import summary

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)
        self.t=Tracking(p/'records.db');self.a=Analysis(p/'reports.db',None,None,None,None)
    def tearDown(self):self.tmp.cleanup()
    def note(self,code='600487.SH',day='2026-09-22'):
        self.t.save(dict(thscode=code,name='测试股票',date=day,note='核对业绩'))
    def report(self,id,day,status='complete',asof=None):
        payload={'technical':{'close':10,'asof':asof or day,'trend':'均线交错'},'ai':{'watch':[{'text':'查看财报','evidence':['T1']}]}}
        with self.a.db() as db:db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(id,'600487.SH',day,day+'T16:00:00+08:00',status,'分析完成',json.dumps(payload),None))
    def test_group_cutoff_and_archive(self):
        self.note();self.note(day='2026-09-23');self.note('000636.SZ','2026-09-25')
        d=summary(self.t,self.a,'2026-09-23')
        self.assertEqual(d['counts'],{'stocks':1,'pending':1,'ready':0,'records':2})
        self.assertEqual(d['future_records'],1);self.assertEqual(d['items'][0]['observed'],'2026-09-23')
        for r in self.t.list()['items']:self.t.save({'action':'archive','id':r['id']})
        self.assertEqual(summary(self.t,self.a,'2026-09-23')['items'],[])
    def test_report_never_uses_future(self):
        self.note();self.report('a','2026-09-22');self.report('b','2026-09-24')
        d=summary(self.t,self.a,'2026-09-23')['items'][0]
        self.assertEqual(d['report']['id'],'a');self.assertEqual(d['status'],'outdated')
        self.report('c','2026-09-23');self.assertEqual(summary(self.t,self.a,'2026-09-23')['items'][0]['status'],'ready')
    def test_incomplete_and_stale_prices(self):
        self.note();self.report('a','2026-09-23',asof='2026-09-22')
        self.assertEqual(summary(self.t,self.a,'2026-09-23')['items'][0]['status'],'outdated')
        with self.a.db() as db:db.execute("UPDATE reports SET status='partial'")
        self.assertEqual(summary(self.t,self.a,'2026-09-23')['items'][0]['status'],'incomplete')

    def test_optional_assessment_for_old_and_new_reports(self):
        self.note();self.report('old','2026-09-23')
        self.assertIsNone(summary(self.t,self.a,'2026-09-23')['items'][0]['assessment'])
        from tech_score import evaluate
        assessment=evaluate({'sample':1,'close':10,'asof':'2026-09-23'})
        with self.a.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM reports WHERE id=?',('old',)).fetchone()[0])
            payload['assessment']=assessment
            db.execute('UPDATE reports SET payload=? WHERE id=?',(json.dumps(payload),'old'))
        item=summary(self.t,self.a,'2026-09-23')['items'][0]['assessment']
        self.assertEqual(item['rule_version'],assessment['rule_version'])
        self.assertEqual(item['coverage'],assessment['coverage'])
        self.assertIsNone(item['components']['volume_coord'])

    def test_status_priority_is_completion_not_price(self):
        day='2026-09-23'
        specs=[
            ('600003.SH','ready','complete',day,day),
            ('600001.SH','outdated','complete','2026-09-22','2026-09-22'),
            ('600008.SH','missing',None,None,None),
            ('600005.SH','missing',None,None,None),
            ('600002.SH','incomplete','partial',day,day),
            ('600000.SH','running','running',day,day),
        ]
        for code,kind,status,report_day,asof in specs:
            self.t.save(dict(thscode=code,name='测试'+code,date=day,note='核对'))
            if kind=='missing':continue
            payload={'technical':{'close':10,'asof':asof,'trend':'均线交错'}}
            with self.a.db() as db:
                db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)',(code,code,report_day,report_day+'T16:00:00+08:00',status,'分析完成',json.dumps(payload),None))
        result=summary(self.t,self.a,day)
        self.assertEqual([item['status'] for item in result['items']],['incomplete','missing','missing','outdated','running','ready'])
        self.assertEqual([item['thscode'] for item in result['items']],['600002.SH','600005.SH','600008.SH','600001.SH','600000.SH','600003.SH'])
        self.assertEqual(result['counts'],{'stocks':6,'pending':4,'ready':1,'records':6})
        self.assertTrue(all(item['note']=='核对' for item in result['items']))
