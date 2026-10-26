"""Read-only, locally verified official disclosure materials; no upstream or financial-value calls."""
import datetime as dt
import gzip
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs

TZ=dt.timezone(dt.timedelta(hours=8))
RULE='日期型披露按次日 00:00（北京时间）保守可用；不假定当日盘前可知。'
SCOPE='仅覆盖本机已核验资料，不是实时或完整公告库；原文为核验抓取版本，不保证还原历史当天文件内容。'


def annual_identity(title):
    """Recognize full Chinese annual reports and their notices, not related opinions/abstracts."""
    text=html.unescape(re.sub('<[^>]+>','',title)).strip()
    if any(word in text for word in ('摘要','英文','问询','审计','意见','取消')):return None
    match=re.search(r'(20\d{2})年?年度报告(?:全文)?(?:[（(](修订版|修订稿|修订后|更新版|更新后|更正后|更正版)[）)])?$',text)
    if match:return match[1], 'revised_report' if match[2] else 'annual_report'
    match=re.search(r'(20\d{2})年?年度报告.*(?:更正|补充|修订).*公告$',text)
    if match:return match[1], 'correction_notice'
    return None


def date_value(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):return None
    try:return dt.date.fromisoformat(value)
    except ValueError:return None


def available_at(value):
    day=date_value(value)
    try:return dt.datetime.combine(day+dt.timedelta(days=1),dt.time(),tzinfo=TZ).isoformat() if day else None
    except OverflowError:return None


def asof_value(value):
    if date_value(value):return dt.datetime.combine(date_value(value),dt.time(23,59,59),tzinfo=TZ)
    try:
        result=dt.datetime.fromisoformat(value)
        return result if result.tzinfo is not None else None
    except (ValueError,TypeError):return None


def materials_asof(items,stock_code,period_end,asof):
    at=asof_value(asof)
    if at is None or date_value(period_end) is None:return {'status':'invalid','base':None,'corrections':[]}
    relevant=[x for x in items if x.get('stock_code')==stock_code and x.get('period_end')==period_end]
    visible=[x for x in relevant if x.get('integrity')=='match' and asof_value(x.get('available_at'))
             and asof_value(x['available_at'])<=at]
    bases=[x for x in visible if x['document_kind'] in ('annual_report','revised_report')]
    bases.sort(key=lambda x:(asof_value(x['available_at']),x['document_kind']=='revised_report',str(x['id'])))
    base=bases[-1] if bases else None
    corrections=[x for x in visible if x['document_kind']=='correction_notice' and base
                 and asof_value(x['available_at'])>=asof_value(base['available_at'])]
    return {'status':'available' if base else 'unavailable','base':base,'corrections':corrections,
            'unverified_dates':sum(not x.get('available_at') for x in relevant),
            'note':'Material selection only; correction notices do not replace full reports or create PIT financial values.'}


def report_period(value):
    if re.fullmatch(r'20\d{2}-[1-4]',value or ''):
        year,quarter=value.split('-');return year+'-'+{'1':'03-31','2':'06-30','3':'09-30','4':'12-31'}[quarter]
    if date_value(value):return value
    raise ValueError('报告期无效')


def empty_snapshot(status,code,day,period):
    notes={'unconfigured':'本机尚未导入已核验披露资料。','uncovered':'该股票尚未纳入本机已核验披露资料。',
           'period_not_covered':'该报告期尚未纳入本机已核验披露资料。',
           'not_yet_available':'截至观察日，本机尚无可用的已核验披露材料。',
           'failed':'披露资料校验未通过，暂不展示；其他分析仍可使用。'}
    return {'schema_version':'official-disclosures-1','status':status,'code':code,'date':day,'period_end':period,
            'items':[],'versions':[],'rule':RULE,'scope':SCOPE,'note':notes.get(status,''),'financial_values':None}


