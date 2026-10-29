"""Deterministic, read-only synthetic demo. No credentials, external I/O, model calls or user database."""
import datetime as dt
import math

from analysis import technical
from compare import compare_reports
from reading_notes import invalidation_lines
from report_compare import delta_view
from tech_score import evaluate
from watch_points import describe_point, validate_points
from market import Market,DataError,TZ

NOTICE='演示模式：全部数据由程序合成，非真实行情；不联网、不调用AI、不保存操作。'
STOCKS=[dict(thscode='600000.SH',name='合成示例甲',asset_type='a-share'),dict(thscode='000001.SZ',name='合成示例乙',asset_type='a-share'),dict(thscode='920001.BJ',name='合成示例丙',asset_type='a-share')]


def _labeled(points):
    return [dict(point, label=describe_point(point)) for point in validate_points(points)]


DEMO_POINTS=[
    _labeled([
        dict(id='wp-600000-ma',subject='收盘价 vs MA20',kind='metric',metric='close',op='>=',ref_metric='ma20',days=1),
        dict(id='wp-600000-text',subject='下一份财报预约披露日',kind='text',source='巨潮公告索引/自行核对',note='合成文本观察，核对披露时点是否已公开。'),
    ]),
    _labeled([dict(id='wp-000001-rsi',subject='RSI14',kind='metric',metric='rsi14',op='>=',value=70,days=1)]),
    _labeled([dict(id='wp-920001-vol',subject='较前5日均量',kind='metric',metric='volume_ratio5',op='>=',value=1.2,days=1)]),
]


class DemoMarket(Market):
    def __init__(self):
        self.dates=[];d=dt.date(2025,1,6)
        while len(self.dates)<300:
            if d.weekday()<5:self.dates.append(d.isoformat())
            d+=dt.timedelta(days=1)
        self.series={}
        for j,s in enumerate(STOCKS):
            bars=[];previous=12+j*7
            for i,date in enumerate(self.dates):
                close=round(12+j*7+i*.035+math.sin(i/8+j)*1.1+math.sin(i/2.8)*.22,4)
                opening=round(previous*(1+math.sin(i)*.003),4)
                bars.append(dict(date_ms=int(dt.datetime.fromisoformat(date+'T15:00:00+08:00').timestamp()*1000),open_price=opening,high_price=round(max(opening,close)+.18,4),low_price=round(min(opening,close)-.16,4),close_price=close,volume=100000+1000*((i*17+j*11)%70)))
                previous=close
            self.series[s['thscode']]=bars

    def calendar(self):return list(self.dates)
    def daily(self,day,kind,loader,force=False):return loader(False)
    def pool(self,day,kind='up',force=False):self.window(day,1);return []
    def hot(self,day,force=False):self.window(day,1);return dict(date=day,items=[dict(s,rank=i+1,heat=3000-i*450)for i,s in enumerate(STOCKS)])
    def get(self,endpoint,params=None,ttl=60):
        p=params or {}
        if endpoint=='prices/historical':
            if p.get('thscode')not in self.series:raise DataError('演示中只提供三只合成股票。')
            return dict(item=[dict(b)for b in self.series[p['thscode']]if p['start']<=b['date_ms']<=p['end']])
        if endpoint=='meta/tickers/search':return dict(item=[dict(s)for s in STOCKS if p.get('q','')in(s['name']+s['thscode'])])
        if endpoint=='special-data/hot-stock-rank-trend':return dict(item=[dict(date=d,rank=STOCKS.index(next(s for s in STOCKS if s['thscode']==p['thscode']))+1)for d in self.dates if p['start_date']<=d<=p['end_date']])
        raise DataError('演示不提供该数据源；请查看合成日K、技术报告或新手指南。')


