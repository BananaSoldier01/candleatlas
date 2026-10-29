import datetime as dt
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from analysis import PROMPT_VERSION, Analysis, validate_report
from number_gate import MARK, NOTE, gate_ai_report, source_numbers


KEYS=('overview','supporting','opposing','watch')


def prices(count=80):
    start=dt.date(2026,1,1)
    return [{'date':(start+dt.timedelta(days=i)).isoformat(),'close_price':10+i,'volume':100} for i in range(count)]


def news_item(title='增持 1000 万股'):
    return {'id':'N1','title':title,'value':{'time':'2026-03-20 10:00:00','title':title,'url':'https://example.com/n','source':'示例'},'source':'合成新闻标题'}


def report(rows):
    return {key:rows[key] if key in rows else [{'text':'无数字陈述。','evidence':['N1']}] for key in KEYS}


class NumberGateTests(unittest.TestCase):
    def test_source_numbers_expand_suffixes_and_ignore_non_claims(self):
        got=source_numbers(['增持 1,000 万股，约 1.5 亿，增幅 12.5%。'])
        self.assertIn(Decimal('10000000'),got)
        self.assertIn(Decimal('150000000'),got)
        self.assertIn(Decimal('0.125'),got)
        self.assertEqual(source_numbers(['1,000万'])&source_numbers(['1000 万','10,000,000']),{Decimal('10000000')})
        blank='观察日 2024-03-20 10:00:00，年份 2024 年，材料 T1 N2 D3 M1 F1，近 5 日，近5个交易日，参数 (12,26,9)。'
        self.assertEqual(source_numbers([blank]),set())
        self.assertIn(Decimal('20240000'),source_numbers(['金额 2024万元']))
        self.assertEqual(source_numbers(None),set())

    def test_news_figure_is_kept_and_unsourced_figure_is_marked_without_dropping_the_item(self):
        evidence=[news_item()]
        kept=gate_ai_report(report({'overview':[{'text':'标题写明增持 1000 万股。','evidence':['N1']}]}),evidence)
        self.assertEqual(kept['overview'][0]['text'],'标题写明增持 1000 万股。')
        self.assertNotIn(MARK,kept['overview'][0]['text'])
        original='另有复述称增持 2000 万股，句子仍保留。'
        ai=report({'supporting':[{'text':original,'evidence':['N1']}]})
        snapshot=json.loads(json.dumps(ai))
        out=gate_ai_report(ai,evidence)
        text=out['supporting'][0]['text']
        self.assertIn('另有复述称增持',text)
        self.assertIn('句子仍保留。',text)
        self.assertNotIn('2000',text)
        self.assertNotIn('万股',text)
        self.assertNotIn('（略※）元',text)
        self.assertIn(NOTE,text)
        self.assertEqual(text.count('未整段丢弃本条'),1)
        self.assertEqual(out['supporting'][0]['evidence'],['N1'])
        self.assertEqual(ai,snapshot)
        self.assertEqual(gate_ai_report(out,evidence),out)

    def test_units_travel_with_the_number_and_the_note_is_appended_once(self):
        evidence=[news_item('无金额标题')]
        text='一处 11 万，另一处 22%，还有 300 亿元。'
        out=gate_ai_report(report({'opposing':[{'text':text,'evidence':['N1']}]}),evidence)
        body,note=out['opposing'][0]['text'].split('（文中',1)
        self.assertEqual(body.count(MARK),3)
        self.assertNotIn('亿元',body)
        self.assertNotIn('（略※）亿',body)
        self.assertNotIn('（略※）元',body)
        self.assertNotIn('%',body)
        self.assertIn('一处',body)
        self.assertIn('另一处',body)
        self.assertIn('还有',body)
        self.assertEqual(note.count('未整段丢弃本条'),1)
        for key in KEYS:
            ai=report({key:[{'text':'2000 万','evidence':['N1']}]})
            self.assertIn(MARK,gate_ai_report(ai,evidence)[key][0]['text'])

    def test_technical_financial_dates_ids_and_windows_are_not_rewritten(self):
        technical=[{'id':'T1','title':'行情与技术指标','value':{'rsi14':12.3,'method':'MACD(12,26,9)'},'source':'程序'}]
        prose='RSI 70，MACD(12,26,9)，近 5 日，日期 2024-03-20，见 T1。'
        ai=report({'overview':[{'text':prose,'evidence':['T1']}]})
        self.assertEqual(gate_ai_report(ai,technical)['overview'][0]['text'],prose)
        financial=[{'id':'F1','title':'财务指标','value':{'items':[{'label':'净资产收益率','value':1}]},'source':'财务'}]
        rich='财务栏写了 999 亿，本条只引用财务材料。'
        fai=report({'watch':[{'text':rich,'evidence':['F1']}]})
        self.assertEqual(gate_ai_report(fai,financial)['watch'][0]['text'],rich)
        both=report({'overview':[{'text':'标题为增持 1000 万，同时写了 RSI 70。','evidence':['N1','T1']}]})
        mixed=gate_ai_report(both,[news_item(),technical[0]])['overview'][0]['text']
        self.assertIn('1000 万',mixed)
        self.assertNotIn('70',mixed)
        self.assertIn(MARK,mixed)
        plain='观察日 2024-03-20，近 5 日，材料 N1，参数 (12,26,9)，2024年回顾。'
        dated=gate_ai_report(report({'overview':[{'text':plain,'evidence':['N1']}]}),[news_item('公司签署日常经营合同')])
        self.assertEqual(dated['overview'][0]['text'],plain)
        limits=[{'id':'M1','title':'材料范围与缺失项','value':['新闻得到 10 条；缺失日未填补。'],'source':'观市数据检查'}]
        limited=gate_ai_report(report({'overview':[{'text':'材料写明 10 条，不能写成 99。','evidence':['M1']}]}),limits)['overview'][0]['text']
        self.assertIn('10 条',limited)
        self.assertNotIn('99',limited)
        self.assertIn(NOTE,limited)
        unknown=gate_ai_report(report({'overview':[{'text':'无法识别的材料写成 999。','evidence':['X1']}]}),[])['overview'][0]['text']
        self.assertIn('无法识别的材料写成',unknown)
        self.assertIn(MARK,unknown)
        self.assertNotIn('999',unknown)
        disclosure=[{'id':'D1','title':'营收 12.5 亿元','value':{'title':'营收 12.5 亿元','notice_date':'2024-04-20'},'source':'披露'}]
        disclosed=gate_ai_report(report({'overview':[{'text':'披露写营收 12.5 亿元，没有 8.8 亿。','evidence':['D1']}]}),disclosure)['overview'][0]['text']
        self.assertIn('12.5 亿元',disclosed)
        self.assertNotIn('8.8',disclosed)
        shared=gate_ai_report(report({'overview':[{'text':'增持 1000 万见 N1 或 D1。','evidence':['N1','D1']}]}),[news_item(),{'id':'D1','title':'无数字','value':'无数字','source':'披露'}])
        self.assertNotIn(MARK,shared['overview'][0]['text'])
        bare=gate_ai_report(report({'overview':[{'text':'只写了 1000，没有单位。','evidence':['N1']}]}),[news_item()])['overview'][0]['text']
        self.assertNotIn('1000',bare.split('（文中',1)[0])
        self.assertIn(MARK,bare)

    def test_prompt_version_and_system_text_stay_put(self):
        self.assertEqual(PROMPT_VERSION,'guanshi-research-1')
        source=Path('analysis.py').read_text()
        self.assertIn("PROMPT_VERSION='guanshi-research-1'",source)
        self.assertIn('你是股票研究助手，只使用给定材料，以简体中文输出 JSON，不使用 Markdown。',source)
        self.assertNotIn('略※',source)

    def engine(self,folder,reply):
        market=Mock();market.prices.return_value={'items':prices()}
        news=Mock();news.stock.return_value={'items':[{'time':'2026-03-20 10:00:00','title':'公司公告增持 1000 万股','url':'https://example.com/n','source':'示例'}]}
        model=Mock();model.complete.return_value=reply
        return Analysis(Path(folder)/'reports.sqlite3',market,news,Mock(),model)

    def run_ai(self,analysis,identifier):
        with analysis.db() as db:
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                       (identifier,'600487.SH','2026-03-21','2026-03-21T16:00:00+08:00','running','test',None,None))
        analysis.run(identifier,'600487.SH','测试','2026-03-21','',True,{'model':'test-model'})
        return analysis.get(identifier)

    def test_analysis_gates_after_validation_and_survives_a_gate_error(self):
        reply=json.dumps({
            'overview':[{'text':'标题写明增持 1000 万股。','evidence':['N1']}],
            'supporting':[{'text':'另有复述称增持 2000 万股。','evidence':['N1']}],
            'opposing':[{'text':'程序指标 RSI 70，仅作对照。','evidence':['T1']}],
            'watch':[{'text':'近 5 日与日期 2024-03-20、材料 N1 仍待核对。','evidence':['N1']}],
        },ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            done=self.run_ai(self.engine(tmp,reply),'gated')
            self.assertEqual(done['status'],'complete')
            self.assertIsNone(done['error'])
            ai=done['report']['ai']
            self.assertEqual(done['report']['prompt_version'],PROMPT_VERSION)
            self.assertIn('1000 万',ai['overview'][0]['text'])
            self.assertNotIn(MARK,ai['overview'][0]['text'])
            self.assertEqual(ai['overview'][0]['evidence'],['N1'])
            self.assertNotIn('2000',ai['supporting'][0]['text'])
            self.assertIn(MARK,ai['supporting'][0]['text'])
            self.assertIn('另有复述称增持',ai['supporting'][0]['text'])
            self.assertEqual(ai['supporting'][0]['text'].count('未整段丢弃本条'),1)
            self.assertEqual(ai['opposing'][0]['text'],'程序指标 RSI 70，仅作对照。')
            self.assertEqual(ai['watch'][0]['text'],'近 5 日与日期 2024-03-20、材料 N1 仍待核对。')
            technical='连续样本下 RSI 70，参数 (12,26,9)，近 5 日无额外口径。'
            pure=json.dumps({key:[{'text':technical,'evidence':['T1']}] for key in KEYS},ensure_ascii=False)
            checked=validate_report(pure,{'T1'})
            self.assertEqual(gate_ai_report(checked,[{'id':'T1','title':'指标','value':{'rsi14':12.3},'source':'程序'}]),checked)
            saved=self.run_ai(self.engine(tmp,pure),'technical-only')
            self.assertEqual(saved['status'],'complete')
            for key in KEYS:
                self.assertEqual(saved['report']['ai'][key][0]['text'],technical)
            broken=self.engine(tmp,'不是 JSON')
            failed=self.run_ai(broken,'invalid')
            self.assertEqual(failed['status'],'partial')
            self.assertIsNone(failed['report']['ai'])
            with patch('analysis.gate_ai_report',side_effect=RuntimeError('boom')):
                fallback=self.run_ai(self.engine(tmp,reply),'fallback')
            self.assertEqual(fallback['status'],'complete')
            self.assertIsNone(fallback['error'])
            self.assertIn('2000 万',fallback['report']['ai']['supporting'][0]['text'])
            self.assertNotIn(MARK,json.dumps(fallback['report']['ai'],ensure_ascii=False))