class DisclosureStore:
    def __init__(self,folder):self.folder=Path(folder)

    def _file(self,relative,pattern):
        if not isinstance(relative,str) or not re.fullmatch(pattern,relative):raise ValueError('invalid bundle path')
        path=self.folder/relative
        if not path.resolve().is_relative_to(self.folder.resolve()):raise ValueError('bundle path escapes folder')
        return path

    @staticmethod
    def _sha(body):return hashlib.sha256(body).hexdigest()

    def _read(self):
        bundle=json.loads((self.folder/'catalog.json').read_text())
        if bundle.get('schema_version')!='official-disclosures-1' or bundle.get('sample_gate',{}).get('status')!='pass':
            raise ValueError('unverified bundle')
        proofs={};markets={}
        for digest,proof in bundle['index_evidence'].items():
            raw=self._file(proof['path'],r'evidence/[0-9a-f]{64}\.bin').read_bytes()
            if self._sha(raw)!=digest or proof['sha256']!=digest:raise ValueError('index SHA mismatch')
            if proof['url']!='https://www.cninfo.com.cn/new/hisAnnouncement/query':raise ValueError('index source mismatch')
            payload=json.loads(gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw)
            rows=payload.get('announcements') or []
            if not rows or payload.get('totalAnnouncement',0)>len(rows):raise ValueError('incomplete index')
            params=parse_qs(proof['request_body_utf8'])
            expected=params['stock'][0].split(',')[0]
            if any(x['secCode']!=expected for x in rows):raise ValueError('index query/stock mismatch')
            markets[digest]={'sse':'SH','szse':'SZ'}[params['column'][0]]
            proofs[digest]={str(x['announcementId']):x for x in rows}
        documents=bundle['documents'];ids=set()
        for doc in documents:
            identifier=doc['id']
            if identifier in ids or not re.fullmatch(r'\d+',identifier):raise ValueError('duplicate document identity')
            ids.add(identifier)
            raw=self._file(doc['pdf_path'],r'documents/\d+\.pdf').read_bytes()
            if self._sha(raw)!=doc['sha256'] or not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-2048:]:raise ValueError('PDF integrity failed')
            row=proofs[doc['index_sha256']][identifier]
            if doc['stock_code']!=row['secCode'] or doc['url']!='https://static.cninfo.com.cn/'+row['adjunctUrl']:
                raise ValueError('document/index identity mismatch')
            stamp=row['announcementTime']
            if not isinstance(stamp,int) or isinstance(stamp,bool):raise ValueError('bad timestamp')
            notice=dt.datetime.fromtimestamp(stamp/1000,TZ).date().isoformat()
            if doc['publication_timestamp_raw']!=stamp or doc['notice_date']!=notice or doc['available_at']!=available_at(notice):
                raise ValueError('date evidence mismatch')
            if not doc['identity_verified'] or doc['integrity']!='match' or doc['published_precision']!='date' or doc.get('financial_values') is not None:
                raise ValueError('unsupported data semantics')
            title=html.unescape(re.sub('<[^>]+>','',row['announcementTitle']))
            identity=annual_identity(title)
            if not identity or doc['period_end']!=identity[0]+'-12-31' or doc['document_kind']!=identity[1] or doc['title']!=title or doc['stock_name']!=row['secName']:
                raise ValueError('period or version kind mismatch')
            if doc['exchange']!=markets[doc['index_sha256']] or asof_value(doc['fetched_at']) is None or asof_value(doc['index_fetched_at']) is None:
                raise ValueError('missing provenance')
        for doc in documents:
            if doc['document_kind']!='annual_report':
                previous=next((x for x in documents if x['id']==doc.get('previous_report_id')),None)
                if not previous or previous['document_kind'] not in ('annual_report','revised_report') or previous['stock_code']!=doc['stock_code'] or previous['period_end']!=doc['period_end'] or previous['notice_date']>=doc['notice_date']:
                    raise ValueError('orphan or cross-stock revision')
        bases={(x['stock_code'],x['period_end']) for x in documents if x['document_kind']=='annual_report'}
        if len({code for code,p in bases if sum(c==code for c,period in bases)>=2})<2:
            raise ValueError('sample gate missing stock/period coverage')
        counts={'stocks':len({code for code,p in bases}),'original_stock_periods':len(bases),'verified_pdfs':len(documents),
                'revised_reports':sum(x['document_kind']=='revised_report' for x in documents),
                'correction_notices':sum(x['document_kind']=='correction_notice' for x in documents)}
        if not counts['revised_reports'] or any(bundle['sample_gate'].get(k)!=v for k,v in counts.items()):
            raise ValueError('sample gate counts do not match evidence')
        return bundle

    def query(self,code,day,report):
        if not isinstance(code,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code) or not date_value(day):raise ValueError('股票或观察日无效')
        period=report_period(report)
        if not (self.folder/'catalog.json').exists():return empty_snapshot('unconfigured',code,day,period)
        try:bundle=self._read()
        except (OSError,ValueError,KeyError,TypeError,OverflowError):return empty_snapshot('failed',code,day,period)
        documents=[x for x in bundle['documents'] if x['stock_code']+'.'+x['exchange']==code]
        if not documents:return empty_snapshot('uncovered',code,day,period)
        relevant=[x for x in documents if x['period_end']==period]
        if not relevant:return empty_snapshot('period_not_covered',code,day,period)
        selected=materials_asof(relevant,code[:6],period,day)
        if not selected['base']:return empty_snapshot('not_yet_available',code,day,period)
        result=empty_snapshot('available',code,day,period)
        public=('id','stock_code','stock_name','period_end','title','document_kind','url','notice_date','available_at',
                'fetched_at','index_fetched_at','sha256','published_precision','notice_date_basis')
        def view(doc):return {key:doc[key] for key in public}
        result['items']=[view(selected['base'])]+[view(x) for x in selected['corrections']]
        visible=[x for x in relevant if asof_value(x['available_at'])<=asof_value(day)]
        result['versions']=[view(x) for x in visible if x['document_kind']!='correction_notice']
        result['note']='已按观察日筛选；修订版只在其保守可用时间后替换原版。'
        return result
