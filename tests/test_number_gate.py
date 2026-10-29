import datetime as dt
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from analysis import PROMPT_VERSION, Analysis, _number_gate_status, technical, validate_report
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
        self.assertIn((Decimal('10000000'),'shares'),got)
        self.assertIn((Decimal('150000000'),'unitless'),got)
        self.assertIn((Decimal('0.125'),'percent'),got)
        self.assertEqual(source_numbers(['1,000万'])&source_numbers(['1000 万','10,000,000']),{(Decimal('10000000'),'unitless')})
        blank='观察日 2024-03-20 10:00:00，年份 2024 年，材料 T1 N2 D3 M1 F1，近 5 日，近5个交易日，MACD(12,26,9)。'
        self.assertEqual(source_numbers([blank]),set())
        self.assertEqual(source_numbers(['参数 (12,26,9)','(1,2,3)']),{(Decimal(n),'unitless') for n in ('12','26','9','1','2','3')})
        self.assertEqual(source_numbers(['2001年','2024 年','macd(12,26,9)','EMA（12，26）','Boll(20,2)','kdj(9,3,3)']),set())
        self.assertIn((Decimal('20240000'),'money'),source_numbers(['金额 2024万元']))
        self.assertEqual(source_numbers(None),set())
        self.assertEqual(source_numbers(['1万股']),source_numbers(['10000股']))
        self.assertEqual(source_numbers(['1亿元']),{(Decimal('100000000'),'money')})
        self.assertEqual(source_numbers(['1万亿元']),{(Decimal('1000000000000'),'money')})
        self.assertEqual(source_numbers(['12元股']),{(Decimal('12'),'shares')})
        self.assertFalse(source_numbers(['123股'])&source_numbers(['123元']))
        self.assertFalse(source_numbers(['12.5%'])&source_numbers(['12.5元','12.5']))
        self.assertFalse(source_numbers(['3倍'])&source_numbers(['3点','3']))
        self.assertFalse(source_numbers(['1万元'])&source_numbers(['1万']))
        self.assertEqual(source_numbers(['+12.5%']),source_numbers(['12.5%']))
        self.assertFalse(source_numbers(['-12.5%'])&source_numbers(['12.5%']))
        self.assertEqual(source_numbers(['-12.5%']),source_numbers(['-12.5％']))
        self.assertEqual(source_numbers(['+3倍']),source_numbers(['3倍']))
        self.assertEqual(source_numbers(['2万']),{(Decimal('20000'),'unitless')})
        self.assertIn((Decimal('2001'),'shares'),source_numbers(['增持 2001 股']))
        self.assertIn((Decimal('2001'),'multiple'),source_numbers(['2001倍']))
        self.assertIn((Decimal('2001'),'points'),source_numbers(['2001点']))

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
        both=report({'overview':[{'text':'标题为增持 1000 万股，同时写了 RSI 70，另称订单 5000 万元。','evidence':['N1','T1']}]})
        mixed_evidence=[news_item(),{'id':'T1','title':'行情与技术指标','value':{'rsi14':70,'method':'MACD(12,26,9)'},'source':'程序'}]
        mixed=gate_ai_report(both,mixed_evidence)['overview'][0]['text']
        self.assertIn('1000 万股',mixed)
        self.assertIn('RSI 70',mixed)
        self.assertNotIn('5000',mixed)
        self.assertIn(MARK,mixed)
        plain='观察日 2024-03-20，近 5 日，材料 N1，参数 (12,26,9)，2024年回顾。'
        dated=gate_ai_report(report({'overview':[{'text':plain,'evidence':['N1']}]}),[news_item('公司签署日常经营合同')])['overview'][0]['text']
        self.assertEqual(dated,'观察日 2024-03-20，近 5 日，材料 N1，参数 (（略※）,（略※）,（略※）)，2024年回顾。'+NOTE)
        anchored='回顾 MACD(12,26,9)，以及 2001年，没有别的数字。'
        self.assertEqual(gate_ai_report(report({'overview':[{'text':anchored,'evidence':['N1']}]}),[news_item('公司签署日常经营合同')])['overview'][0]['text'],anchored)
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
        shared=gate_ai_report(report({'overview':[{'text':'增持 1000 万股见 N1 或 D1。','evidence':['N1','D1']}]}),[news_item(),{'id':'D1','title':'无数字','value':'无数字','source':'披露'}])
        self.assertNotIn(MARK,shared['overview'][0]['text'])
        bare=gate_ai_report(report({'overview':[{'text':'只写了 1000，没有单位。','evidence':['N1']}]}),[news_item()])['overview'][0]['text']
        self.assertNotIn('1000',bare.split('（文中',1)[0])
        self.assertIn(MARK,bare)

    def test_same_dimension_scales_match_and_cross_dimension_is_masked(self):
        evidence=[news_item('增持 1 万股，金额 2 万元，跌幅 -12.5%，估值 3 倍')]
        kept=gate_ai_report(report({'overview':[{'text':'增持 10000 股，金额 20000 元，跌幅 -12.5％，估值 3 倍。','evidence':['N1']}]}),evidence)
        self.assertNotIn(MARK,kept['overview'][0]['text'])
        crossed=gate_ai_report(report({'supporting':[{'text':'增持 10000 元，跌幅 12.5%，估值 3 点，裸数 3。','evidence':['N1']}]}),evidence)['supporting'][0]['text']
        body,note=crossed.split('（文中',1)
        self.assertNotIn('10000',body)
        self.assertNotIn('12.5%',body)
        self.assertNotIn('3 点',body)
        self.assertNotIn('裸数 3',body)
        self.assertEqual(body.count(MARK),4)
        self.assertEqual(note.count('未整段丢弃本条'),1)

    def test_year_needs_context_and_parameter_groups_need_an_indicator(self):
        quiet=[news_item('公司签署日常经营合同')]
        bare='2001年回顾，增持 2001 股，放大 2001 倍，上行 2001 点，MACD(12,26,9) 仍保留。'
        masked=gate_ai_report(report({'overview':[{'text':bare,'evidence':['N1']}]}),quiet)['overview'][0]['text']
        self.assertEqual(masked,'2001年回顾，增持 （略※），放大 （略※），上行 （略※），MACD(12,26,9) 仍保留。'+NOTE)
        sourced=[news_item('增持 2001 股')]
        kept=gate_ai_report(report({'watch':[{'text':bare,'evidence':['N1']}]}),sourced)['watch'][0]['text']
        self.assertEqual(kept,'2001年回顾，增持 2001 股，放大 （略※），上行 （略※），MACD(12,26,9) 仍保留。'+NOTE)
        self.assertIn('2001年',kept)
        self.assertIn('2001 股',kept)
        self.assertNotIn('2001 倍',kept)
        self.assertNotIn('2001 点',kept)

    def test_mixed_technical_or_financial_numbers_stay_when_news_is_also_cited(self):
        technical={'id':'T1','title':'行情与技术指标','value':{'rsi14':100,'method':'MACD(12,26,9)'},'source':'程序'}
        news=news_item('公司公告增持 1000 万股')
        news['value']['url']='https://example.com/n/987654321'
        prose='RSI 100，标题增持 1000 万股，新闻另写订单 5000 万元。'
        out=gate_ai_report(report({'overview':[{'text':prose,'evidence':['N1','T1']}]}),[news,technical])['overview'][0]['text']
        self.assertIn('RSI 100',out)
        self.assertIn('1000 万股',out)
        self.assertNotIn('5000',out)
        self.assertIn(MARK,out)
        self.assertEqual(out.count('未整段丢弃本条'),1)
        financial={'id':'F1','title':'财务指标','value':{'items':[{'label':'净资产收益率','value':'8.5%'}]},'source':'财务'}
        disclosure={'id':'D1','title':'年度报告','value':{'title':'年度报告','content':'营业收入 12.5 亿元','url':'https://example.com/987654321.pdf','stock_code':'600487','notice_date':'2024-04-20','sha256':'abc987654321'},'source':'披露'}
        line='披露营业收入 12.5 亿元，财务净资产收益率 8.5%，另有无出处的 77 亿元。'
        mixed=gate_ai_report(report({'watch':[{'text':line,'evidence':['D1','F1']}]}),[disclosure,financial])['watch'][0]['text']
        self.assertIn('12.5 亿元',mixed)
        self.assertIn('8.5%',mixed)
        self.assertNotIn('77',mixed)
        self.assertNotIn('987654321',mixed)
        self.assertIn(MARK,mixed)
        only_t='RSI 100，但不能因此放过新闻里的 5000 万元。'
        self.assertEqual(gate_ai_report(report({'opposing':[{'text':only_t,'evidence':['T1']}]}),[technical])['opposing'][0]['text'],only_t)

    def test_news_and_disclosure_metadata_is_not_a_number_source(self):
        news={'id':'N1','title':'增持 1000 万股','value':{'time':'2026-03-20 10:00:00','title':'增持 1000 万股','url':'https://example.com/n/987654321','source':'示例987654321'},'source':'东方财富按代码检索'}
        doc={'id':'ann-1','stock_code':'600487','stock_name':'示例','period_end':'2024-12-31','title':'营收 12.5 亿元','document_kind':'annual_report','url':'https://static.cninfo.com.cn/finalpage/2024-04-20/987654321.PDF','notice_date':'2024-04-20','available_at':'2024-04-20T16:00:00+08:00','fetched_at':'2024-04-21T08:00:00+08:00','index_fetched_at':'2024-04-21T08:00:00+08:00','sha256':'0123456789abcdef9876543210','published_precision':'day','notice_date_basis':'index','pdf_path':'documents/987654321.pdf','content':'正文：净利润 3.2 亿元。'}
        disclosure={'id':'D1','title':'营收 12.5 亿元','value':doc,'source':'巨潮官方公告索引及已核验原文 / 本机资料库'}
        prose='标题增持 1000 万股。营收 12.5 亿元，净利润 3.2 亿元。不能写成营业收入 987654321 元，也不能单写 987654321 或代码 600487。'
        out=gate_ai_report(report({'overview':[{'text':prose,'evidence':['N1','D1']}]}),[news,disclosure])['overview'][0]['text']
        self.assertIn('1000 万股',out)
        self.assertIn('12.5 亿元',out)
        self.assertIn('3.2 亿元',out)
        self.assertNotIn('987654321',out)
        self.assertNotIn('600487',out)
        self.assertIn(MARK,out)
        nested={'id':'N2','title':'无数字标题','value':{'url':'https://example.com/987654321','summary':{'title':'订单 42 万股','url':'https://cdn.example/555666777','sha256':'555666777'}},'source':'合成'}
        body=gate_ai_report(report({'supporting':[{'text':'订单 42 万股，附件 555666777。','evidence':['N2']}]}),[nested])['supporting'][0]['text']
        self.assertIn('42 万股',body)
        self.assertNotIn('555666777',body)
        literal={'id':'D2','title':'简讯','value':'公告称派息 0.5 元','source':'披露'}
        text=gate_ai_report(report({'opposing':[{'text':'公告称派息 0.5 元，不是 9 元。','evidence':['D2']}]}),[literal])['opposing'][0]['text']
        self.assertIn('0.5 元',text)
        self.assertNotIn('9 元',text)

    def test_technical_field_units_are_mapped_when_mixed_with_news(self):
        tech={'id':'T1','title':'行情与技术指标','value':technical(prices()),'source':'程序'}
        news=news_item()
        evidence=[news,tech]
        self.assertEqual(tech['value']['close'],89)
        close=gate_ai_report(report({'overview':[{'text':'收盘价为 89 元，不是 89 股，标题增持 1000 万股，另有订单 5000 万元。','evidence':['N1','T1']}]}),evidence)['overview'][0]['text']
        self.assertIn('89 元',close)
        self.assertIn('1000 万股',close)
        self.assertNotIn('89 股',close)
        self.assertNotIn('5000',close)
        self.assertIn(MARK,close)
        change=gate_ai_report(report({'supporting':[{'text':'近一日涨跌 1.14%，不是 1.14 元，标题增持 1000 万股。','evidence':['N1','T1']}]}),evidence)['supporting'][0]['text']
        self.assertIn('1.14%',change)
        self.assertIn('1000 万股',change)
        self.assertNotIn('1.14 元',change)
        self.assertIn(MARK,change)
        volume=gate_ai_report(report({'opposing':[{'text':'量比 1.0 倍，不是 1.0 元，标题增持 1000 万股。','evidence':['N1','T1']}]}),evidence)['opposing'][0]['text']
        self.assertIn('1.0 倍',volume)
        self.assertIn('1000 万股',volume)
        self.assertNotIn('1.0 元',volume)
        self.assertIn(MARK,volume)
        rsi=gate_ai_report(report({'watch':[{'text':'RSI 100，标题增持 1000 万股，另称订单 5000 万元。','evidence':['N1','T1']}]}),evidence)['watch'][0]['text']
        self.assertIn('RSI 100',rsi)
        self.assertIn('1000 万股',rsi)
        self.assertNotIn('5000',rsi)
        self.assertIn(MARK,rsi)
        only_t=gate_ai_report(report({'overview':[{'text':'收盘价为 89 元。','evidence':['T1']}]}),evidence)['overview'][0]['text']
        self.assertEqual(only_t,'收盘价为 89 元。')

    def test_financial_units_follow_recorded_structure_only(self):
        news=news_item()
        percent={'id':'F1','title':'财务指标','value':{'items':[{'label':'净资产收益率','value':'8.5%'}]},'source':'财务'}
        kept=gate_ai_report(report({'overview':[{'text':'净资产收益率 8.5%，标题增持 1000 万股，另有 77 亿元。','evidence':['N1','F1']}]}),[news,percent])['overview'][0]
        self.assertIn('8.5%',kept['text'])
        self.assertIn('1000 万股',kept['text'])
        self.assertNotIn('77',kept['text'])
        self.assertIn(MARK,kept['text'])
        self.assertNotIn('unit_unverified',kept)
        explicit={'id':'F1','title':'财务指标','value':{'items':[{'label':'销售净利率','value':8.5,'unit':'%'}]},'source':'财务'}
        unit=gate_ai_report(report({'supporting':[{'text':'销售净利率 8.5%，标题增持 1000 万股。','evidence':['N1','F1']}]}),[news,explicit])['supporting'][0]
        self.assertIn('8.5%',unit['text'])
        self.assertNotIn(MARK,unit['text'])
        self.assertNotIn('unit_unverified',unit)
        scaled={'id':'F1','title':'财务指标','value':{'items':[{'label':'营收','value':1.5,'unit':'亿元'}]},'source':'财务'}
        money=gate_ai_report(report({'opposing':[{'text':'营收 1.5 亿元，不是 1.5 万股，标题增持 1000 万股。','evidence':['N1','F1']}]}),[news,scaled])['opposing'][0]['text']
        self.assertIn('1.5 亿元',money)
        self.assertNotIn('1.5 万股',money)
        self.assertIn(MARK,money)
        bare={'id':'F1','title':'财务指标','value':{'items':[{'label':'归母净利润同比','value':93.381059}],'report':'2026-2','note':'同花顺财务指标'},'source':'财务'}
        watched=gate_ai_report(report({'watch':[{'text':'同比 93.381059%，不能据此写成 93.38 元或 8.5%，标题增持 1000 万股，另有 9999 万股。','evidence':['N1','F1']}]}),[news,bare])['watch'][0]
        self.assertIn('93.381059%',watched['text'])
        self.assertIn('1000 万股',watched['text'])
        self.assertNotIn('93.38 元',watched['text'])
        self.assertNotIn('8.5%',watched['text'])
        self.assertNotIn('9999',watched['text'])
        self.assertIn(MARK,watched['text'])
        self.assertTrue(watched['unit_unverified'])
        only_f=gate_ai_report(report({'overview':[{'text':'财务栏写了 999 亿。','evidence':['F1']}]}),[bare])['overview'][0]
        self.assertEqual(only_f['text'],'财务栏写了 999 亿。')
        self.assertNotIn('unit_unverified',only_f)

    def test_unitless_financial_keeps_same_magnitude_and_still_masks_news(self):
        news=news_item('公司公告增持计划')
        self.assertNotIn('9999',news['title'])
        financial={'id':'F1','title':'财务指标','value':{'items':[{'label':'销售净利率','value':8.5}],'report':'2026-2','note':'同花顺财务指标；按所选报告期展示当前查询值。'},'source':'财务'}
        self.assertNotIn('unit',financial['value']['items'][0])
        prose='销售净利率为8.5%，另有增持公告写了 9999 万股。'
        ai=report({'overview':[{'text':prose,'evidence':['F1','N1']}]})
        snapshot=json.loads(json.dumps(ai))
        out=gate_ai_report(ai,[financial,news])
        row=out['overview'][0]
        self.assertIn('8.5%',row['text'])
        self.assertNotIn('9999',row['text'])
        self.assertNotIn('万股',row['text'])
        self.assertIn(MARK,row['text'])
        self.assertIn(NOTE,row['text'])
        self.assertEqual(row['text'].count('未整段丢弃本条'),1)
        self.assertTrue(row['unit_unverified'])
        self.assertEqual(row['evidence'],['F1','N1'])
        self.assertEqual(ai,snapshot)
        self.assertEqual(gate_ai_report(out,[financial,news]),out)
        self.assertEqual(_number_gate_status(out),{'status':'masked','unit_unverified':True})
        kept=gate_ai_report(report({'supporting':[{'text':'销售净利率为8.5%。','evidence':['F1','N1']}]}),[financial,news])
        self.assertEqual(kept['supporting'][0]['text'],'销售净利率为8.5%。')
        self.assertNotIn(MARK,kept['supporting'][0]['text'])
        self.assertTrue(kept['supporting'][0]['unit_unverified'])
        self.assertEqual(_number_gate_status(kept),{'status':'unit_unverified','unit_unverified':True})
        other=gate_ai_report(report({'watch':[{'text':'销售净利率 8.50 元单位未核，不能写成 93.38 元或 0.085%，也不是 8.5 万元。','evidence':['N1','F1']}]}),[news,financial])['watch'][0]
        self.assertIn('8.50 元',other['text'])
        self.assertTrue(other['unit_unverified'])
        self.assertNotIn('93.38',other['text'])
        self.assertNotIn('0.085',other['text'])
        self.assertNotIn('8.5 万',other['text'])
        self.assertIn(MARK,other['text'])

    def test_prompt_version_and_system_text_stay_put(self):
        self.assertEqual(PROMPT_VERSION,'guanshi-research-1')
        source=Path('analysis.py').read_text()
        self.assertIn("PROMPT_VERSION='guanshi-research-1'",source)
        self.assertIn('你是股票研究助手，只使用给定材料，以简体中文输出 JSON，不使用 Markdown。',source)
        self.assertNotIn('略※',source)

    def engine(self,folder,reply,financial=None):
        market=Mock();market.prices.return_value={'items':prices()}
        news=Mock();news.stock.return_value={'items':[{'time':'2026-03-20 10:00:00','title':'公司公告增持 1000 万股','url':'https://example.com/n','source':'示例'}]}
        model=Mock();model.complete.return_value=reply
        themes=Mock()
        if financial is not None:themes.financial.return_value=financial
        return Analysis(Path(folder)/'reports.sqlite3',market,news,themes,model)

    def run_ai(self,analysis,identifier,report=''):
        with analysis.db() as db:
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                       (identifier,'600487.SH','2026-03-21','2026-03-21T16:00:00+08:00','running','test',None,None))
        analysis.run(identifier,'600487.SH','测试','2026-03-21',report,True,{'model':'test-model'})
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
            self.assertEqual(done['report']['number_gate'],{'status':'masked'})
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
            self.assertEqual(saved['report']['number_gate'],{'status':'clean'})
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
            self.assertEqual(fallback['report']['number_gate'],{'status':'failed'})
            self.assertIn('2000 万',fallback['report']['ai']['supporting'][0]['text'])
            self.assertNotIn(MARK,json.dumps(fallback['report']['ai'],ensure_ascii=False))
            saved_blob=json.dumps(fallback,ensure_ascii=False)
            self.assertNotIn('boom',saved_blob)
            self.assertNotIn('RuntimeError',saved_blob)
            self.assertNotIn('Traceback',saved_blob)
            page=Path('web/analysis.js').read_text()
            self.assertIn('数字核验未完成',page)
            self.assertIn('旧报告未做数字核验',page)
            self.assertIn("gateStatus==='failed'",page)
            self.assertIn("gateStatus==='skipped'",page)
            self.assertIn("gateStatus==='masked'",page)
            self.assertIn("let gateNote=''",page)
            self.assertLess(page.index("gateStatus==='failed'"),page.index("gateStatus==='masked'"))
            self.assertLess(page.index("gateStatus==='masked'"),page.index('旧报告未做数字核验'))
            legacy=self.engine(tmp,reply)
            old_payload={'name':'测试','code':'600487.SH','date':'2026-03-21','ai':{key:[{'text':'旧文本没有闸门状态。','evidence':['T1']}] for key in KEYS}}
            with legacy.db() as db:
                db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                           ('legacy','600487.SH','2026-03-21','2026-03-21T16:00:00+08:00','complete','分析完成',json.dumps(old_payload,ensure_ascii=False),None))
            loaded=legacy.get('legacy')
            self.assertNotIn('number_gate',loaded['report'])
            self.assertEqual(loaded['report']['ai']['overview'][0]['text'],'旧文本没有闸门状态。')

    def test_analysis_run_maps_technical_and_financial_units(self):
        tech_reply=json.dumps({
            'overview':[{'text':'收盘价为 89 元，不是 89 股，标题增持 1000 万股，另有订单 5000 万元。','evidence':['N1','T1']}],
            'supporting':[{'text':'近一日涨跌 1.14%，不是 1.14 元，标题增持 1000 万股。','evidence':['N1','T1']}],
            'opposing':[{'text':'量比 1.0 倍，标题增持 1000 万股。','evidence':['N1','T1']}],
            'watch':[{'text':'RSI 100，标题增持 1000 万股。','evidence':['N1','T1']}],
        },ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            analysis=self.engine(tmp,tech_reply)
            done=self.run_ai(analysis,'tech-units')
            self.assertEqual(done['status'],'complete')
            self.assertIsNone(done['error'])
            self.assertEqual(analysis.model.complete.call_count,1)
            self.assertEqual(done['report']['technical']['close'],89)
            self.assertEqual(done['report']['technical']['change1'],1.14)
            self.assertEqual(done['report']['technical']['volume_ratio5'],1.0)
            self.assertEqual(done['report']['technical']['rsi14'],100)
            ai=done['report']['ai']
            self.assertEqual(done['report']['number_gate'],{'status':'masked'})
            self.assertIn('89 元',ai['overview'][0]['text'])
            self.assertIn('1000 万股',ai['overview'][0]['text'])
            self.assertNotIn('89 股',ai['overview'][0]['text'])
            self.assertNotIn('5000',ai['overview'][0]['text'])
            self.assertIn(MARK,ai['overview'][0]['text'])
            self.assertIn('1.14%',ai['supporting'][0]['text'])
            self.assertNotIn('1.14 元',ai['supporting'][0]['text'])
            self.assertIn(MARK,ai['supporting'][0]['text'])
            self.assertIn('1.0 倍',ai['opposing'][0]['text'])
            self.assertIn('1000 万股',ai['opposing'][0]['text'])
            self.assertNotIn(MARK,ai['opposing'][0]['text'])
            self.assertIn('RSI 100',ai['watch'][0]['text'])
            self.assertIn('1000 万股',ai['watch'][0]['text'])
            self.assertNotIn(MARK,ai['watch'][0]['text'])
            page=Path('web/analysis.js').read_text()
            self.assertIn('数字核验未完成',page)
            self.assertIn('旧报告未做数字核验',page)
            percent={'items':[{'label':'净资产收益率','value':'8.5%'}],'report':'2026-2','note':'合成财务'}
            percent_reply=json.dumps({
                'overview':[{'text':'净资产收益率 8.5%，标题增持 1000 万股，另有 77 亿元。','evidence':['N1','F1']}],
                'supporting':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
                'opposing':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
                'watch':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
            },ensure_ascii=False)
            with patch('analysis.today',return_value='2026-03-21'):
                finance=self.run_ai(self.engine(tmp,percent_reply,financial=percent),'f-percent','2026-2')
            self.assertEqual(finance['status'],'complete')
            self.assertEqual(finance['report']['number_gate'],{'status':'masked'})
            self.assertIn('8.5%',finance['report']['ai']['overview'][0]['text'])
            self.assertIn('1000 万股',finance['report']['ai']['overview'][0]['text'])
            self.assertNotIn('77',finance['report']['ai']['overview'][0]['text'])
            self.assertEqual(finance['report']['ai']['overview'][0]['evidence'],['N1','F1'])
            explicit={'items':[{'label':'销售净利率','value':8.5,'unit':'%'}],'report':'2026-2','note':'合成财务'}
            with patch('analysis.today',return_value='2026-03-21'):
                unit=self.run_ai(self.engine(tmp,percent_reply,financial=explicit),'f-unit','2026-2')
            self.assertEqual(unit['report']['number_gate'],{'status':'masked'})
            self.assertNotIn('unit_unverified',unit['report']['ai']['overview'][0])
            self.assertIn('8.5%',unit['report']['ai']['overview'][0]['text'])
            self.assertNotIn('77',unit['report']['ai']['overview'][0]['text'])
            bare={'items':[{'label':'归母净利润同比','value':93.381059}],'report':'2026-2','note':'合成财务'}
            bare_reply=json.dumps({
                'overview':[{'text':'同比 93.381059%，不能据此写成 93.38 元或 8.5%，标题增持 1000 万股，另有 9999 万股。','evidence':['N1','F1']}],
                'supporting':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
                'opposing':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
                'watch':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
            },ensure_ascii=False)
            with patch('analysis.today',return_value='2026-03-21'):
                unknown=self.run_ai(self.engine(tmp,bare_reply,financial=bare),'f-bare','2026-2')
            self.assertEqual(unknown['status'],'complete')
            self.assertEqual(unknown['report']['number_gate'],{'status':'masked','unit_unverified':True})
            self.assertIn('93.381059%',unknown['report']['ai']['overview'][0]['text'])
            self.assertIn('1000 万股',unknown['report']['ai']['overview'][0]['text'])
            self.assertNotIn('93.38 元',unknown['report']['ai']['overview'][0]['text'])
            self.assertNotIn('8.5%',unknown['report']['ai']['overview'][0]['text'])
            self.assertNotIn('9999',unknown['report']['ai']['overview'][0]['text'])
            self.assertIn(MARK,unknown['report']['ai']['overview'][0]['text'])
            self.assertTrue(unknown['report']['ai']['overview'][0]['unit_unverified'])
            self.assertEqual(unknown['report']['ai']['overview'][0]['evidence'],['N1','F1'])

    def test_analysis_run_keeps_unitless_financial_and_masks_unsourced_news(self):
        financial={'items':[{'label':'销售净利率','value':8.5}],'report':'2026-2','note':'同花顺财务指标；按所选报告期展示当前查询值。'}
        reply=json.dumps({
            'overview':[{'text':'销售净利率为8.5%，另有增持公告写了 9999 万股。','evidence':['F1','N1']}],
            'supporting':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
            'opposing':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
            'watch':[{'text':'标题增持 1000 万股。','evidence':['N1']}],
        },ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            analysis=self.engine(tmp,reply,financial=financial)
            with patch('analysis.today',return_value='2026-03-21'):
                done=self.run_ai(analysis,'f-unitless','2026-2')
            self.assertEqual(analysis.model.complete.call_count,1)
            self.assertEqual(done['status'],'complete')
            self.assertIsNone(done['error'])
            loaded=analysis.get('f-unitless')
            self.assertEqual(loaded['report']['number_gate'],{'status':'masked','unit_unverified':True})
            text=loaded['report']['ai']['overview'][0]['text']
            self.assertIn('销售净利率为8.5%',text)
            self.assertNotIn('9999',text)
            self.assertNotIn('万股',text)
            self.assertIn(MARK,text)
            self.assertIn(NOTE,text)
            self.assertTrue(loaded['report']['ai']['overview'][0]['unit_unverified'])
            self.assertEqual(loaded['report']['ai']['overview'][0]['evidence'],['F1','N1'])
            stored=next(item for item in loaded['report']['evidence'] if item['id']=='F1')
            self.assertEqual(stored['value']['items'],[{'label':'销售净利率','value':8.5}])
            self.assertNotIn('unit',stored['value']['items'][0])
            news=next(item for item in loaded['report']['evidence'] if item['id']=='N1')
            self.assertNotIn('9999',news['title'])
            self.assertNotIn('9999',json.dumps(news['value'],ensure_ascii=False))
            page=Path('web/analysis.js').read_text()
            self.assertIn('单位未核验',page)
            self.assertIn('ai-number-gate',page)
            self.assertIn('数字核验未完成',page)
            self.assertIn('旧报告未做数字核验',page)
            self.assertIn("gateStatus==='failed'",page)
            self.assertIn("gateStatus==='masked'",page)
            self.assertLess(page.index("gateStatus==='masked'"),page.index('旧报告未做数字核验'))
            self.assertLess(page.index('旧报告未做数字核验'),page.index('单位未核验'))
