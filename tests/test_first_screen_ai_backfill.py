"""首屏 AI 调用状态与生成日相对观察日。合成数据、临时库、Mock，不读真实配置。"""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from analysis import Analysis
from first_screen import attach_disclosure, disclosure_items
from market import DataError


def ai_item(report, row=None, delta=None):
    payload = dict(row or {})
    payload.setdefault('report', report)
    items = disclosure_items(payload, report, delta)
    return next(item for item in items if item['key'] == 'ai')


def prices(count=80):
    start = dt.date(2026, 1, 1)
    return [{'date': (start + dt.timedelta(days=i)).isoformat(), 'close_price': 10 + i, 'volume': 100}
            for i in range(count)]


class AiCallStateTests(unittest.TestCase):
    def test_technical_only_with_explicit_model_none(self):
        item = ai_item({'ai': None, 'model': None}, {'status': 'complete'})
        self.assertEqual(item['text'], '仅程序计算，未调用 AI')
        self.assertEqual(item['level'], 'ok')

    def test_usable_ai_names_the_model(self):
        item = ai_item({'ai': {'overview': [{'text': '核对', 'evidence': ['T1']}]}, 'model': 'demo-model'})
        self.assertEqual(item['text'], '含 AI 解读（demo-model）')

    def test_call_or_parse_failure_does_not_claim_uninvoked(self):
        for error in ('模型响应失败', '模型未返回有效结构化报告，技术分析已保留。'):
            with self.subTest(error=error):
                item = ai_item(
                    {'ai': None, 'model': 'demo-model'},
                    {'status': 'partial', 'error': error},
                )
                self.assertNotIn('未调用', item['text'])
                self.assertIn('无可用 AI 解读', item['text'])
                self.assertEqual(item['level'], 'warn')

    def test_running_with_configured_model_does_not_claim_uninvoked(self):
        item = ai_item({'ai': None, 'model': 'demo-model'}, {'status': 'running'})
        self.assertEqual(item['text'], 'AI 解读生成中')
        self.assertNotIn('未调用', item['text'])

    def test_legacy_report_without_model_key_is_unknown(self):
        for report in ({'ai': None}, {'ai': None, 'overview': []}):
            with self.subTest(report=report):
                item = ai_item(report)
                self.assertIn('状态未知', item['text'])
                self.assertNotIn('未调用', item['text'])

    def test_empty_ai_dict_is_no_result(self):
        unknown = ai_item({'ai': {}})
        self.assertIn('状态未知', unknown['text'])
        self.assertNotIn('未调用', unknown['text'])
        technical = ai_item({'ai': {}, 'model': None})
        self.assertEqual(technical['text'], '仅程序计算，未调用 AI')

    def test_attach_disclosure_reads_row_status_and_error(self):
        row = {
            'status': 'partial',
            'error': '模型响应失败',
            'phase': '解读未完成，已取得的材料保留',
            'report': {'ai': None, 'model': 'demo-model'},
        }
        attach_disclosure(row)
        item = next(entry for entry in row['first_screen'] if entry['key'] == 'ai')
        self.assertNotIn('未调用', item['text'])
        self.assertIn('无可用 AI 解读', item['text'])

    def test_reason_does_not_echo_stack_or_secret(self):
        item = ai_item(
            {'ai': None, 'model': 'demo-model'},
            {'status': 'partial', 'error': 'Traceback (most recent call last):\n  File "x.py", line 1\nsk-secret-key'},
        )
        self.assertEqual(item['text'], '无可用 AI 解读')
        self.assertNotIn('sk-', item['text'])
        self.assertNotIn('Traceback', item['text'])


class AiFailurePipelineTests(unittest.TestCase):
    def engine(self, folder):
        market = Mock()
        market.calendar.return_value = ['2026-03-21']
        market.prices.return_value = {'items': prices()}
        news = Mock()
        news.stock.return_value = {'items': []}
        model = Mock()
        model.read.return_value = {'model': 'fake-model', 'base_url': 'http://localhost/v1', 'key': 'test-key'}
        model.complete.side_effect = DataError('模型响应失败')
        return Analysis(Path(folder) / 'reports.sqlite3', market, news, Mock(), model)

    def test_analysis_run_model_error_is_attempted_not_uninvoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.engine(tmp)
            with analysis.db() as db:
                db.execute(
                    'INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                    ('job', '600487.SH', '2026-03-21', '2026-03-21T16:00:00+08:00',
                     'running', 'test', None, None),
                )
            analysis.run('job', '600487.SH', '测试', '2026-03-21', '', True, {'model': 'fake-model'})
            viewed = analysis.get('job')
            self.assertEqual(viewed['status'], 'partial')
            self.assertIsNone(viewed['report']['ai'])
            self.assertEqual(viewed['report']['model'], 'fake-model')
            item = next(entry for entry in viewed['first_screen'] if entry['key'] == 'ai')
            self.assertNotIn('未调用', item['text'])
            self.assertIn('无可用 AI 解读', item['text'])
            analysis.model.complete.assert_called()
            self.assertNotIn('test-key', json.dumps(viewed, ensure_ascii=False, default=str))
