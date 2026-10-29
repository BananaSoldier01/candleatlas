"""Invalidation lines for strong technical-profile components."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import Analysis, technical
from reading_notes import invalidation_lines
from tech_score import evaluate


def component(score, coverage=1, status='ok'):
    return {'score':score,'coverage':coverage,'status':status,'explanation':'分项解释'}


def payload(components, sample=80, asof='2026-09-18', date='2026-09-18', method='前复权日 K', warnings=None, total_note=''):
    return {
        'date':date,
        'technical':{'sample':sample,'asof':asof,'method':method,'close':10},
        'assessment':{
            'sample':sample,'asof':asof,
            'components':components,
            'warnings':['样本提示'] if warnings is None else warnings,
            'total':{'note':total_note},
        },
    }


class ReadingNoteTests(unittest.TestCase):
    def test_strong_weak_missing_and_old_report(self):
        lines=invalidation_lines(payload({
            'trend':component(80),'momentum':component(40),'overheat':component(75, coverage=0.5, status='partial'),
        }, warnings=['trend 与 momentum 共用 change20，trend 与 overheat 共用 bias20，已降权但未完全消除重复计分。']))
        by={line['component']:line for line in lines}
        self.assertEqual(list(by), ['trend','overheat'])
        self.assertEqual(by['trend']['score'],80)
        self.assertIn('前复权修订可能改变历史序列', by['trend']['text'])
        self.assertIn('重复计分', by['trend']['text'])
        self.assertNotIn('样本不足', by['trend']['text'])
        self.assertNotIn('partial', by['trend']['text'])
        self.assertIn('覆盖度不足 100%', by['overheat']['text'])
        self.assertIn('status=partial', by['overheat']['text'])
        self.assertNotIn('重复计分', by['overheat']['text'])
        self.assertNotIn('量能配合', by['overheat']['text'])
        for line in lines:
            self.assertIn('技术画像不是上涨概率。', line['text'])
        volume=invalidation_lines(payload({'volume_coord':component(88)}, sample=40, asof='2026-09-17', date='2026-09-18'))
        self.assertEqual(len(volume),1)
        text=volume[0]['text']
        self.assertIn('连续有效样本不足 60', text)
        self.assertIn('前复权修订可能改变历史序列', text)
        self.assertIn('观察日与行情截至日不一致', text)
        self.assertIn('量能配合依赖当日涨跌与当日成交量', text)
        plain=invalidation_lines(payload({'trend':component(80)}, method='未复权日 K', warnings=[]))
        self.assertNotIn('前复权修订', plain[0]['text'])
        self.assertIn('本次材料未标出样本、覆盖度或截至日方面的失效条件。', plain[0]['text'])
        missing_asof=invalidation_lines(payload({'trend':component(80)}, asof='', method='未复权日 K', warnings=[]))
        self.assertIn('行情截至日未取得，不能与观察日对齐', missing_asof[0]['text'])
        edge=invalidation_lines(payload({'overheat':component(70),'trend':component(69.9)}))
        self.assertEqual([line['component'] for line in edge], ['overheat'])
        for empty in (None, {}, {'technical':{'sample':80}}, {'assessment':{}}, {'assessment':{'components':'bad'}}):
            self.assertEqual(invalidation_lines(empty), [])

    def test_lines_follow_real_technical_profile(self):
        rows=[]
        start=dt.date(2026,1,5)
        for i in range(80):
            price=round(10+i*0.4, 4)
            rows.append({'date':(start+dt.timedelta(days=i)).isoformat(),'open_price':price,'high_price':price,'low_price':price,'close_price':price,'volume':1000+i*10})
        tech=technical(rows)
        assessment=evaluate(tech, {'source':'synthetic'})
        self.assertTrue(any('重复计分' in item and 'change20' in item for item in assessment['warnings']))
        lines=invalidation_lines({'date':tech['asof'],'technical':tech,'assessment':assessment})
        strong=[line for line in lines if line['component'] in ('trend','momentum')]
        self.assertTrue(strong)
        self.assertTrue(all(line['score']>=70 for line in strong))
        for line in strong:
            self.assertIn('重复计分', line['text'])
            self.assertIn('前复权修订可能改变历史序列', line['text'])
            self.assertNotIn('样本不足', line['text'])
            self.assertIn('技术画像不是上涨概率。', line['text'])

    def test_analysis_get_is_read_only_and_survives_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            analysis=Analysis(Path(tmp)/'reports.sqlite3', None, None, None, None)
            old={'evidence':[],'technical':{'close':10,'asof':'2026-09-18','sample':80}}
            strong=payload({'trend':component(82)})
            with analysis.db() as db:
                db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)', ('old','600487.SH','2026-09-18','2026-09-18T16:00:00+08:00','complete','完成', json.dumps(old), None))
                db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)', ('new','600487.SH','2026-09-18','2026-09-18T16:00:00+08:00','complete','完成', json.dumps(strong), None))
            with analysis.db() as db:
                before={row['id']:row['payload'] for row in db.execute('SELECT id,payload FROM reports')}
            self.assertEqual(analysis.get('old')['reading_notes'], [])
            notes=analysis.get('new')['reading_notes']
            self.assertEqual(len(notes),1)
            self.assertIn('技术画像不是上涨概率。', notes[0]['text'])
            self.assertIn('delta', analysis.get('new'))
            with analysis.db() as db:
                after={row['id']:row['payload'] for row in db.execute('SELECT id,payload FROM reports')}
            self.assertEqual(after, before)
            self.assertNotIn('reading_notes', json.loads(after['new']))
            with patch('reading_notes.invalidation_lines', side_effect=RuntimeError('boom')):
                broken=analysis.get('new')
            self.assertEqual(broken['reading_notes'], [])
            self.assertIn('delta', broken)
