"""Read-only verification of explicitly collected historical ordinary-page evidence packages."""
import datetime as dt
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode

from announcement_clues import AnnouncementClues, normalize_notice
from market import DataError
from disclosures import date_value

PROFILE='verified-backfill-v1'
PARTS={'seed-1':50,'seed-2':12,'additional':20}


def _verify(folder,day,*,require_complete=True):
    folder=Path(folder);parsed=date_value(day)
    if parsed is None:raise DataError('历史补采观察日无效。',reason='invalid_snapshot')
    notice=(parsed-dt.timedelta(days=1)).isoformat()
    meta=json.loads((folder/'package.json').read_text())
    if meta.get('schema_version')!=1 or meta.get('day')!=day or meta.get('notice_day')!=notice:
        raise DataError('历史补采元数据日期不符。',reason='invalid_snapshot')
    docs={};excluded=set();pages=set();targets=set();total=None;records=0;fetched=[];seed=set();duplicates=0;counts={}
    for part,limit in PARTS.items():
        ledger=folder/part/'ledger.json'
        if not ledger.exists():counts[part]=0;continue
        data=json.loads(ledger.read_text());requests=data.get('requests')
        if not isinstance(requests,list)or len(requests)>limit or data.get('max_requests')!=limit:
            raise DataError('历史补采账本额度或格式无效。',reason='invalid_snapshot')
        counts[part]=len(requests)
        for record in requests:
            records+=1;body=record.get('request_body_utf8','');q=parse_qs(body,keep_blank_values=True)
            try:
                page=int(q['pageNum'][0]);stock=q['stock'][0]
                if not 1<=page<=82 or any(len(v)!=1 for v in q.values()):raise ValueError()
                allowed=set()
                if stock:
                    if page!=1:raise ValueError()
                    for issuer in stock.split(';'):
                        code,org=issuer.split(',')
                        if not re.fullmatch(r'\d{6}',code)or not re.fullmatch(r'[A-Za-z0-9]{1,40}',org):raise ValueError()
                        allowed.add(code)
                expected=AnnouncementClues.query(notice,'all',page);expected['stock']=stock
                if body!=urlencode(expected):raise ValueError()
            except (ValueError,KeyError,IndexError,TypeError):
                raise DataError('历史补采请求日期、股票范围或参数无效。',reason='invalid_snapshot')from None
            payload=AnnouncementClues.payload(folder/part,record,body)
            rows,count=payload.get('announcements'),payload.get('totalAnnouncement')
            if rows is None and count==0:rows=[]
            if not isinstance(rows,list)or type(count)is not int or count<0:
                raise DataError('历史补采响应格式无效。',reason='invalid_snapshot')
            if not stock:
                if total is not None and total!=count:raise DataError('历史补采索引总量变化，缺口保留。',reason='incomplete')
                total=count;pages.add(page)
            for row in rows:
                outside=False
                try:doc=normalize_notice(row,notice);code=doc['thscode'].split('.')[0]
                except ValueError as exc:
                    if str(exc)!='not a supported A-share code' or not isinstance(row,dict)or not re.fullmatch(r'\d{6}',str(row.get('secCode',''))):
                        raise DataError('历史补采公告日期或身份核验失败：'+str(exc),reason='date_mismatch'if'outside requested day'in str(exc)else'invalid_snapshot')from None
                    try:doc=normalize_notice({**row,'secCode':'600000'},notice)
                    except ValueError as exc:raise DataError('范围外证券日期或身份核验失败：'+str(exc),reason='invalid_snapshot')from None
                    code=row['secCode'];outside=True
                if allowed and code not in allowed:raise DataError('历史补采单股参数未生效。',reason='invalid_snapshot')
                key=doc['id'],code
                if part.startswith('seed'):seed.add(key)
                if outside:excluded.add(key);continue
                previous=docs.get(key)
                if previous:
                    duplicates+=1
                    if any(previous[k]!=doc[k]for k in ('name','title','notice_date','available_at','timestamp','url')):
                        raise DataError('历史补采同一身份内容冲突，未覆盖旧证据。',reason='invalid_snapshot')
                    org=row.get('orgId')
                    if isinstance(org,str)and re.fullmatch(r'[A-Za-z0-9]{1,40}',org):targets.add((code,org))
                doc.update(index_sha256=record['sha256'],index_fetched_at=record.get('fetched_at'),query_family='历史普通分页补采')
                docs.setdefault(key,doc)
            fetched.append(record.get('fetched_at'))
    actual=len(docs)+len(excluded)
    needed=set(range(1,(total+29)//30+1))if total is not None else set()
    complete=bool(total and actual==total and needed.issubset(pages))
    if total is not None and actual>total:raise DataError('历史补采唯一条数超过索引总量。',reason='invalid_snapshot')
    if require_complete and not complete:raise DataError(f'历史补采尚未完整：已核验 {actual}/{total if total is not None else "未知"} 条，缺口保留。',reason='incomplete')
    return dict(day=day,notice_day=notice,documents=docs,excluded=excluded,total=total,pages=pages,
        targets=targets,records=records,counts=counts,seed_unique=len(seed),duplicates=duplicates,complete=complete,
        fetched_at=max((x for x in fetched if x),default=None))


def verify(folder,day,*,require_complete=True):
    try:return _verify(folder,day,require_complete=require_complete)
    except DataError:raise
    except (OSError,ValueError,TypeError,KeyError,IndexError):
        raise DataError('历史补采原始证据缺失或格式无效，未采用。',reason='invalid_snapshot')from None


def load(folder,day):
    state=verify(folder,day);docs=state['documents'];merged={}
    for doc in docs.values():
        if not doc['keys']:continue
        row=merged.setdefault(doc['thscode'],dict(thscode=doc['thscode'],stock_name=doc['name'],keyword_list=[],tag_name='公告标题归类',analysis_content='',evidence=[]))
        row['keyword_list']=sorted(set(row['keyword_list'])|set(doc['keys']));row['evidence'].append(doc)
    if not merged:raise DataError('历史补采已核验，但没有匹配的公告标题线索。',reason='no_matching_evidence')
    count=len(docs);outside=len(state['excluded']);added=count+outside-state['seed_unique']
    return dict(source_kind='cninfo',snapshot_source='local',date=day,notice_day=state['notice_day'],timestamp=max(d['timestamp']for d in docs.values()),
        fetched_at=state['fetched_at'],item=list(merged.values()),limited=True,pagination_reconciled=True,
        coverage=[dict(family='历史普通分页补采',received=count+outside,total=state['total'],complete=True,warning='')],
        unique_verified=count,excluded_non_a=outside,repair_added=0,legacy_added=0,segment_repair=None,
        backfill=dict(seed_records=state['counts']['seed-1']+state['counts']['seed-2'],additional_requests=state['counts']['additional'],added=added),
        note=f'默认普通分页，分段仅用于补缺。本次历史普通分页补采：复用 {state["counts"]["seed-1"]+state["counts"]["seed-2"]} 次已冻结请求，追加 {state["counts"]["additional"]}/20 次专用补采请求；额外核验 {added} 条。有效A股 {count}＋范围外 {outside}＝索引 {state["total"]} 条。'
        '公告日次日00:00（北京时间）保守可用；日期、身份、原文路径和SHA逐次核验。仅按标题归类，不判断涨跌原因。当前索引不保证还原当日网页版本；未解析 PDF 财务数值。日常自动额度未提高，历史补采只读复用，缺失行情不使用其他日期补齐。')
