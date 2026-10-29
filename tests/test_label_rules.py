"""UI rule copy stays aligned with the calculators it describes."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LabelRuleSourceTests(unittest.TestCase):
    def setUp(self):
        self.workbench = (ROOT / 'workbench.py').read_text()
        analysis = (ROOT / 'analysis.py').read_text()
        start = analysis.index('def technical')
        self.technical = analysis[start:analysis.index('\ndef has_usable')]
        self.rankings = (ROOT / 'rankings.py').read_text()
        self.market = (ROOT / 'market.py').read_text()
        self.rules = (ROOT / 'web' / 'label-rules.js').read_text()
        self.overview = (ROOT / 'web' / 'overview.js').read_text()

    def test_status_words_match_workbench_priority(self):
        self.assertIn("status='missing' if not report else 'running' if report['status']=='running' else 'incomplete' if report['status']!='complete' or not t.get('close') else 'outdated' if report['day']<day or t.get('asof')!=day else 'ready'", self.workbench)
        self.assertIn("priority={'incomplete':0,'missing':1,'outdated':2,'running':3,'ready':4}", self.workbench)
        self.assertIn("r['status'] in ('missing','outdated','incomplete')", self.workbench)
        for phrase in (
            '观察日及以前没有保存的分析报告',
            '状态不是 running',
            '报告状态不是 complete',
            '行情截至日不同于当前观察日',
            '行情截至日也等于当前观察日',
            '排序为分析不完整、尚未分析、分析待更新',
            '不按涨跌或评分排序',
        ):
            self.assertIn(phrase, self.rules)

    def test_trend_and_sample_gates_match_technical(self):
        self.assertIn("values['trend']='数据不足'", self.technical)
        self.assertIn('if n>=20:', self.technical)
        self.assertIn('if n>=15:', self.technical)
        self.assertIn('if n>=60:', self.technical)
        self.assertIn("values['trend']='均线多头排列' if a>b>d else '均线空头排列' if a<b<d else '均线交错'", self.technical)
        for phrase in ('MA5 > MA10 > MA20', 'MA5 < MA10 < MA20', '不少于 20 根', '少于 20 根', '15 根连续有效收盘', '60 根连续有效收盘'):
            self.assertIn(phrase, self.rules)

    def test_breadth_bins_and_break_rate_match_sources(self):
        self.assertIn('sum(v<=-5 for v in values),sum(-5<v<=-3 for v in values),sum(-3<v<0 for v in values),sum(v==0 for v in values),sum(0<v<3 for v in values),sum(3<=v<5 for v in values),sum(v>=5 for v in values)', self.rankings)
        for phrase in ('含 −5%', '不含 −5%', '含 −3%', '不含两端', '含 3%', '不含 5%', '含 5%', '平盘'):
            self.assertIn(phrase, self.rules)
        self.assertIn("LabelRules.inlineRule('breadth.bins')", self.overview)
        self.assertIn("touched = {s['thscode'] for s in (up or []) + (broken or [])}", self.market)
        self.assertIn("'break_rate': len(broken)/len(touched)*100 if up is not None and broken is not None and touched else None", self.market)
        self.assertIn('按代码去重后的并集', self.rules)
        self.assertIn('不记为 0', self.rules)
        self.assertIn("LabelRules.inlineRule('temperature.break_rate')", self.overview)
