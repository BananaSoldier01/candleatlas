"""Bounded, non-AI clues from dated CNINFO public announcement titles, not price attribution."""
import datetime as dt
import gzip
import io
import json
from pathlib import Path
import re
import threading
from urllib.parse import urlencode

from disclosures import available_at, date_value
from market import DataError, TZ
from news import plain
from scripts.official_collect import Collector, sha

INDEX = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
MAX_BYTES = 4 * 1024 * 1024
PAGE_LIMIT = 50
FAMILIES = {'all': ''}  # No category filter: financial and event titles share one dated index.
PROFILE = 'code-order-v3'
LABELS = {
    'cninfo:report': '公告 · 定期报告', 'cninfo:forecast': '公告 · 业绩预告',
    'cninfo:express': '公告 · 业绩快报', 'cninfo:correction': '公告 · 业绩披露更正',
    'cninfo:repurchase': '公告 · 股份回购相关', 'cninfo:holdings': '公告 · 持股变动相关',
    'cninfo:contract': '公告 · 合同与中标', 'cninfo:assets': '公告 · 并购及资产交易',
    'cninfo:investment': '公告 · 项目投资', 'cninfo:guarantee': '公告 · 担保相关',
}
FINANCE_KEYS = frozenset(('cninfo:report', 'cninfo:forecast', 'cninfo:express', 'cninfo:correction'))
RULE = '只按公告标题归类，不判断利好利空或涨跌原因；日期型公告按次日 00:00（北京时间）保守可用。'


def title_keys(title, name):
    """Conservative title matching; plans/corrections remain visible as original titles."""
    text = re.sub(r'\s+', '', title)
    if any(x in text for x in ('业绩说明会', '业绩网上说明', '解读', '英文', '法律意见', '核查意见')):
        return []
    keys = []
    financial = re.search('业绩预告|业绩快报|季度报告|半年度报告|年度报告', text)
    if financial and re.search('更正|修订|补充', text): keys.append('cninfo:correction')
    elif re.search(r'业绩预告(?:公告)?$', text): keys.append('cninfo:forecast')
    elif re.search(r'业绩快报(?:公告)?$', text): keys.append('cninfo:express')
    else:
        prefix = re.escape(re.sub(r'\s+', '', name))
        if re.fullmatch(r'(?:'+prefix+r'(?:股份有限公司|集团股份有限公司)?[:：]?)?20\d{2}年(?:第?[一二三123]季度|半年度|年度)报告(?:全文|正文|摘要)?', text):
            keys.append('cninfo:report')
    if '回购' in text: keys.append('cninfo:repurchase')
    if re.search('增持|减持|持股变动', text): keys.append('cninfo:holdings')
    if re.search('重大合同|中标|订单|项目合同', text) and not re.search('募集资金|监管协议|担保合同|劳动合同', text): keys.append('cninfo:contract')
    if re.search('收购|重大资产重组|资产出售', text): keys.append('cninfo:assets')
    if re.search('项目投资|投资建设|建设项目|扩建项目', text): keys.append('cninfo:investment')
    if '担保' in text: keys.append('cninfo:guarantee')
    return keys


def normalize_notice(row, notice_day):
    if not isinstance(row, dict): raise ValueError('invalid announcement row')
    code = row.get('secCode', '')
    if not isinstance(code, str): raise ValueError('invalid stock code')
    suffix = 'SH' if re.fullmatch(r'6\d{5}', code) else 'SZ' if re.fullmatch(r'[03]\d{5}', code) else 'BJ' if re.fullmatch(r'(?:[48]\d{5}|920\d{3})', code) else None
    if suffix is None: raise ValueError('not a supported A-share code')
    identifier = str(row.get('announcementId', ''))
    if not re.fullmatch(r'\d{6,20}', identifier): raise ValueError('invalid announcement id')
    stamp = row.get('announcementTime')
    if not isinstance(stamp, int) or isinstance(stamp, bool): raise ValueError('invalid announcement date')
    try: date = dt.datetime.fromtimestamp(stamp/1000, TZ).date().isoformat()
    except (OverflowError, OSError, ValueError): raise ValueError('invalid announcement date') from None
    if date != notice_day: raise ValueError('announcement date outside requested day')
    path = row.get('adjunctUrl', '')
    if not isinstance(path, str) or not re.fullmatch(r'finalpage/'+date+'/'+identifier+r'\.[pP][dD][fF]', path):
        raise ValueError('announcement URL/date/id mismatch')
    title, name = plain(row.get('announcementTitle')), plain(row.get('secName'))
    if not 2 <= len(title) <= 400 or not 1 <= len(name) <= 60: raise ValueError('invalid title or issuer name')
    return dict(id=identifier, thscode=code+'.'+suffix, name=name, title=title,
                notice_date=date, available_at=available_at(date), timestamp=stamp,
                url='https://static.cninfo.com.cn/'+path, source='巨潮资讯公告索引',
                keys=title_keys(title, name))


