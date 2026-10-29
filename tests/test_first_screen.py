"""首屏披露、证据类型与数据缺口。只用合成序列和临时库。"""
import datetime as dt
import json
import tempfile
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch

from analysis import PROMPT_VERSION, Analysis, technical
from demo import Demo
from first_screen import (MACD_MIN_BARS, RSI14_MIN_BARS, disclosure_items, evidence_kind,
                          evidence_kinds, gap_impacts)
from server import STATIC, Handler
from tech_score import evaluate


BANNED = ('应买', '应卖', '看多', '看空', '目标价', '胜率', '上涨概率')


def bars(count, volume=100):
    start = dt.date(2024, 1, 2)
    return [{'date': (start + dt.timedelta(days=i)).isoformat(), 'close_price': 10 + i * 0.13,
             'volume': volume} for i in range(count)]


def clause(text, name):
    part = text.split('；')[0] if name == 'rsi' else text.split('；', 1)[1]
    if '不够' in part:
        return '不够'
    if '够' in part:
        return '够'
    raise AssertionError(part)


def screen(report, delta=None):
    items = disclosure_items({'report': report}, report, delta)
    return {item['key']: item for item in items}


def covers(gap, item):
    text = gap['text']
    if item == 'macd':
        return 'MACD' in text
    if item == 'rsi14':
        return 'RSI14' in text
    if item == 'volume_ratio5':
        return 'volume_ratio5' in text and '为 0' not in text
    if item == 'volume_ratio5==0':
        return 'volume_ratio5 为 0' in text
    if item == 'change20':
        return text.startswith('change20')
    if item == 'change1':
        return text.startswith('当日涨跌')
    if item == 'bias20':
        return text.startswith('bias20')
    if item == 'trend':
        return text.startswith('趋势标签')
    return False