class Demo:
    def __init__(self):self.market=DemoMarket();self.day=self.market.dates[-1]
    def quotes(self,day):
        self.market.window(day,1);i=self.market.dates.index(day);rows=[]
        for s in STOCKS:
            b=self.market.series[s['thscode']][i];prev=self.market.series[s['thscode']][max(0,i-1)]['close_price']
            rows.append(dict(s,last_price=b['close_price'],price_change_ratio_pct=round((b['close_price']/prev-1)*100,2),volume=b['volume'],turnover=round(b['close_price']*b['volume'],2)))
        return rows
    def report(self,code,day):
        self.market.window(day,1);name=next((s['name']for s in STOCKS if s['thscode']==code),None)
        if name is None:raise DataError('演示股票不存在。')
        t=technical(self.market.prices(code,day,250)['items']);assessment=evaluate(t,dict(source='synthetic demo',window=250,asof=day))
        p=dict(code=code,name=name,date=day,generated_at=day+'T16:00:00+08:00',prompt_version='demo-synthetic-1',technical=t,assessment=assessment,ai=None,model=None,limitations=[NOTICE,'合成工作日日历，仅用于操作演示，不包含真实交易所节假日。'],evidence=[dict(id='T1',title='合成行情与程序技术指标',value=t,source='程序合成 / 正式指标计算器')])
        i=self.market.dates.index(day);old=None
        if i>0:
            old_day=self.market.dates[i-1];old=dict(p,date=old_day,technical=technical(self.market.prices(code,old_day,250)['items']))
        raw=compare_reports(old,p);view=delta_view(raw);view['raw']=raw
        return dict(id='demo-'+code+'-'+day,code=code,day=day,created=p['generated_at'],status='complete',phase='合成技术样例 · 只读',report=p,error=None,delta=view,reading_notes=invalidation_lines(p))
    def observed(self,day):
        dates=self.market.dates
        if day not in dates:return day
        return dates[max(0,dates.index(day)-20)]
    def records(self,day):
        observed=self.observed(day);rows=[]
        for i,s in enumerate(STOCKS):
            r=self.report(s['thscode'],observed)
            rows.append(dict(id='demo-record-'+str(i),**s,date=observed,createdAt=observed+'T16:00:00+08:00',note='合成关注理由：用于学习量价与指标，不代表真实持仓或建议。',active=True,report_id=r['id'],watch_points=DEMO_POINTS[i]))
        return rows
    def get(self,path,q):
        one=lambda k,default='':q.get(k,[default])[0]
        day=one('date',self.day);code=one('code',STOCKS[0]['thscode'])
        if path=='/api/runtime':return dict(mode='demo',read_only=True,synthetic=True,notice=NOTICE)
        if path=='/api/health':return dict(app='stock-board',status='ok',mode='demo')
        if path=='/api/settings':return dict(configured=False,managed=False,demo=True)
        if path=='/api/model-settings':return dict(configured=False,has_key=False,base_url='',model='',demo=True)
        if path=='/api/calendar':return dict(dates=self.market.calendar(),note=NOTICE)
        if path=='/api/search':return self.market.search(one('q'))
        if path=='/api/counts':return self.market.counts(day,int(one('days','20')))
        if path=='/api/hot':return self.market.hot(day)
        if path=='/api/trend':return self.market.trend(code,day,int(one('days','5')))
        if path=='/api/prices':return self.market.candles(code,day,one('cycle','day'),int(one('period','60')),one('start')or None,include_context=one('context')=='1')
        if path=='/api/research':return self.market.research(day)
        if path=='/api/overview-dates':return dict(dates=self.market.calendar())
        if path=='/api/overview':
            rows=self.quotes(day);bins=[0]*7
            for r in rows:
                v=r['price_change_ratio_pct'];bins[0 if v<=-5 else 1 if v<=-3 else 2 if v<0 else 3 if v==0 else 4 if v<3 else 5 if v<5 else 6]+=1
            return dict(timestamp=int(dt.datetime.fromisoformat(day+'T15:00:00+08:00').timestamp()*1000),up=sum(r['price_change_ratio_pct']>0 for r in rows),down=sum(r['price_change_ratio_pct']<0 for r in rows),flat=sum(r['price_change_ratio_pct']==0 for r in rows),bins=bins,valid=3,received=3,universe=3,excluded=0,traded=3,turnover_sample=3,turnover=sum(r['turnover']for r in rows),leaders=rows,note=NOTICE)
        if path=='/api/rankings':return dict(date=day,source_date=day,source='程序合成示例',items=[dict(r,rank=i+1,heat=3000-i*450,rank_change=0)for i,r in enumerate(self.quotes(day))],total=3,limit=int(one('limit','10')),offset=0,note=NOTICE)
        if path=='/api/observations':return dict(items=self.records(self.day))
        if path=='/api/followup':
            from tracking import followup
            code=one('code');observed=one('observed');end=one('date',self.day);oid=one('id','')
            class _records:
                def __init__(self,items):self.items=items
                def list(self):return dict(items=self.items)
            return followup(self.market,code,observed,end,observation_id=oid or None,tracking=_records(self.records(self.day)) if oid else None)
        if path=='/api/workbench':
            items=[];recs={r['thscode']:r for r in self.records(day if day in self.market.dates else self.day)}
            for s in STOCKS:
                r=self.report(s['thscode'],day);p=r['report'];rec=recs.get(s['thscode'],{})
                items.append(dict(s,note=rec.get('note') or '合成研究记录，用于体验工作台。',observed=rec.get('date') or day,record_count=1,status='ready',report={k:r[k]for k in('id','day','created','status','phase','error')},technical=p['technical'],assessment=p['assessment'],overview=[],watch=[],has_ai=False,limitations=p['limitations'],watch_points=rec.get('watch_points') or []))
            return dict(date=day,items=items,counts=dict(stocks=3,ready=3,pending=0,records=3),future_records=0)
        if path=='/api/analysis-history':return dict(items=[{k:r[k]for k in('id','code','day','created','status','phase','error')}for r in [self.report(code,day)]])
        if path=='/api/analysis':
            identifier=one('id');parts=identifier.split('-')
            if len(parts)!=5 or parts[0]!='demo':raise DataError('演示报告不存在。')
            return self.report(parts[1],'-'.join(parts[2:]))
        if path=='/api/batch':return dict(items=[])
        if path=='/api/disclosures':return dict(status='unconfigured',items=[],versions=[],scope=NOTICE,note='演示不分发真实公告原文；真实模式需自行核验和导入。')
        if path=='/api/news':return dict(items=[],updated_at=self.day+' 16:00:00',source='演示未加载真实新闻',stale=False)
        if path=='/api/stock-news':return dict(items=[],updated_at=day+' 16:00:00',stale=False,warning=NOTICE)
        if path=='/api/chan':
            from chan_structure import for_market
            return for_market(self.market,code,day,include_candidates=one('candidates')=='1')
        if path=='/api/clue-catalog':return dict(items=[],timestamp=None,source_summary=NOTICE,note='演示没有真实主题、业绩或板块来源。可查看合成行情或新手指南。')
        raise DataError('演示样本未覆盖此功能；数据保持缺失，不联网补取。')
