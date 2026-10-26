"""Explicit, bounded collection of a deduplicated stock list; no keys or model calls."""
import argparse
import datetime as dt
import gzip
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode,urlsplit

from disclosures import annual_identity,TZ
from scripts.official_collect import Collector,sha

INDEX='https://www.cninfo.com.cn/new/hisAnnouncement/query'
HEADERS={'Accept':'application/json','Referer':'https://www.cninfo.com.cn/',
         'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}


def load_roster(path):
    source=json.loads(Path(path).read_text());stocks={}
    for row in source['stocks']:
        code=row.get('code','');name=row.get('name','')
        if not re.fullmatch(r'\d{6}\.(SH|SZ)',code) or not isinstance(name,str) or not name.strip():
            raise ValueError('invalid stock identity')
        if code in stocks and stocks[code]['name']!=name:raise ValueError('conflicting stock names')
        stocks.setdefault(code,{'code':code,'name':name})
    if not 1<=len(stocks)<=50:raise ValueError('stock batch must have 1..50 unique stocks')
    return list(stocks.values())


def official_lookup(source):
    source=Path(source);ledger=json.loads((source/'ledger.json').read_text())
    rows=[r for r in ledger['requests'] if r.get('ok') and r['url']=='https://www.cninfo.com.cn/new/data/szse_stock.json']
    if not rows:raise ValueError('official stock-list evidence missing')
    record=rows[-1];raw=(source/record['raw']).read_bytes()
    if sha(raw)!=record['sha256'] or record.get('raw_complete') is False:raise ValueError('bad stock-list evidence')
    raw=gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw
    return {r['code']:r for r in json.loads(raw)['stockList']},record


def selected_rows(payload,code,day):
    rows=payload.get('announcements') or [];total=payload.get('totalAnnouncement')
    if not isinstance(total,int) or isinstance(total,bool) or total!=len(rows) or not rows:
        raise ValueError('empty or incomplete announcement index; not safe to import')
    unique={}
    for row in rows:
        if row.get('secCode')!=code[:6]:raise ValueError('cross-stock announcement index')
        identifier=str(row['announcementId'])
        if not re.fullmatch(r'\d+',identifier):raise ValueError('invalid announcement identity')
        if identifier in unique and unique[identifier]!=row:raise ValueError('conflicting announcement identity')
        unique[identifier]=row
    if len(unique)!=total:raise ValueError('duplicate announcement rows leave index completeness unverified')
    eligible=[]
    for row in unique.values():
        identity=annual_identity(row['announcementTitle']);stamp=row.get('announcementTime')
        if not identity:continue
        if not isinstance(stamp,int) or isinstance(stamp,bool):raise ValueError('invalid announcement date')
        notice=dt.datetime.fromtimestamp(stamp/1000,TZ).date()
        if notice<=day:eligible.append((identity,row))
    periods=sorted({identity[0] for identity,row in eligible if identity[1] in ('annual_report','revised_report')})[-2:]
    if len(periods)!=2:raise ValueError('latest two annual-report periods not found')
    for period in periods:
        if not any(identity==(period,'annual_report') for identity,row in eligible):raise ValueError('latest period has no original report')
    return periods,[row for identity,row in eligible if identity[0] in periods]


class SourceStopped(Exception):pass


class BatchCollector:
    def __init__(self,folder,stocks,lookup_source,*,day=None,pause_s=.4,collector_factory=Collector):
        self.folder=Path(folder);self.stocks=stocks;self.lookup_source=Path(lookup_source)
        self.day=day or dt.datetime.now(TZ).date();self.pause_s=pause_s;self.factory=collector_factory
        self.failures={};self.requests=0;self.limit=len(stocks)*10
        self.lookup,self.lookup_record=official_lookup(lookup_source)
        self.report={'asof':self.day.isoformat(),'status':'running','stocks':[],
            'max_requests_per_stock':10,'max_total_requests':self.limit,'model_calls':0,
            'lookup_source':str(self.lookup_source),'lookup_sha256':self.lookup_record['sha256']}

    def save(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        path=self.folder/'collection.json';temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)

    def fetch(self,collector,url,**kwargs):
        # Reuse exact frozen successful requests; do not retry failures by resetting a round.
        method=kwargs.get('method','GET');body=kwargs.get('data');body=body.decode() if isinstance(body,bytes) else body
        matches=[r for r in collector.data['requests'] if r['url']==url and r['method']==method and r.get('request_body_utf8')==body]
        if matches:
            record=matches[-1]
            if not record.get('ok') or record.get('raw_complete') is False:raise ValueError('previous request failed; no automatic retry')
            raw=(collector.folder/record['raw']).read_bytes()
            if sha(raw)!=record['sha256']:raise ValueError('cached response hash mismatch')
            return record
        if self.requests>=self.limit:raise SourceStopped('total request budget exhausted')
        if self.pause_s:time.sleep(self.pause_s)
        record=collector.fetch(url,**kwargs);self.requests+=1
        # Redirects count too, against the per-stock budget and actual global ledger count.
        self.requests=sum(len(json.loads(p.read_text())['requests']) for p in self.folder.glob('*/ledger.json'))
        host=urlsplit(url).hostname
        if not record.get('ok'):
            if record.get('stop')=='budget_exhausted':raise ValueError('stock request budget exhausted')
            self.failures[host]=self.failures.get(host,0)+1
            if record.get('status') in (401,402,403,429) or record.get('stop')=='access_or_rate_limit' or self.failures[host]>=2:
                raise SourceStopped('source access/rate limit or repeated failure; stopped entire batch')
            raise ValueError('public request failed: '+str(record.get('result') or record.get('stop')))
        self.failures[host]=0
        return record

    def collect_stock(self,stock,download):
        code=stock['code'];info=self.lookup.get(code[:6])
        if not info or info.get('category')!='A股' or not info.get('orgId'):raise ValueError('official stock lookup missing')
        collector=self.factory(self.folder/code,max_requests=10)
        params={'pageNum':1,'pageSize':100,'column':'sse' if code.endswith('.SH') else 'szse',
            'tabName':'fulltext','stock':code[:6]+','+info['orgId'],'searchkey':'年度报告','secid':'',
            'category':'','trade':'','seDate':f'{self.day.year-2}-01-01~{self.day.isoformat()}',
            'sortName':'time','sortType':'desc','isHLtitle':'false'}
        record=self.fetch(collector,INDEX,data=urlencode(params),method='POST',headers=HEADERS,name='annual-discovery')
        raw=(collector.folder/record['raw']).read_bytes();raw=gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw
        periods,rows=selected_rows(json.loads(raw),code,self.day)
        selection={'code':code,'name':stock['name'],'official_name':info['zwjc'],'orgId':info['orgId'],
            'periods':periods,'index_sha256':record['sha256'],'ids':[str(row['announcementId']) for row in rows],
            'rows':rows,'status':'discovered'}
        (collector.folder/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
        if download:
            pending=[row for row in rows if not any(r.get('ok') and r['url']=='https://static.cninfo.com.cn/'+row['adjunctUrl'] for r in collector.data['requests'])]
            if len(collector.data['requests'])+len(pending)>10:raise ValueError('selected files exceed stock request budget')
            for row in rows:
                self.fetch(collector,'https://static.cninfo.com.cn/'+row['adjunctUrl'],expect='pdf',name='annual-pdf-'+str(row['announcementId']))
            if collector.replay()['status']!='pass':raise ValueError('frozen ledger incomplete')
            selection['status']='collected'
            (collector.folder/'selection.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2)+'\n')
        return {k:v for k,v in selection.items() if k!='rows'}

    def run(self,*,download=True):
        self.folder.mkdir(parents=True,exist_ok=True);self.save()
        self.requests=sum(len(json.loads(p.read_text())['requests']) for p in self.folder.glob('*/ledger.json'))
        # A previous rate-limit or repeated failure remains a stop across resumptions/stocks.
        previous=sorted((r for p in self.folder.glob('*/ledger.json') for r in json.loads(p.read_text())['requests']),key=lambda r:r['started_at'])
        for record in previous:
            host=urlsplit(record['url']).hostname
            if record.get('ok'):self.failures[host]=0
            else:
                self.failures[host]=self.failures.get(host,0)+1
                if record.get('status') in (401,402,403,429) or self.failures[host]>=2:
                    self.report.update(status='stopped',reason='prior source failure; no automatic retry');self.save();return self.report
        for stock in self.stocks:
            try:result=self.collect_stock(stock,download)
            except SourceStopped as exc:
                self.report['stocks'].append({**stock,'status':'failed','reason':str(exc)})
                self.report.update(status='stopped',reason=str(exc));break
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
                result={**stock,'status':'failed','reason':str(exc)}
            self.report['stocks'].append(result);self.save()
            print(stock['code'],result['status'],result.get('periods',result.get('reason')),flush=True)
        else:
            self.report['status']='collected' if download and all(x['status']=='collected' for x in self.report['stocks']) else 'discovered' if not download and all(x['status']=='discovered' for x in self.report['stocks']) else 'incomplete'
        self.report['actual_requests']=self.requests;self.save();return self.report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stocks',required=True)
    parser.add_argument('--lookup-source',required=True);parser.add_argument('--folder',required=True)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--discover-only',action='store_true')
    args=parser.parse_args();stocks=load_roster(args.stocks)
    if not args.execute:
        print(json.dumps({'status':'dry_run','stocks':stocks,'max_total_requests':len(stocks)*10},ensure_ascii=False,indent=2))
    else:
        result=BatchCollector(args.folder,stocks,args.lookup_source).run(download=not args.discover_only)
        print(result['status'],result['actual_requests'] if 'actual_requests' in result else 0,flush=True)
        raise SystemExit(0 if result['status'] in ('collected','discovered') else 2)