class DisclosureTests(unittest.TestCase):
    def test_five_items_keep_order_and_do_not_score(self):
        report = {'date': '2024-06-03', 'generated_at': '2024-06-03T16:00:00+08:00',
                  'technical': {'asof': '2024-06-03', 'sample': 80}, 'ai': None, 'model': None}
        items = disclosure_items({}, report, {'status': 'comparable', 'reasons': []})
        self.assertEqual([item['key'] for item in items], ['dates', 'sample', 'baseline', 'backfill', 'ai'])
        for item in items:
            self.assertIn(item['level'], ('ok', 'note', 'warn'))
            self.assertNotIsInstance(item['level'], (int, float))
            for word in BANNED:
                self.assertNotIn(word, item['text'] + item['label'])

    def test_dates_match_mismatch_and_missing_technical(self):
        matched = screen({'date': '2024-06-03', 'technical': {'asof': '2024-06-03', 'sample': 80}})
        self.assertEqual(matched['dates']['text'], '一致：观察日与数据日均为 2024-06-03')
        self.assertEqual(matched['dates']['level'], 'ok')
        drifted = screen({'date': '2024-06-03', 'technical': {'asof': '2024-06-01', 'sample': 80}})
        self.assertEqual(drifted['dates']['text'], '不一致：观察日 2024-06-03，数据日 2024-06-01')
        self.assertEqual(drifted['dates']['level'], 'warn')
        for report in (None, {}, {'technical': None}, {'date': '2024-06-03'}):
            item = screen(report)['dates']
            self.assertEqual(item['text'], '行情未取得', report)
        blank = screen({'date': '2024-06-03', 'technical': {'sample': 3, 'asof': None}})
        self.assertEqual(blank['dates']['text'], '未取得')
        self.assertEqual(len(disclosure_items(None, None, None)), 5)

    def test_sample_thresholds_match_technical_behavior(self):
        self.assertIsNone(technical(bars(RSI14_MIN_BARS - 1))['rsi14'])
        self.assertIsNotNone(technical(bars(RSI14_MIN_BARS))['rsi14'])
        short_macd = technical(bars(MACD_MIN_BARS - 1))
        long_macd = technical(bars(MACD_MIN_BARS))
        self.assertIsNone(short_macd['macd_dif'])
        self.assertIsNone(short_macd['macd_dea'])
        self.assertIsNone(short_macd['macd_hist'])
        self.assertIsNotNone(long_macd['macd_dif'])
        self.assertIsNotNone(long_macd['macd_hist'])
        for count, rsi_flag, macd_flag in (
                (14, '不够', '不够'), (15, '够', '不够'), (59, '够', '不够'), (60, '够', '够')):
            tech = technical(bars(count))
            self.assertEqual(tech['sample'], count)
            item = screen({'date': tech['asof'], 'technical': tech})['sample']
            self.assertEqual(clause(item['text'], 'rsi'), rsi_flag, count)
            self.assertEqual(clause(item['text'], 'macd'), macd_flag, count)
            self.assertIn(f'至少 {RSI14_MIN_BARS} 根', item['text'])
            self.assertIn(f'至少 {MACD_MIN_BARS} 根', item['text'])
            self.assertIn(f'当前样本 {count} 根', item['text'])
        self.assertEqual(screen({'technical': {'sample': 14}})['sample']['level'], 'warn')
        self.assertEqual(screen({'technical': {'sample': 59}})['sample']['level'], 'note')
        self.assertEqual(screen({'technical': {'sample': 60}})['sample']['level'], 'ok')
        self.assertEqual(screen({})['sample']['text'], '未取得')
        self.assertEqual(screen({'technical': {'sample': True}})['sample']['text'], '未取得')

    def test_baseline_statuses_and_first_caliber_reason(self):
        self.assertEqual(screen({}, {'status': 'first_analysis', 'reasons': ['没有更早报告，本次为首次分析']})['baseline']['text'], '无更早基线')
        self.assertEqual(screen({}, {'status': 'comparable', 'reasons': []})['baseline']['text'], '可比')
        limited = screen({}, {'status': 'limited', 'reasons': ['样本数 30→80，指标初始化窗口可能不同']})['baseline']
        self.assertEqual(limited['text'], '有限可比')
        self.assertNotIn('窗口', limited['text'])
        drifted = screen({}, {'status': 'incomparable', 'reasons': [
            '基线观察日晚于当前观察日，禁止用未来报告回看',
            '指标 method 口径不同，不可比',
            'prompt_version 不同，AI 文本不参与数值对比',
        ]})['baseline']
        self.assertEqual(drifted['text'], '口径不可比（指标 method 口径不同，不可比）')
        self.assertEqual(drifted['level'], 'warn')
        version = screen({}, {'status': 'incomparable', 'reasons': ['prompt_version 不同，AI 文本不参与数值对比']})['baseline']['text']
        self.assertEqual(version, '口径不可比（prompt_version 不同，AI 文本不参与数值对比）')
        plain = screen({}, {'status': 'incomparable', 'reasons': ['当前报告无 technical']})['baseline']['text']
        self.assertEqual(plain, '口径不可比')
        self.assertEqual(screen({}, None)['baseline']['text'], '未取得')
        self.assertEqual(screen({}, {'reasons': []})['baseline']['text'], '未取得')

    def test_backfill_uses_shanghai_date_of_this_report_only(self):
        def item(generated, day='2024-06-03'):
            return screen({'date': day, 'generated_at': generated, 'technical': {'asof': day, 'sample': 80}})['backfill']
        self.assertEqual(item('2024-06-03T16:00:00+08:00')['text'], '否：生成于观察日当天')
        self.assertEqual(item('2024-06-03T23:30:00+08:00')['level'], 'ok')
        later = item('2024-06-04T00:30:00+08:00')
        self.assertEqual(later['text'], '是：生成于观察日之后，不代表当时可知')
        self.assertEqual(later['level'], 'warn')
        self.assertNotIn('基线', later['text'])
        # 16:30Z 是上海时间次日 00:30。
        self.assertEqual(item('2024-06-03T16:30:00Z')['text'], '是：生成于观察日之后，不代表当时可知')
        early = item('2024-06-02T16:00:00+08:00')
        self.assertIn('日期异常', early['text'])
        self.assertNotIn('当天', early['text'])
        self.assertIn('2024-06-02', early['text'])
        self.assertIn('2024-06-03', early['text'])
        self.assertIn(early['level'], ('warn', 'note'))
        self.assertEqual(item('2024-06-04T00:30:00')['text'], '未取得')
        self.assertEqual(item(None)['text'], '未取得')
        self.assertEqual(screen({'generated_at': '2024-06-04T00:30:00+08:00'})['backfill']['text'], '未取得')
        self.assertEqual(item('not-a-date')['text'], '未取得')

    def test_ai_presence_names_the_model_without_calling_one(self):
        unknown = screen({'ai': None})['ai']
        self.assertIn('状态未知', unknown['text'])
        self.assertNotIn('未调用', unknown['text'])
        empty = screen({'ai': {}})['ai']
        self.assertIn('状态未知', empty['text'])
        self.assertNotIn('未调用', empty['text'])
        self.assertEqual(screen({'ai': None, 'model': None})['ai']['text'], '仅程序计算，未调用 AI')
        named = screen({'ai': {'overview': [{'text': '核对', 'evidence': ['T1']}]}, 'model': ' demo-model '})['ai']
        self.assertEqual(named['text'], '含 AI 解读（demo-model）')
        self.assertEqual(named['level'], 'note')
        self.assertEqual(screen({'ai': {'overview': [{}]}})['ai']['text'], '含 AI 解读（未取得）')
        self.assertEqual(screen(None)['ai']['text'], '未取得')


