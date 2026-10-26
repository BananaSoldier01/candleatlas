"""Bounded market and issuer segments that supplement an exhausted, frozen daily scan."""
from collections import Counter
import re
from urllib.parse import urlencode

from announcement_clues import AnnouncementClues, INDEX, MAX_BYTES, normalize_notice
from market import DataError

PROFILE = 'market-gaps-v1'
REQUEST_LIMIT = 12
MARKETS = ('sz','sh','bj')


def market_of(code):
    if re.fullmatch(r'(?:[48]\d{5}|920\d{3})',code): return 'bj'
    if re.fullmatch(r'[69]\d{5}',code): return 'sh'
    if re.fullmatch(r'[023]\d{5}',code): return 'sz'
    return None


def identity(doc): return doc['id'],doc['thscode'].split('.')[0]


def merge(documents, doc):
    key=identity(doc);previous=documents.get(key)
    if previous and any(previous[k]!=doc[k]for k in ('title','notice_date','url','name')):
        raise DataError('分段查询与已核验公告身份内容冲突。',reason='invalid_snapshot')
    documents.setdefault(key,doc)


def fill_segments(folder, factory, documents, excluded, targets, notice_day, base_total, *, collect):
    """Reuse base evidence. Discover market totals, then batch only duplicate-boundary issuers.

    Each result must independently pass date, URL, issuer and market scope checks.
    Market totals must sum to the base total before count reconciliation is claimed.
    """
    collector=factory(folder/PROFILE,max_requests=REQUEST_LIMIT)
    added_before=len(documents);coverage=[];totals={};failures=False;did_fetch=False
    base_query=AnnouncementClues.query(notice_day,'all',1)

    def counts(market):
        return sum(market_of(code)==market for _,code in documents)+sum(market_of(code)==market for _,code in excluded)

    def query(params, market, codes=None):
        nonlocal did_fetch,failures
        body=urlencode(params)
        record=next((r for r in collector.data['requests'] if r.get('url')==INDEX and r.get('request_body_utf8')==body),None)
        label='分段 '+market if codes is None else '定向分段 '+','.join(sorted(codes))
        if record is None:
            if not collect:
                coverage.append(dict(family=label,received=0,total=None,complete=False,warning='本项尚未采集'))
                failures=True;return None
            did_fetch=True
            record=collector.fetch(INDEX,method='POST',data=body,name=label,
                headers={'Referer':'https://www.cninfo.com.cn/'},max_bytes=MAX_BYTES)
        try:
            if record.get('stop')=='budget_exhausted':
                raise DataError('分段补查已达12次上限，本项尚未采集。',reason='budget_exhausted')
            payload=AnnouncementClues.payload(collector.folder,record,body)
            rows,total=payload.get('announcements'),payload.get('totalAnnouncement')
            if rows is None and total==0:rows=[]
            if not isinstance(rows,list) or type(total)is not int or total<0:
                raise DataError('分段查询格式无效。',reason='invalid_snapshot')
            page_docs={};page_excluded=set();bad=0
            for row in rows:
                try:doc=normalize_notice(row,notice_day)
                except ValueError:
                    # Exclusions also need a valid date, identity and original URL.
                    if not isinstance(row,dict) or not re.fullmatch(r'\d{6}',str(row.get('secCode',''))):bad+=1;continue
                    code=row['secCode']
                    try:normalize_notice({**row,'secCode':'600000'},notice_day)
                    except ValueError:bad+=1;continue
                    # Never turn a rejected A-share record into an out-of-scope exclusion.
                    if code[0]in '03648' or code.startswith('920'):bad+=1;continue
                    if market_of(code)!=market or (codes is not None and code not in codes):
                        raise DataError('分段查询的范围外证券不符合查询市场或股票范围。',reason='invalid_snapshot')
                    page_excluded.add((str(row['announcementId']),code));continue
                code=doc['thscode'].split('.')[0]
                if market_of(code)!=market or (codes is not None and code not in codes):
                    raise DataError('分段参数未生效，返回其他市场或股票，未采用。',reason='invalid_snapshot')
                doc.update(index_sha256=record['sha256'],index_fetched_at=record.get('fetched_at'),query_family=label)
                merge(page_docs,doc)
            if len(page_docs)+len(page_excluded)>total:
                raise DataError('分段唯一条数超过声明总量。',reason='invalid_snapshot')
            for doc in page_docs.values():merge(documents,doc)
            excluded.update(page_excluded)
            complete=bad==0 and len(page_docs)+len(page_excluded)==len(rows)==total
            coverage.append(dict(family=label,received=len(page_docs)+len(page_excluded),total=total,complete=complete,
                warning='' if complete else '本页只是分段样本，仍需与已有证据合并核对'+(f'；排除日期或身份无效 {bad} 条' if bad else '')))
            return total,bad
        except (OSError,ValueError,TypeError,DataError)as exc:
            if isinstance(exc,DataError)and exc.reason=='invalid_snapshot':raise
            failures=True
            coverage.append(dict(family=label,received=0,total=None,complete=False,warning=str(exc)))
            return None

    for market in MARKETS:
        params={**base_query,'plate':market,'sortType':'desc'}
        result=query(params,market)
        if result is not None:
            totals[market]=result[0]
            if result[1]:failures=True
    # First-fit batches use known issuer sizes plus one slot for a boundary omission.
    # This is only a planning estimate. A response larger than one page remains incomplete.
    issuer_counts=Counter(code for _,code in documents)
    for market in MARKETS:
        if market not in totals or counts(market)>=totals[market]:continue
        batches=[]
        for code,org in sorted(targets):
            if market_of(code)!=market:continue
            size=issuer_counts[code]+1
            batch=next((b for b in batches if b[1]+size<=30),None)
            if batch:batch[0].append((code,org));batch[1]+=size
            else:batches.append([[(code,org)],size])
        for issuers,_ in batches:
            if counts(market)>=totals[market]:break
            params={**base_query,'plate':market,'stock':';'.join(code+','+org for code,org in issuers)}
            result=query(params,market,{code for code,_ in issuers})
            if result is not None and result[1]:failures=True
    # One extra reverse page for an unresolved market boundary, never an unbounded scan.
    for market in MARKETS:
        if market not in totals or counts(market)>=totals[market]:continue
        result=query({**base_query,'plate':market,'sortType':'desc','pageNum':2},market)
        if result is not None and result[0]!=totals[market]:
            failures=True
            coverage[-1]['warning']='市场分段总量变化，缺口保留。'
    market_counts={m:counts(m)for m in MARKETS}
    totals_agree=len(totals)==3 and sum(totals.values())==base_total
    reconciled=totals_agree and not failures and all(market_counts[m]==totals[m]for m in MARKETS)
    if totals_agree is False:
        warning='市场分段总量与原索引不一致，未推定补齐。'
    elif not reconciled:warning='分段仍有未取得或未核验记录，缺口保留。'
    else:warning='市场分段总量与原索引相符，已有证据和补查合并后条数已对齐。'
    coverage.append(dict(family='分段合并',received=sum(market_counts.values()),total=base_total,complete=reconciled,warning=warning))
    return dict(added=len(documents)-added_before,reconciled=reconciled,coverage=coverage,
        did_fetch=did_fetch,requests=len(collector.data['requests']),market_totals=totals,market_counts=market_counts)
