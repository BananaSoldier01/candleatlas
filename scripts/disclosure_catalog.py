"""Offline official-document metadata and conservative material visibility; no financial values."""
import gzip
import json
from pathlib import Path
import re
import subprocess
from scripts.official_collect import Collector, sha

from disclosures import date_value, available_at, asof_value, materials_asof


def metadata(text,url):
    compact=re.sub(r'\s+','',text);head=compact[:450]
    code=re.search(r'(?:证券代码|公司代码)[:：](\d{6})',head)
    year=re.search(r'(20\d{2})年年度报告',head)
    path_date=re.search(r'/((?:20\d{2})-\d{2}-\d{2})/',url)
    archive=path_date[1] if path_date else None
    correction='更正公告' in head
    result={'stock_code':code[1] if code else None,'period_end':year[1]+'-12-31' if year else None,
            'document_kind':'correction_notice' if correction else 'annual_report',
            'archive_date':archive,'notice_date':None,'notice_date_basis':'unverified_archive_date_only',
            'available_at':None,'financial_values':None}
    if correction:
        dates=re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日',compact)
        board_date='-'.join((dates[-1][0],dates[-1][1].zfill(2),dates[-1][2].zfill(2))) if dates else None
        if board_date==archive:
            result.update(notice_date=archive,notice_date_basis='document_date_matches_official_archive')
        reference=re.search(r'于(20\d{2})年(\d{1,2})月(\d{1,2})日.{0,100}?披露',compact)
        if reference:
            result['original_notice_date']='-'.join((reference[1],reference[2].zfill(2),reference[3].zfill(2)))
        result['has_before_after']='更正前' in compact and '更正后' in compact
    return result


def build(folder):
    folder=Path(folder);collector=Collector(folder);integrity=collector.replay();documents=[];rejected=[]
    for rec in collector.data['requests']:
        path=folder/rec.get('raw','missing')
        if not rec.get('ok') or rec.get('result') in ('response_too_large','decoded_response_too_large') or not path.is_file():
            rejected.append({'id':rec['id'],'reason':rec['result']});continue
        body=path.read_bytes()
        if sha(body)!=rec.get('sha256'):
            rejected.append({'id':rec['id'],'reason':'sha256_mismatch'});continue
        if body.startswith(b'\x1f\x8b'): body=gzip.decompress(body)
        if not body.startswith(b'%PDF-') or b'%%EOF' not in body[-2048:]:
            rejected.append({'id':rec['id'],'reason':'not_complete_pdf'});continue
        # Poppler extracts the frozen original; no re-fetch or inferred financial values.
        result=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,text=True,check=True)
        doc={**metadata(result.stdout,rec['url']),'id':rec['id'],'url':rec['url'],
             'raw':rec['raw'],'sha256':rec['sha256'],'fetched_at':rec['fetched_at'],'integrity':'match',
             'excerpt':result.stdout[:500]}
        if not doc['stock_code'] or not doc['period_end']:
            rejected.append({'id':rec['id'],'reason':'missing_issuer_or_period'});continue
        documents.append(doc)
        (folder/f"text-{rec['id']:03}.txt").write_text(result.stdout)
    for doc in documents:
        if doc['document_kind']=='annual_report':
            supporting=[x for x in documents if x['document_kind']=='correction_notice' and
                (x['stock_code'],x['period_end'],x.get('original_notice_date'))==
                (doc['stock_code'],doc['period_end'],doc['archive_date'])]
            if supporting: doc.update(notice_date=doc['archive_date'],notice_date_basis='original_disclosure_referenced_in_correction',date_evidence_id=supporting[0]['id'])
        doc['available_at']=available_at(doc['notice_date'])
    periods={(x['stock_code'],x['period_end']) for x in documents if x['document_kind']=='annual_report'}
    qualified_stocks={code for code,period in periods if sum(stock==code for stock,other in periods)>=2}
    date_missing=sum(not x['available_at'] for x in documents)
    complete=len(qualified_stocks)>=2 and not date_missing and integrity['status']=='pass'
    status='failed' if integrity['status']=='failed' else 'pass' if complete else 'incomplete' if documents else 'unverified'
    return {'status':status,'documents':documents,'rejected':rejected,'integrity':integrity,
            'annual_stock_periods':[list(x) for x in sorted(periods)],
            'verified_date_count':sum(bool(x['available_at']) for x in documents),
            'date_total':len(documents),'date_missing':date_missing,
            'two_stocks_two_periods':len(qualified_stocks)>=2,
            'real_correction_pair':any(x['document_kind']=='correction_notice' and x.get('has_before_after') and
                any(base.get('date_evidence_id')==x['id'] for base in documents) for x in documents),
            'note':'Metadata and disclosure materials only; no numeric financial PIT or long-history source integration.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--folder',required=True);args=parser.parse_args()
    report=build(args.folder);path=Path(args.folder)/'catalog.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('CATALOG',len(report['documents']),'documents;',len(report['annual_stock_periods']),'annual stock-periods;',report['status'])
    raise SystemExit(0 if report['status']=='pass' else 1 if report['status']=='failed' else 2)
