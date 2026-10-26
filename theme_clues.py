"""Source keyword groups and official sector membership, kept distinct."""
import datetime as dt
import hashlib
import math
import re
import threading
from market import DataError, TZ
from rankings import finite, timestamp_day
from announcement_clues import LABELS, FINANCE_KEYS

FINANCE = re.compile('业绩|营收|利润|扭亏|亏损|盈利|增收|预增|预减')

def groups(rows, finance=False):
    result={}
    for row in rows:
        code=row.get('thscode')
        if not code:continue
        for keyword in set(k.strip() for k in row.get('keyword_list',[]) if isinstance(k,str) and k.strip()):
            if finance and not FINANCE.search(keyword):continue
            result.setdefault(keyword,{})[code]=row
    return [{'key':k,'name':k,'count':len(v),'stocks':list(v.values())} for k,v in sorted(result.items(),key=lambda x:(-len(x[1]),x[0]))]

class ThemeClues:
    def __init__(self,market,rankings,announcements=None):self.market=market;self.rankings=rankings;self.announcements=announcements;self.lock=threading.RLock()

    def grouped_source(self,day):
        try:return {**self.anomaly(day),'source_kind':'hithink'}
        except DataError as primary:
            if self.announcements is None:raise
            try:return {**self.announcements.get(day),'primary_warning':str(primary)}
            except (DataError,OSError,ValueError) as secondary:
                raise DataError('原异动解读：'+str(primary)+' 公告补充：'+str(secondary),
                    reason=getattr(secondary,'reason',None) or primary.reason) from None

    @staticmethod
    def source_groups(data,kind):
        if data.get('source_kind')!='cninfo':return groups(data['item'],kind=='finance')
        return [{**g,'name':LABELS[g['key']]} for g in groups(data['item'])
                if g['key'] in LABELS and (kind!='finance' or g['key'] in FINANCE_KEYS)]
    def validate(self,day,kind):
        dates=self.market.calendar()
        if day not in dates or kind not in ('topics','finance','concept','industry'):raise DataError('线索类型或观察日无效。')
        return dates
    def anomaly(self,day):
        dates=self.market.calendar()
        data=self.rankings.read(day+'-anomaly.json')
        if data is not None:
            return {**self.validate_anomaly(data,day,'本地'),'snapshot_source':'local'}
        if day!=dates[-1]:
            raise DataError(f'历史未采集：{day} 没有本地异动解读；接口仅提供当前数据，不用其他日期回填。', reason='not_collected')
        data=self.validate_anomaly(self.market.get('special-data/anomaly-analysis-list',ttl=300),day,'上游')
        self.rankings.save(day+'-anomaly.json',data)
        return {**data,'snapshot_source':'upstream'}

    @staticmethod
    def validate_anomaly(data,day,source):
        if not isinstance(data,dict) or not isinstance(data.get('item'),list):
            raise DataError(source+'异动解读格式无效。', reason='invalid_snapshot')
        actual=timestamp_day(data.get('timestamp'))
        if actual!=day:
            empty='，且返回空清单' if not data['item'] else ''
            raise DataError(f'日期不符：观察日 {day}；{source}异动解读日期 {actual or "缺失"}{empty}。本地没有可用的同日解读，未用其他日期替代。', reason='date_mismatch')
        if not data['item']:
            raise DataError(f'上游为空：{day} 的异动解读清单为空，不能据此认定没有异动，也不生成主题或业绩结论。', reason='upstream_empty')
        return data
    def catalog(self,day,kind):
        dates=self.validate(day,kind)
        with self.lock:
            if kind in ('topics','finance'):
                d=self.grouped_source(day)
                items=[{k:v for k,v in g.items() if k!='stocks'} for g in self.source_groups(d,kind)]
                if d['source_kind']=='cninfo':
                    coverage='；'.join({'finance':'业绩类','events':'经营/股权类','all':'全部公告类别'}.get(c['family'],('定向股票 '+c['family'].split(':')[-1]) if c['family'].startswith('issuer:') else c['family'])+' '+str(c['received'])+'/'+str(c['total'] if c['total'] is not None else '未知')+' 条'+('（未完整）' if not c['complete'] else '')+(' '+c['warning'] if c['warning'] else '') for c in d['coverage'])
                    progress=('本次索引条数已对齐' if d['pagination_reconciled'] else '本次索引条数未对齐')+'；有效 A 股 '+str(d['unique_verified'])+' 条。'
                    if d.get('backfill'):progress+=' 历史补采复用 '+str(d['backfill']['seed_records'])+' 次，追加 '+str(d['backfill']['additional_requests'])+' 次。'
                    if any(c.get('stop')=='page_limit' for c in d['coverage']):
                        progress+=(' 主查询已达50次；分段补查已完成本次对账。' if d['pagination_reconciled'] else ' 主查询已达50次上限，剩余未采集。')
                        if d.get('segment_repair'):progress+=' 分段补查 '+str(d['segment_repair']['requests'])+'/12 次追加请求。'
                    return {'items':items,'timestamp':d['timestamp'],'source_kind':'cninfo','snapshot_source':d['snapshot_source'],
                        'source_summary':'巨潮公告索引补充'+(' · 有限覆盖' if d['limited'] else '')+'：公告日 '+d['notice_day']+'，保守可用日 '+day+'。'+progress+'仅按标题归类，非异动归因。',
                        'notice_day':d['notice_day'],'fetched_at':d['fetched_at'],'limited':d['limited'],'coverage':d['coverage'],
                        'note':d['note']+' 覆盖：'+coverage+'。原来源缺失原因：'+d['primary_warning']}
                return {'items':items,'timestamp':d['timestamp'],'snapshot_source':d['snapshot_source'],'note':('优先使用观察日 '+day+' 的本地异动解读。' if d['snapshot_source']=='local' else '')+'按同花顺异动解读原始关键词归组，覆盖上游收录的涨跌异动股票，非全市场财务筛选。解读由上游 AI 汇总，不等于已核实的涨跌原因。'}
            if day!=dates[-1]:raise DataError('历史归属不可用：板块接口只提供当前成分，没有该观察日可用的板块目录；不使用当前成分回填。请切换最新观察日。', reason='not_collected')
            d=self.market.get('a-share-index/catalog/ths-index-list',{'tag':'cn_concept' if kind=='concept' else 'industry'},ttl=86400)
            if not d['item']:raise DataError('上游为空：未返回板块目录，不能据此判断没有相关板块。', reason='upstream_empty')
            return {'items':[{'key':r['thscode'],'name':r['name'],'count':None} for r in d['item']], 'timestamp':d.get('timestamp'),'note':'同花顺正式板块目录及当前成分股。归属是背景信息，不代表当日涨跌原因；当前成分不用于历史回测。'}
    def detail(self,day,kind,key):
        catalog=self.catalog(day,kind)
        chosen=next((r for r in catalog['items'] if r['key']==key),None)
        if not chosen:raise DataError('未找到所选线索。')
        with self.lock:
            if kind in ('topics','finance'):
                source=self.grouped_source(day)
                group=next((g for g in self.source_groups(source,kind) if g['key']==key),None)
                if group is None:raise DataError('线索来源已变化，请刷新清单后重新选择。')
                rows=[{'thscode':r['thscode'],'name':r.get('stock_name') or r['thscode'],'tag':r.get('tag_name'),'analysis':r.get('analysis_content') or '',
                       'evidence':[e for e in r.get('evidence',[]) if key in e['keys']]} for r in group['stocks']]
                timestamp=catalog['timestamp']
            else:
                d=self.market.get('a-share-index/constituents/ths-stock-list',{'thscode':key},ttl=21600)
                rows=[{'thscode':r['thscode'],'name':r.get('name') or r['thscode']} for r in d['item']];timestamp=d.get('timestamp')
                # Archive as observed now; never label current membership as a past day.
                actual=dt.datetime.now(TZ).date().isoformat()
                if day==actual and finite(timestamp) and dt.datetime.fromtimestamp(timestamp/1000,TZ).date().isoformat()==day:
                    with self.rankings.lock:
                        self.rankings.save(self.member_file(day,kind,key), {'items':rows,'timestamp':timestamp,'observed_date':actual})
            quote_note='';quote_warning='';quote_source=None;quotes={};quote_time=None
            try:
                snapshot=self.rankings.snapshot_for_day(day)
                quotes={r['thscode']:r for r in snapshot['items']};quote_time=snapshot['timestamp']
                quote_source=snapshot['snapshot_source']
                if snapshot['snapshot_source']=='local':quote_note='涨跌幅使用观察日 '+day+' 的本地行情快照。'
            except DataError as e:
                quote_warning=str(e)
                quote_note=quote_warning+' 涨跌幅显示缺失，线索与成分清单仍保留。'
            for r in rows:r['pct']=quotes.get(r['thscode'],{}).get('price_change_ratio_pct')
            rows.sort(key=lambda r:(not finite(r['pct']),-r['pct'] if finite(r['pct']) else 0,r['thscode']))
            return {'name':chosen['name'],'items':rows,'timestamp':timestamp,'quote_timestamp':quote_time,'quote_source':quote_source,'quote_warning':quote_warning,'note':catalog['note']+' '+quote_note,
                    'source_kind':catalog.get('source_kind','hithink'),'source_summary':catalog.get('source_summary',''),
                    'notice_day':catalog.get('notice_day'),'fetched_at':catalog.get('fetched_at'),'coverage':catalog.get('coverage',[])}
    def financial(self,code,report):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code) or not re.fullmatch(r'20\d{2}-[1-4]',report):raise DataError('股票或报告期无效。')
        d=self.market.get('financials/indicators',{'thscode':code,'report':report},ttl=21600)
        values={r['index_id']:r.get('value') for a in d['abilities'] for r in a.get('indicators',[]) if isinstance(r,dict) and 'index_id' in r}
        labels=[('operating_income_yoy_growth_ratio','营收同比'),('calculate_operating_income_yoy_growth_ratio','营收同比'),('net_profit_yoy_growth_ratio','净利润同比'),('calculate_parent_holder_net_profit_yoy_growth_ratio','归母净利润同比'),('sale_net_interest_ratio','销售净利率')]
        items=[];seen=set()
        for key,label in labels:
            if key not in values or label in seen:continue
            try:v=float(values[key]);v=v if math.isfinite(v) else None
            except (ValueError,TypeError):v=None
            items.append({'label':label,'value':v});seen.add(label)
        return {'items':items,'report':report,'note':'同花顺财务指标；按所选报告期展示当前查询值。接口无披露时间，不能证明历史观察日已知这些数据；正同比也不自动代表盈利或扭亏。'}

    @staticmethod
    def member_file(day,kind,key):
        digest=hashlib.sha256(key.encode()).hexdigest()[:24]
        return f'{day}-{kind}-{digest}-members.json'

    def history(self,day,kind,key):
        dates=self.validate(day,kind)
        selected=dates[max(0,dates.index(day)-4):dates.index(day)+1]
        if key.startswith('cninfo:'):
            if self.announcements is None:raise DataError('公告补充来源未启用。',reason='not_collected')
            items=[]
            for date in selected:
                data=self.announcements.read(date)
                group=next((g for g in self.source_groups(data,kind) if g['key']==key),None) if data else None
                items.append({'date':date,'count':len(group['stocks']) if group else None})
            return {'items':items,'tracking_mode':'announcements','note':'仅列本机已核验的公告样本；缺失不记为零。公告新增可用日与异动成员口径不同，不混入同花顺异动历史，也不计算成员进出或样本收益。'}
        snapshots=[]
        with self.rankings.lock:
            for date in selected:
                if kind in ('topics','finance'):
                    archive=self.rankings.read(date+'-anomaly.json')
                    if archive is not None:
                        group=next((g for g in groups(archive['item'],kind=='finance') if g['key']==key),None)
                        members=group['stocks'] if group else []
                    else: members=None
                else:
                    archive=self.rankings.read(self.member_file(date,kind,key))
                    members=archive['items'] if archive else None
                snapshots.append({'date':date,'count':len(members) if members is not None else None,'members':members})
            quotes=self.rankings.read(day+'-market.json')
        by_code={r['thscode']:r for r in quotes['items']} if quotes and quotes.get('source_date')==day else {}
        previous=snapshots[-2]['members'] if len(snapshots)>1 else None
        current=snapshots[-1]['members']
        before={r['thscode'] for r in previous} if previous is not None else None
        after={r['thscode'] for r in current} if current is not None else None
        cohort=[]
        for r in previous or []:
            q=by_code.get(r['thscode'],{})
            value=q.get('price_change_ratio_pct')
            valid=finite(value) and finite(q.get('volume')) and q['volume']>0 and finite(q.get('last_price')) and q['last_price']>0
            cohort.append({'thscode':r['thscode'],'name':r.get('name') or r.get('stock_name') or r['thscode'],'pct':value if valid else None,'retained':r['thscode'] in after if after is not None else None})
        values=[r['pct'] for r in cohort if finite(r['pct'])]
        return {'items':[{'date':r['date'],'count':r['count']} for r in snapshots],
                'entered':len(after-before) if before is not None and after is not None else None,
                'left':len(before-after) if before is not None and after is not None else None,
                'cohort':cohort,'previous_available':previous is not None,'sample':len(values),
                'positive':sum(v>0 for v in values),'average':sum(values)/len(values) if values else None,
                'note':'最近 5 个交易日，仅用本地已采集记录；缺失不记为零。昨日样本固定保留，退出线索的股票仍参与跟踪。概念与行业成分从实际访问当日起存档，不回填历史；样本表现不是因果结论。'}
