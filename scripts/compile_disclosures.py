"""Compile verified official PDF + announcement-index evidence into a local read-only bundle."""
import argparse
import datetime as dt
import gzip
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs,urlsplit
from scripts.disclosure_catalog import available_at
from scripts.official_collect import sha
from disclosures import annual_identity,DisclosureStore

TZ=dt.timezone(dt.timedelta(hours=8))

def decode(body):return gzip.decompress(body) if body.startswith(b'\x1f\x8b') else body


def cover_text(path):
    with tempfile.TemporaryDirectory(prefix='disclosure-cover-') as temporary:
        output=Path(temporary)/'cover'
        subprocess.run(['pdftoppm','-f','1','-l','1','-scale-to','2400','-singlefile','-png',str(path),str(output)],check=True,capture_output=True)
        if sys.platform=='darwin' and shutil.which('swift'):
            command=['swift','-module-cache-path',str(Path(tempfile.gettempdir())/'guanshi-disclosure-swift-cache'),
                     str(Path(__file__).with_name('disclosure_cover_ocr.swift')),str(output)+'.png']
        else:command=['tesseract',str(output)+'.png','stdout','-l','eng','--psm','11']
        return subprocess.run(command,check=True,capture_output=True,text=True,timeout=120).stdout


def verify_pdf_identity(text,code,name,year,*,ocr=None):
    compact=re.sub(r'\s+','',text)
    match=re.search(r'(?:证券代码|公司代码|股票代码)[:：]?(\d{6})',compact[:20000]);basis='explicit_code_label'
    if not match:
        match=re.search(r'股票代码(?:变更前股票简称)?(?:A股|人民币普通股)(?:上海|深圳)证券交易所'+re.escape(name)+r'(\d{6})(?!\d)',compact[:20000])
        basis='company_share_listing_table'
    if not match or match[1]!=code or name not in compact[:20000]:raise ValueError('PDF issuer does not match index')
    title=re.search(r'(20\d{2})年?年度报告',compact[:1000]);period_basis='report_title_text'
    result={'stock_code_basis':basis,'period_basis':period_basis}
    if title:
        if title[1]!=year:raise ValueError('PDF report period does not match index')
    else:
        normalized=re.sub(r'\s+','',ocr or '').upper()
        years=set(re.findall(r'(?<!\d)(20\d{2})(?!\d)',ocr or ''))
        if years!={year} or not any(label in normalized for label in ('ANNUALREPORT','年度报告')):raise ValueError('PDF cover period is not verified')
        result.update(period_basis='cover_ocr_year_and_annual_report',cover_ocr_sha256=sha(ocr.encode()),cover_ocr_text=ocr)
    return result