class AnnouncementClues:
    def __init__(self, directory, collector_factory=Collector):
        self.directory = Path(directory)
        self.factory = collector_factory
        self.lock = threading.RLock()

    @staticmethod
    def query(day, family, page):
        return dict(pageNum=page, pageSize=30, column='szse', tabName='fulltext', stock='', searchkey='',
                    secid='', trade='', plate='sz;sh;bj', category=FAMILIES[family],
                    seDate=day+'~'+day, sortName='code', sortType='asc', isHLtitle='false')

    @staticmethod
    def payload(folder, record, body):
        if record.get('stop')=='budget_exhausted':
            raise DataError('已达该观察日50次请求上限，本项尚未采集，缺口保留。',reason='budget_exhausted')
        if record.get('stop')=='access_or_rate_limit':
            raise DataError('来源拒绝访问或限流，后续查询已停止，缺口保留。',reason='source_failed')
        if record.get('stop')=='repeated_source_failure':
            raise DataError('来源连续失败，后续查询已停止，缺口保留。',reason='source_failed')
        if (not record.get('ok') or record.get('raw_complete') is not True or record.get('url') != INDEX
                or record.get('method') != 'POST' or record.get('request_body_utf8') != body):
            raise DataError('巨潮公告查询失败或证据不完整，未生成补充线索。', reason='source_failed')
        raw_path = record.get('raw', '')
        if not re.fullmatch(r'raw/\d{3}\.bin', raw_path): raise DataError('公告证据路径无效。', reason='invalid_snapshot')
        raw = (folder/raw_path).read_bytes()
        if sha(raw) != record.get('sha256'): raise DataError('公告原始响应 SHA256 校验失败。', reason='invalid_snapshot')
        decoded = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES+1) if raw.startswith(b'\x1f\x8b') else raw
        if len(decoded) > MAX_BYTES: raise DataError('公告响应超出长度限制。', reason='invalid_snapshot')
        result = json.loads(decoded)
        if not isinstance(result, dict): raise DataError('公告响应格式无效。', reason='invalid_snapshot')
        return result

    def read(self, day):
        with self.lock:
            if not date_value(day): raise DataError('公告观察日无效。')
            if not any((self.directory/day/p).exists() for p in ('verified-backfill-v1/package.json',PROFILE+'/ledger.json','all-categories-v2/ledger.json','ledger.json')): return None
            return self._build(day, collect=False)

    def get(self, day):
        with self.lock:
            return self._build(day, collect=True)

    def legacy_documents(self, day, notice_day):
        """Replay the previous bounded category snapshot; never refetch or reset its budget."""
        result = []
        categories = ('category_yjyg_szsh;category_yjkb_szsh;category_sjdbg_szsh;',
                      'category_rcjy_szsh;category_gqbd_szsh;')
        for profile, filters, limit in (('',categories,3),('all-categories-v2',('',),50)):
            folder = self.directory/day/profile
            if not (folder/'ledger.json').exists(): continue
            ledger = json.loads((folder/'ledger.json').read_text())
            bodies = set()
            for category in filters:
                for page in range(1,limit+1):
                    query = self.query(notice_day,'all',page)
                    query.update(category=category,sortName='time',sortType='desc')
                    bodies.add(urlencode(query))
            for record in ledger['requests']:
                body = record.get('request_body_utf8')
                if body not in bodies or not record.get('ok'): continue
                payload = self.payload(folder,record,body)
                rows = payload.get('announcements')
                if not isinstance(rows,list): raise DataError('旧公告证据格式无效。',reason='invalid_snapshot')
                for row in rows:
                    try: document = normalize_notice(row,notice_day)
                    except ValueError: continue
                    if document['available_at'][:10] > day: continue
                    document.update(index_sha256=record['sha256'],query_family='legacy',index_fetched_at=record.get('fetched_at'))
                    result.append(document)
        return result

    def repair_duplicates(self, collector, notice_day, targets, collect):
        """One dated issuer query per duplicate boundary, within the SAME durable budget.

        Large issuers remain partial: another unstable multi-page scan is not proof.
        """
        documents, coverage, fetched = [], [], False
        for code, org in sorted(targets):
            query = self.query(notice_day,'all',1); query['stock'] = code+','+org
            body = urlencode(query)
            record = next((r for r in collector.data['requests'] if r.get('url')==INDEX and r.get('request_body_utf8')==body),None)
            if record is None:
                if not collect: continue
                fetched = True
                record = collector.fetch(INDEX,method='POST',data=body,name='issuer-'+code,
                    headers={'Referer':'https://www.cninfo.com.cn/'},max_bytes=MAX_BYTES)
            try:
                payload = self.payload(collector.folder,record,body)
                rows, total = payload.get('announcements'),payload.get('totalAnnouncement')
                if not isinstance(rows,list) or type(total) is not int or total<0:
                    raise DataError('股票定向查询格式无效。',reason='invalid_snapshot')
                seen = {}
                for row in rows:
                    try: doc = normalize_notice(row,notice_day)
                    except ValueError: continue
                    if doc['thscode'].split('.')[0]!=code:
                        raise DataError('股票定向查询返回其他股票，未采用。',reason='invalid_snapshot')
                    if doc['id'] in seen and seen[doc['id']]['title']!=doc['title']:
                        raise DataError('股票定向查询同一公告内容冲突。',reason='invalid_snapshot')
                    doc.update(index_sha256=record['sha256'],index_fetched_at=record.get('fetched_at'),query_family='issuer:'+code)
                    seen[doc['id']] = doc
                if len(seen)>total: raise DataError('股票定向查询条数超过总量。',reason='invalid_snapshot')
                documents.extend(seen.values())
                complete = len(seen)==len(rows)==total
                coverage.append(dict(family='issuer:'+code,received=len(seen),total=total,complete=complete,
                    warning='' if complete else '单股定向查询未完整，未继续用不稳定分页推定补齐'))
            except (OSError,ValueError,TypeError,DataError) as exc:
                if isinstance(exc,DataError) and exc.reason=='invalid_snapshot': raise
                coverage.append(dict(family='issuer:'+code,received=0,total=None,complete=False,warning=str(exc)))
        return documents, coverage, fetched

    def _build(self, day, *, collect):
        parsed = date_value(day)
        if not parsed or parsed > dt.datetime.now(TZ).date(): raise DataError('公告观察日无效。')
        backfill=self.directory/day/'verified-backfill-v1'
        if (backfill/'package.json').exists():
            from announcement_backfill import load
            return load(backfill,day)
        notice_day = (parsed-dt.timedelta(days=1)).isoformat()
        folder = self.directory/day/PROFILE
        collector = self.factory(folder, max_requests=PAGE_LIMIT)
        documents, coverage, fetched, did_fetch = {}, [], [], False
        targets, excluded = set(), set()
        for family in FAMILIES:
            total, received, rejected, duplicates, date_rejected, pages, seen, failure = None, 0, 0, 0, 0, 0, set(), ''
            page_signatures = set()
            scanned = 0
            stop = 'page_limit'
            for page in range(1, PAGE_LIMIT+1):
                body = urlencode(self.query(notice_day, family, page))
                record = next((r for r in collector.data['requests'] if r.get('request_body_utf8') == body and r.get('url') == INDEX), None)
                if record is None:
                    if not collect:
                        stop = 'not_collected'; break
                    did_fetch = True
                    record = collector.fetch(INDEX, method='POST', data=body,
                        headers={'Referer':'https://www.cninfo.com.cn/','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},
                        name=family+'-'+str(page), max_bytes=MAX_BYTES)
                try:
                    payload = self.payload(folder, record, body)
                    rows, count = payload.get('announcements'), payload.get('totalAnnouncement')
                    if rows is None and count == 0: rows = []
                    if not isinstance(rows, list) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        raise DataError('公告分页格式无效。', reason='invalid_snapshot')
                    if total is not None and count != total: raise DataError('公告分页总量发生变化，覆盖不完整。', reason='incomplete')
                    total = count; pages += 1
                    scanned += len(rows)
                    signature = tuple(sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows))
                    repeated_page = bool(rows) and signature in page_signatures
                    page_signatures.add(signature)
                    if not rows and count > received: raise DataError('公告分页为空，覆盖不完整。', reason='incomplete')
                    for row in rows:
                        identity = (str(row.get('announcementId')), str(row.get('secCode'))) if isinstance(row,dict) else None
                        try: document = normalize_notice(row, notice_day)
                        except ValueError as exc:
                            rejected += 1
                            if str(exc)=='not a supported A-share code' and isinstance(row,dict) and re.fullmatch(r'\d{6}',str(row.get('secCode',''))):
                                try: normalize_notice({**row,'secCode':'600000'},notice_day)
                                except ValueError: pass
                                else: excluded.add(identity)
                            if 'outside requested day' in str(exc): date_rejected += 1
                            continue
                        if document['available_at'][:10] > day: rejected += 1; continue
                        document['index_sha256'] = record['sha256']
                        document['query_family'] = family
                        previous = documents.get(identity)
                        if previous and any(previous[k] != document[k] for k in ('title','notice_date','url','name')):
                            raise DataError('同一公告身份对应不同内容，未使用冲突版本。', reason='invalid_snapshot')
                        if identity in seen:
                            duplicates += 1
                            org = row.get('orgId')
                            if isinstance(org,str) and re.fullmatch(r'[A-Za-z0-9]{1,40}',org): targets.add((row['secCode'],org))
                            continue
                        seen.add(identity); received += 1
                        documents[identity] = document
                    fetched.append(record.get('fetched_at'))
                    if received > count: raise DataError('公告条数超过上游总量，覆盖不可信。', reason='invalid_snapshot')
                    if received == count:
                        stop = 'unique_total'; break
                    if repeated_page:
                        failure = '整页重复，停止翻页，未推定缺失公告'; stop = 'repeated_page'; break
                    if scanned >= count:
                        stop = 'declared_end'; break
                except (OSError, ValueError, TypeError, DataError) as exc:
                    if isinstance(exc, DataError) and exc.reason == 'invalid_snapshot': raise
                    failure = str(exc); stop = 'source_failure'; break
            if stop == 'page_limit': failure = '达到50页上限，剩余未采集'
            if duplicates: failure += ('；' if failure else '')+f'分页重复 {duplicates} 条，已去重，覆盖仍未完整核验'
            coverage.append(dict(family=family, received=received, total=total, rejected=rejected, date_rejected=date_rejected, duplicates=duplicates, pages=pages, scanned=scanned, stop=stop,
                complete=total is not None and received==total and rejected==0 and duplicates==0 and not failure, warning=failure))
        repaired, repair_coverage, repair_fetch = self.repair_duplicates(collector,notice_day,targets,collect)
        did_fetch = did_fetch or repair_fetch
        repair_added = 0
        for document in repaired:
            identity = (document['id'],document['thscode'].split('.')[0])
            previous = documents.get(identity)
            if previous and any(previous[k]!=document[k] for k in ('title','notice_date','url','name')):
                raise DataError('定向查询与原公告身份内容冲突。',reason='invalid_snapshot')
            if previous is None: documents[identity]=document; repair_added+=1
        coverage.extend(repair_coverage)
        legacy_added = 0
        for document in self.legacy_documents(day,notice_day):
            identity = (document['id'],document['thscode'].split('.')[0])
            previous = documents.get(identity)
            if previous and any(previous[k] != document[k] for k in ('title','notice_date','url','name')):
                raise DataError('新旧公告证据身份冲突，未使用冲突版本。',reason='invalid_snapshot')
            if previous is None:
                documents[identity] = document; legacy_added += 1
        segment = None
        if coverage[0]['stop']=='page_limit' and coverage[0]['total'] is not None:
            from announcement_segments import fill_segments
            segment=fill_segments(self.directory/day,self.factory,documents,excluded,targets,notice_day,coverage[0]['total'],collect=collect)
            did_fetch=did_fetch or segment['did_fetch']
            coverage.extend(segment['coverage'])
        usable = [d for d in documents.values() if d['keys']]
        if not usable:
            if any(c.get('date_rejected',0) for c in coverage):
                raise DataError('公告数据日期不符：没有符合查询公告日 '+notice_day+' 的可用样本，未使用其他日期替代。', reason='date_mismatch')
            if documents:raise DataError('已读取的公告标题没有匹配的事件规则；不代表没有相关事件。', reason='no_matching_evidence')
            if any(c['warning'] for c in coverage):raise DataError('公告查询失败或分页未完成，暂无可核验样本；未把请求失败视为空事件。',reason='source_failed')
            if any(c.get('rejected',0) for c in coverage):raise DataError('公告身份或链接核验未通过，暂无可用样本。',reason='invalid_snapshot')
            raise DataError('公告补充暂无可核验样本，上游为空或查询失败；不据此认定没有事件。', reason='upstream_empty')
        merged = {}
        for document in usable:
            row = merged.setdefault(document['thscode'], dict(thscode=document['thscode'], stock_name=document['name'],
                keyword_list=[], tag_name='公告标题归类', analysis_content='', evidence=[]))
            row['keyword_list'] = sorted(set(row['keyword_list']) | set(document['keys']))
            row['evidence'].append(document)
        limited = not all(c['complete'] for c in coverage)
        reconciled = (coverage[0]['stop'] in ('declared_end','unique_total') and coverage[0]['total']==len(documents)+len(excluded) and all(c['complete'] for c in repair_coverage))
        if segment is not None:reconciled=segment['reconciled']
        return dict(source_kind='cninfo', snapshot_source='upstream' if did_fetch else 'local', date=day, notice_day=notice_day,
            timestamp=max(d['timestamp'] for d in usable), fetched_at=max([x for x in fetched if x]+[d['index_fetched_at'] for d in documents.values() if d.get('index_fetched_at')], default=None),
            item=list(merged.values()), coverage=coverage, limited=limited, legacy_added=legacy_added,
            unique_verified=len(documents), repair_added=repair_added, excluded_non_a=len(excluded),
            pagination_reconciled=reconciled,segment_repair=segment,
            note=RULE+(' 本次查询条数已对齐（有效A股＋范围外证券＝上游总量），不代表全市场事件完整。' if reconciled else ' 本次查询条数仍未对齐，不推定补齐。')+f' 重复边界按股票定向核验补入 {repair_added} 条，范围外证券排除 {len(excluded)} 条。'+f' 已核验旧查询证据额外补入 {legacy_added} 条，联合去重后 {len(documents)} 条；不累加不同查询的总量。'+ (f' 市场分段补查本次额外补入 {segment["added"]} 条，共使用 {segment["requests"]}/12 次追加请求；原主查询账本保留。' if segment else '')+ ' 按证券代码升序查询前一自然日全部公告类别（同一股票内部次序仍不保证稳定），主查询及普通定向补查最多50次请求；高量日分段补查另最多12次（每页30条）；按公告ID和证券代码去重，标题未命中规则的记录不强行归类。不是全市场事件库。当前查询的历史索引不保证还原当日网页版本；未解析 PDF 财务数值。')