class EvidenceKindTests(unittest.TestCase):
    def test_prefixes_include_financial_and_unknown(self):
        expected = {
            'T1': ('T', '程序计算'), 'D2': ('D', '公告标题'), 'N3': ('N', '新闻标题'),
            'F1': ('F', '财务指标'), 'M1': ('M', '无依据说明'), 'F': ('F', '财务指标'),
        }
        for evidence_id, (code, label) in expected.items():
            self.assertEqual(evidence_kind(evidence_id), {'code': code, 'label': label})
        for evidence_id in ('', None, 'X9', 't1', '1', 'other', '新闻'):
            self.assertEqual(evidence_kind(evidence_id), {'code': 'other', 'label': '其他'})
        report = {'evidence': [{'id': 'T1'}, {'id': 'F1'}, {'id': 'ZZ'}, {'id': ''}, '坏', {'title': '无编号'}]}
        self.assertEqual(evidence_kinds(report), {
            'T1': {'code': 'T', 'label': '程序计算'},
            'F1': {'code': 'F', 'label': '财务指标'},
            'ZZ': {'code': 'other', 'label': '其他'},
        })
        self.assertEqual(evidence_kinds(None), {})
        self.assertEqual(evidence_kinds({'evidence': None}), {})


class GapImpactTests(unittest.TestCase):
    def grouped(self, assessment):
        found = {}
        for name, comp in assessment['components'].items():
            for item in comp.get('missing') or []:
                found.setdefault(item, set()).add(name)
        return found

    def assert_matches_score(self, tech, assessment=None, limitations=None):
        if assessment is None:
            assessment = evaluate(tech)
        report = {'technical': tech, 'assessment': assessment, 'limitations': limitations or [], 'date': tech.get('asof')}
        gaps = gap_impacts(report)
        for item, names in self.grouped(assessment).items():
            found = [gap for gap in gaps if covers(gap, item)]
            self.assertEqual(len(found), 1, (item, names, gaps))
            self.assertEqual(set(found[0]['affects']), names, item)
            self.assertNotIn('上涨概率', found[0]['text'])
        return gaps

    def test_missing_volume_matches_evaluate(self):
        rows = bars(80)
        for row in rows:
            row['volume'] = None
        tech = technical(rows)
        self.assertIsNone(tech['volume_ratio5'])
        assessment = evaluate(tech)
        self.assertIn('volume_ratio5', assessment['components']['volume_coord']['missing'])
        self.assertEqual(assessment['components']['volume_coord']['status'], 'missing')
        self.assertNotIn('volume_ratio5', assessment['components']['momentum']['missing'])
        gaps = self.assert_matches_score(tech, assessment)
        volume = next(gap for gap in gaps if covers(gap, 'volume_ratio5'))
        self.assertIn('量能配合不可算', volume['text'])
        self.assertIn('volume_coord', volume['affects'])
        self.assertNotIn('momentum', volume['affects'])
        zero_rows = bars(80)
        zero_rows[-1]['volume'] = 0
        zero = technical(zero_rows)
        self.assertEqual(zero['volume_ratio5'], 0)
        zero_score = evaluate(zero)
        self.assertIn('volume_ratio5==0', zero_score['components']['volume_coord']['missing'])
        zero_gaps = self.assert_matches_score(zero, zero_score)
        self.assertIn('量能配合不可算', next(gap for gap in zero_gaps if covers(gap, 'volume_ratio5==0'))['text'])

    def test_short_sample_macd_and_rsi_follow_score_components(self):
        for count in (14, 15, 40, 59):
            tech = technical(bars(count))
            gaps = self.assert_matches_score(tech, limitations=['连续有效样本不足 60 个，部分指标不计算；缺失日未填补。'])
            macd = next(gap for gap in gaps if covers(gap, 'macd'))
            self.assertIn('momentum', macd['affects'])
            self.assertEqual(macd['gap'], '不足 60')
            rsi = [gap for gap in gaps if covers(gap, 'rsi14')]
            if tech['rsi14'] is None:
                self.assertNotIn('momentum', rsi[0]['affects'])
                self.assertIn('overheat', rsi[0]['affects'])
            else:
                self.assertEqual(rsi, [])
        partial = self.assert_matches_score(technical(bars(40)), limitations=['连续有效样本不足 60 个，部分指标不计算；缺失日未填补。'])
        self.assertIn('动量部分规则不计', next(gap for gap in partial if covers(gap, 'macd'))['text'])
        long = technical(bars(60))
        self.assertIsNotNone(long['macd_hist'])
        self.assertFalse(any(covers(gap, 'macd') for gap in gap_impacts({'technical': long, 'assessment': evaluate(long), 'limitations': []})))

    def test_missing_technical_blocks_every_component(self):
        failed = gap_impacts({'technical': None, 'limitations': ['日 K 获取失败，未计算技术指标。'], 'evidence': []})
        self.assertEqual(failed[0]['gap'], '日 K 获取失败')
        self.assertEqual(failed[0]['affects'], ['trend', 'momentum', 'volume_coord', 'overheat'])
        self.assertIn('全部分项与技术指标不可用', failed[0]['text'])
        absent = gap_impacts({'limitations': ['旧报告没有行情字段'], 'evidence': [{'id': 'M1'}]})
        self.assertEqual(absent[0]['gap'], '技术指标未取得')
        self.assertEqual(absent[0]['affects'], ['trend', 'momentum', 'volume_coord', 'overheat'])
        self.assertEqual(gap_impacts(None), [])

    def test_news_financial_and_unknown_do_not_invent_components(self):
        tech = technical(bars(80))
        assessment = evaluate(tech)
        limitations = [
            '新闻获取失败，不据此认定没有相关事件。',
            '未选择财务报告期，本次不包含财务指标。',
            '所选报告期财务数据暂不可用。',
            '财务接口缺少披露时间，历史观察日不调用当前财务值，避免使用事后信息。',
            '本机披露资料读取未完成，未据此补充历史财务值。',
            '一段没有映射的说明',
        ]
        gaps = gap_impacts({'technical': tech, 'assessment': assessment, 'limitations': limitations})
        by_gap = {gap['gap']: gap for gap in gaps}
        self.assertIn('N 类', by_gap['新闻获取失败']['text'])
        self.assertIn('不据此认定无事件', by_gap['新闻获取失败']['text'])
        self.assertEqual(by_gap['新闻获取失败']['affects'], [])
        self.assertIn('无 F 类财务材料', by_gap['未选择财务报告期']['text'])
        self.assertEqual(by_gap['财务数据暂不可用']['affects'], [])
        self.assertIn('无 F 类财务材料', by_gap['财务接口缺少披露时间']['text'])
        self.assertNotIn('一段没有映射', json.dumps(gaps, ensure_ascii=False))
        unknown = gap_impacts({'technical': tech, 'assessment': {'components': {
            'trend': {'status': 'partial', 'score': 12, 'missing': ['not_a_rule']}}}, 'limitations': []})
        self.assertEqual(unknown, [{'gap': 'not_a_rule', 'affects': [], 'text': '影响范围未核实'}])

    def test_saved_assessment_is_not_recomputed(self):
        tech = technical(bars(30))
        self.assertIsNone(tech['macd_dif'])
        stored = {'components': {'momentum': {'status': 'ok', 'score': 40, 'missing': []}}}
        with patch('tech_score.evaluate', side_effect=AssertionError('should not rescore')):
            gaps = gap_impacts({'technical': tech, 'assessment': stored, 'limitations': []})
        self.assertFalse(any(covers(gap, 'macd') for gap in gaps))
        fresh = gap_impacts({'technical': tech, 'limitations': []})
        self.assertEqual(fresh, gap_impacts({'technical': tech, 'assessment': evaluate(tech), 'limitations': []}))