def compile_bundle(sources,destination,*,base=None,selected_ids=None):
    destination=Path(destination)
    if destination.exists():raise ValueError('destination exists; do not overwrite a verified bundle')
    records=[]
    for source in sources:
        source=Path(source);ledger=json.loads((source/'ledger.json').read_text())
        for record in ledger['requests']:
            if not record.get('ok') or record.get('raw_complete') is False or not record.get('raw'):continue
            body=(source/record['raw']).read_bytes()
            if sha(body)!=record.get('sha256'):raise ValueError('source SHA mismatch')
            records.append((record,body))
    pdfs={r['url']:(r,b) for r,b in records if decode(b).startswith(b'%PDF-') and b'%%EOF' in decode(b)[-2048:]}
    indices=[]
    for record,body in records:
        if urlsplit(record['url']).hostname!='www.cninfo.com.cn' or urlsplit(record['url']).path!='/new/hisAnnouncement/query':continue
        payload=json.loads(decode(body));rows=payload.get('announcements') or []
        expected=parse_qs(record.get('request_body_utf8') or '').get('stock',[''])[0].split(',')[0]
        if not rows or payload.get('totalAnnouncement',0)>len(rows):raise ValueError('empty or incomplete announcement index')
        if any(row.get('secCode')!=expected for row in rows):raise ValueError('announcement stock mismatch')
        indices.append((record,body,rows))
    selected_ids=None if selected_ids is None else set(map(str,selected_ids))
    if selected_ids==set():raise ValueError('empty selection')
    documents=[];proofs={};seen=set();by_id={};selected_seen=set()
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='disclosure-bundle-',dir=destination.parent))
    try:
        (staging/'documents').mkdir();(staging/'evidence').mkdir()
        if base is not None:
            base=Path(base);existing=DisclosureStore(base)._read()
            documents=json.loads(json.dumps(existing['documents']));proofs=json.loads(json.dumps(existing['index_evidence']))
            by_id={doc['id']:doc for doc in documents};seen=set(by_id)
            for doc in documents:shutil.copyfile(base/doc['pdf_path'],staging/doc['pdf_path'])
            for proof in proofs.values():shutil.copyfile(base/proof['path'],staging/proof['path'])
        for index,index_body,rows in indices:
            index_hash=sha(index_body);proof_path=f'evidence/{index_hash}.bin'
            (staging/proof_path).write_bytes(index_body)
            proofs[index_hash]={'path':proof_path,'sha256':index_hash,'url':index['url'],
                'fetched_at':index['fetched_at'],'request_body_utf8':index['request_body_utf8'],
                'request_headers':index['request_headers']}
            for row in rows:
                title=html.unescape(re.sub('<[^>]+>','',row['announcementTitle']))
                identity=annual_identity(title)
                if not identity:continue
                identifier=str(row['announcementId']);url='https://static.cninfo.com.cn/'+row['adjunctUrl']
                if not re.fullmatch(r'\d+',identifier):raise ValueError('invalid announcement identity')
                if selected_ids is not None and identifier not in selected_ids:continue
                selected_seen.add(identifier)
                if identifier in seen:
                    prior=by_id[identifier]
                    if (prior['url'],prior['stock_code'],prior['title'],prior['period_end'],prior['publication_timestamp_raw'])!=(url,row['secCode'],title,identity[0]+'-12-31',row['announcementTime']):
                        raise ValueError('conflicting announcement identity: '+identifier)
                    if url in pdfs and sha(decode(pdfs[url][1]))!=prior['sha256']:raise ValueError('existing PDF bytes changed: '+identifier)
                    continue
                if url not in pdfs:raise ValueError('indexed PDF not frozen: '+identifier)
                pdf_record,pdf_body=pdfs[url];pdf_body=decode(pdf_body)
                filename=f'documents/{identifier}.pdf';path=staging/filename;path.write_bytes(pdf_body)
                text=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,text=True,check=True).stdout
                compact=re.sub(r'\s+','',text)
                ocr=cover_text(path) if not re.search(r'(20\d{2})年?年度报告',compact[:1000]) else None
                try:identity_evidence=verify_pdf_identity(text,row['secCode'],row['secName'],identity[0],ocr=ocr)
                except ValueError as exc:raise ValueError(str(exc)+': '+identifier) from exc
                stamp=row.get('announcementTime')
                if not isinstance(stamp,int) or isinstance(stamp,bool):raise ValueError('bad publication timestamp')
                notice=dt.datetime.fromtimestamp(stamp/1000,TZ).date().isoformat()
                if row['adjunctUrl']!=f'finalpage/{notice}/{identifier}.PDF':raise ValueError('index date/URL mismatch')
                if notice>dt.datetime.fromisoformat(index['fetched_at']).astimezone(TZ).date().isoformat():raise ValueError('future index date')
                documents.append({'id':identifier,'stock_code':row['secCode'],'stock_name':row['secName'],
                    'exchange':{'sse':'SH','szse':'SZ'}[parse_qs(index['request_body_utf8'])['column'][0]],
                    'period_end':identity[0]+'-12-31','title':title,'document_kind':identity[1],'url':url,
                    'notice_date':notice,'published_precision':'date','publication_timestamp_raw':stamp,
                    'notice_date_basis':'cninfo_official_announcement_index','available_at':available_at(notice),
                    'fetched_at':pdf_record['fetched_at'],'index_fetched_at':index['fetched_at'],
                    'pdf_path':filename,'sha256':sha(pdf_body),'index_sha256':index_hash,
                    'integrity':'match','identity_verified':True,'identity_evidence':identity_evidence,'financial_values':None})
                seen.add(identifier)
                by_id[identifier]=documents[-1]
        if selected_ids is not None and selected_seen!=selected_ids:raise ValueError('selected announcement missing from frozen indices')
        documents.sort(key=lambda x:(x['stock_code'],x['period_end'],x['notice_date'],x['document_kind']))
        for doc in documents:
            earlier=[x for x in documents if x['stock_code']==doc['stock_code'] and x['period_end']==doc['period_end']
                and x['document_kind'] in ('annual_report','revised_report') and x['notice_date']<doc['notice_date']]
            if doc['document_kind']!='annual_report':
                if not earlier:raise ValueError('orphan revision/correction')
                doc['previous_report_id']=earlier[-1]['id']
        bases={(x['stock_code'],x['period_end']) for x in documents if x['document_kind']=='annual_report'}
        qualified={code for code,period in bases if sum(c==code for c,p in bases)>=2}
        revisions=sum(x['document_kind']=='revised_report' for x in documents)
        if len(qualified)<2 or not revisions:raise ValueError('two-stock/two-period and real revision gate not satisfied')
        result={'schema_version':'official-disclosures-1','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'scope':'locally verified public disclosure materials; no financial PIT values; not a complete live announcement feed',
            'sample_gate':{'status':'pass','stocks':len({code for code,p in bases}),'original_stock_periods':len(bases),'verified_pdfs':len(documents),
                           'revised_reports':revisions,'correction_notices':sum(x['document_kind']=='correction_notice' for x in documents)},
            'documents':documents,'index_evidence':proofs}
        (staging/'catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        DisclosureStore(staging)._read()
        staging.rename(destination)
        return result
    except BaseException:
        shutil.rmtree(staging);raise


def install_bundle(source,destination,*,expected_catalog_sha256):
    """Append immutable assets, then atomically replace catalog; reject concurrent/stale writes."""
    source=Path(source);destination=Path(destination)
    incoming=DisclosureStore(source)._read();current=DisclosureStore(destination)._read()
    old=(destination/'catalog.json').read_bytes()
    if sha(old)!=expected_catalog_sha256:raise ValueError('destination changed; refused stale install')
    old_docs={d['id']:d for d in current['documents']};new_docs={d['id']:d for d in incoming['documents']}
    if not set(old_docs)<=set(new_docs) or any(new_docs[k]!=v for k,v in old_docs.items()):
        raise ValueError('incremental install must preserve every existing document')
    assets=[d['pdf_path'] for d in incoming['documents']]+[p['path'] for p in incoming['index_evidence'].values()]
    for name in assets:
        target=destination/name
        if target.exists() and sha(target.read_bytes())!=sha((source/name).read_bytes()):raise ValueError('asset conflict; refused overwrite')
    lock=destination.parent/'.disclosures-import.lock';created=[];committed=False;temp_created=False
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(descriptor)
    try:
        if sha((destination/'catalog.json').read_bytes())!=expected_catalog_sha256:raise ValueError('destination changed before install')
        backup=destination.parent/f'disclosures-catalog-{expected_catalog_sha256}.json'
        if backup.exists() and backup.read_bytes()!=old:raise ValueError('catalog backup conflict')
        if not backup.exists():backup.write_bytes(old)
        for name in assets:
            target=destination/name
            if target.exists():
                if sha(target.read_bytes())!=sha((source/name).read_bytes()):raise ValueError('asset changed during import')
                continue
            target.parent.mkdir(exist_ok=True)
            with target.open('xb') as stream:
                created.append(target);stream.write((source/name).read_bytes())
        temp=destination/'catalog.next.json'
        with temp.open('xb') as stream:
            temp_created=True;stream.write((source/'catalog.json').read_bytes())
        temp.replace(destination/'catalog.json');committed=True
        return {'status':'installed','old_catalog_sha256':expected_catalog_sha256,
                'new_catalog_sha256':sha((destination/'catalog.json').read_bytes()),
                'new_assets':len(created),'documents':len(incoming['documents']),'backup':str(backup)}
    finally:
        if not committed:
            for path in created:path.unlink()
            if temp_created and temp.exists():temp.unlink()
        lock.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',action='append',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--base');parser.add_argument('--selection',help='JSON array of announcement IDs')
    args=parser.parse_args();result=compile_bundle(args.source,args.output,base=args.base,
        selected_ids=json.loads(Path(args.selection).read_text()) if args.selection else None)
    print(json.dumps(result['sample_gate'],ensure_ascii=False))