class AnalysisGetTests(unittest.TestCase):
    def engine(self, folder):
        market = Mock()
        market.prices.side_effect = AssertionError('market must not be called')
        news = Mock()
        news.stock.side_effect = AssertionError('news must not be called')
        themes = Mock()
        themes.financial.side_effect = AssertionError('financial must not be called')
        model = Mock()
        model.complete.side_effect = AssertionError('model must not be called')
        return Analysis(Path(folder) / 'reports.sqlite3', market, news, themes, model)

    def insert(self, analysis, identifier, payload, status='complete'):
        raw = None if payload is None else json.dumps(payload, ensure_ascii=False)
        with analysis.db() as db:
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                       (identifier, '600487.SH', '2026-03-21', '2026-03-21T10:00:00+08:00', status, '旧报告', raw, None))
        return raw

    def payload_of(self, analysis, identifier):
        with analysis.db() as db:
            return db.execute('SELECT payload FROM reports WHERE id=?', (identifier,)).fetchone()[0]

    def test_old_payload_is_readable_and_not_rewritten(self):
        self.assertEqual(PROMPT_VERSION, 'guanshi-research-1')
        payload = {
            'name': '旧', 'code': '600487.SH', 'date': '2026-03-21',
            'limitations': ['旧局限'],
            'evidence': [{'id': 'M1', 'title': '材料', 'value': ['旧局限'], 'source': '检查'},
                         {'id': 'F1', 'title': '财务', 'value': {}, 'source': '检查'},
                         {'id': 'X9', 'title': '其他', 'value': {}, 'source': '检查'}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            analysis = self.engine(tmp)
            raw = self.insert(analysis, 'old', payload)
            self.insert(analysis, 'empty', None)
            viewed = analysis.get('old')
            self.assertEqual(self.payload_of(analysis, 'old'), raw)
            self.assertEqual(viewed['report'], payload)
            self.assertNotIn('first_screen', viewed['report'])
            self.assertEqual(len(viewed['first_screen']), 5)
            self.assertEqual(viewed['first_screen'][0]['text'], '行情未取得')
            self.assertEqual(viewed['evidence_kinds']['M1']['label'], '无依据说明')
            self.assertEqual(viewed['evidence_kinds']['F1']['label'], '财务指标')
            self.assertEqual(viewed['evidence_kinds']['X9']['label'], '其他')
            self.assertEqual(viewed['gap_impacts'][0]['gap'], '技术指标未取得')
            analysis.market.prices.assert_not_called()
            analysis.model.complete.assert_not_called()
            empty = analysis.get('empty')
            self.assertIsNone(empty['report'])
            self.assertEqual(len(empty['first_screen']), 5)
            self.assertEqual(empty['gap_impacts'], [])
            self.assertIsNone(self.payload_of(analysis, 'empty'))
            with patch('first_screen.attach_disclosure', side_effect=RuntimeError('boom')):
                failed = analysis.get('old')
            self.assertNotIn('first_screen', failed)
            self.assertEqual(failed['report']['name'], '旧')
            self.assertEqual(self.payload_of(analysis, 'old'), raw)

    def test_copy_has_no_advice_language(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('first_screen.py', 'web/first-screen-view.js'):
            for line in (root / name).read_text().splitlines():
                for word in BANNED:
                    self.assertNotIn(word, line, name)
                if '概率' in line:
                    self.assertIn('不是概率', line, name)
        block = (root / 'web/style.css').read_text().split('.report-first-screen', 1)[1]
        for color in ('#c65148', '#257555', '#ff0000', '#00ff00'):
            self.assertNotIn(color, block)


class DemoDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.demo = Demo()
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.demo = self.demo
        Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.shutdown)
        self.addCleanup(self.http.server_close)

    def request(self, path, method='GET', body=None):
        connection = HTTPConnection('127.0.0.1', self.http.server_port, timeout=10)
        payload = json.dumps(body) if body is not None else None
        connection.request(method, path, payload, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        text = response.read()
        status = response.status
        connection.close()
        if path.startswith('/api/'):
            return status, json.loads(text)
        return status, text.decode()

    def test_demo_report_is_read_only_and_post_stays_forbidden(self):
        self.assertEqual(STATIC['/first-screen-view.js'], ('first-screen-view.js', 'text/javascript'))
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            report = self.demo.report('600000.SH', self.demo.day)
            self.assertEqual([item['key'] for item in report['first_screen']], ['dates', 'sample', 'baseline', 'backfill', 'ai'])
            self.assertEqual(report['evidence_kinds']['T1']['label'], '程序计算')
            self.assertIsInstance(report['gap_impacts'], list)
            self.assertNotIn('first_screen', report['report'])
            self.assertEqual(report['first_screen'][4]['text'], '仅程序计算，未调用 AI')
            first = self.demo.report('600000.SH', self.demo.market.dates[0])
            self.assertEqual(next(item['text'] for item in first['first_screen'] if item['key'] == 'baseline'), '无更早基线')
            status, page = self.request('/')
            self.assertEqual(status, 200)
            self.assertLess(page.index('/first-screen-view.js'), page.index('/analysis.js'))
            status, script = self.request('/first-screen-view.js')
            self.assertEqual(status, 200)
            fetched = self.request('/api/analysis?id=' + report['id'])[1]
            self.assertEqual(fetched['first_screen'], report['first_screen'])
            self.assertEqual(fetched['gap_impacts'], report['gap_impacts'])
            status, denied = self.request('/api/analysis', 'POST', {})
            self.assertEqual(status, 403)
            self.assertEqual(denied['reason'], 'demo_read_only')
