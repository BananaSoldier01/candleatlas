"""Compile/import validation with synthetic PDF bytes; independent real samples are audited separately."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from disclosure_fakes import FIXTURE
from scripts.official_collect import sha
from scripts.compile_disclosures import compile_bundle,install_bundle,verify_pdf_identity
from disclosures import DisclosureStore

class DisclosureCompileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'source';(self.source/'raw').mkdir(parents=True)
        self.records=[];self.by_id={d['id']:d for d in FIXTURE['catalog']['documents']}
        for digest,proof in FIXTURE['catalog']['index_evidence'].items():
            self.add(proof['url'],FIXTURE['index_bytes'][digest].encode(),request_body_utf8=proof['request_body_utf8'],request_headers=proof['request_headers'])
        for doc in self.by_id.values():self.add(doc['url'],('%PDF-1.7\nSYNTHETIC '+doc['id']+'\n%%EOF').encode())
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def add(self,url,body,**extra):
        identifier=len(self.records)+1;name=f'raw/{identifier:03}.bin';(self.source/name).write_bytes(body)
        self.records.append(dict(id=identifier,url=url,ok=True,raw_complete=True,raw=name,sha256=sha(body),fetched_at='2026-10-23T00:00:00+00:00',**extra))
    def save(self):(self.source/'ledger.json').write_text(json.dumps({'requests':self.records}))
    def text(self,command,**kwargs):
        doc=self.by_id[Path(command[2]).stem]
        return SimpleNamespace(stdout=f"公司代码：{doc['stock_code']} 公司简称：{doc['stock_name']} {doc['period_end'][:4]}年年度报告")
    def test_compiled_bundle_passes_gate_and_runtime_validation(self):
        with patch('scripts.compile_disclosures.subprocess.run',side_effect=self.text):
            result=compile_bundle([self.source],self.root/'out')
        self.assertEqual(result['sample_gate']['verified_pdfs'],7)
        self.assertEqual(DisclosureStore(self.root/'out').query('001380.SZ','2025-04-29','2024-4')['items'][0]['id'],'1223321707')
        with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'out')
    def test_wrong_pdf_identity_and_missing_pdf_leave_no_output(self):
        with patch('scripts.compile_disclosures.subprocess.run',return_value=SimpleNamespace(stdout='公司代码：600000 浦发银行 2024年年度报告')):
            with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'bad')
        self.assertFalse((self.root/'bad').exists())
        self.records.pop();self.save()
        with patch('scripts.compile_disclosures.subprocess.run',side_effect=self.text):
            with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'missing')
        self.assertFalse((self.root/'missing').exists())
    def test_corrupted_hash_and_cross_stock_index_fail(self):
        raw=self.source/self.records[-1]['raw'];body=raw.read_bytes();raw.write_bytes(body+b'bad')
        with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'hash')
        raw.write_bytes(body)
        first=self.records[0];payload=json.loads((self.source/first['raw']).read_text());payload['announcements'][0]['secCode']='999999'
        content=json.dumps(payload).encode();(self.source/first['raw']).write_bytes(content);first['sha256']=sha(content);self.save()
        with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'stock')
    def new_report(self):
        identifier='9999991001';self.by_id[identifier]={'stock_code':'001380','stock_name':'华纬科技','period_end':'2025-12-31'}
        row={'secCode':'001380','secName':'华纬科技','announcementId':identifier,'announcementTitle':'2025年年度报告',
             'announcementTime':1774972800000,'adjunctUrl':'finalpage/2026-04-01/'+identifier+'.PDF'}
        self.add('https://www.cninfo.com.cn/new/hisAnnouncement/query',json.dumps({'totalAnnouncement':1,'announcements':[row]}).encode(),
                 request_body_utf8='stock=001380%2C9900041935&column=szse',request_headers={})
        self.add('https://static.cninfo.com.cn/'+row['adjunctUrl'],('%PDF-1.7\nSYNTHETIC '+identifier+'\n%%EOF').encode());self.save()
        return identifier
    def test_incremental_merge_preserves_base_and_same_ids_are_not_duplicated(self):
        with patch('scripts.compile_disclosures.subprocess.run',side_effect=self.text):
            base=compile_bundle([self.source],self.root/'base');identifier=self.new_report()
            merged=compile_bundle([self.source],self.root/'merged',base=self.root/'base',selected_ids=[identifier])
            repeat=compile_bundle([self.source],self.root/'repeat',base=self.root/'merged',selected_ids=[identifier])
        self.assertEqual(len(merged['documents']),8);self.assertEqual(len(repeat['documents']),8)
        prior={d['id']:d for d in base['documents']};after={d['id']:d for d in merged['documents']}
        self.assertTrue(all(after[k]==v for k,v in prior.items()))
        self.assertEqual(DisclosureStore(self.root/'merged').query('001380.SZ','2026-04-02','2025-4')['items'][0]['id'],identifier)
    def test_atomic_install_stale_guard_backup_and_failed_publish(self):
        with patch('scripts.compile_disclosures.subprocess.run',side_effect=self.text):
            compile_bundle([self.source],self.root/'base');identifier=self.new_report()
            compile_bundle([self.source],self.root/'merged',base=self.root/'base',selected_ids=[identifier])
        base=self.root/'base';old=(base/'catalog.json').read_bytes();initial={str(p.relative_to(base)):p.read_bytes() for p in base.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):install_bundle(self.root/'merged',base,expected_catalog_sha256='wrong')
        original_open=Path.open
        def fail_publish(path,*args,**kwargs):
            if path.name=='catalog.next.json':raise OSError('injected publish failure')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',fail_publish):
            with self.assertRaises(OSError):install_bundle(self.root/'merged',base,expected_catalog_sha256=sha(old))
        self.assertEqual({str(p.relative_to(base)):p.read_bytes() for p in base.rglob('*') if p.is_file()},initial)
        self.assertFalse((self.root/'.disclosures-import.lock').exists())
        result=install_bundle(self.root/'merged',base,expected_catalog_sha256=sha(old))
        self.assertEqual(result['documents'],8);self.assertEqual(Path(result['backup']).read_bytes(),old)
        for name,body in initial.items():
            if name!='catalog.json':self.assertEqual((base/name).read_bytes(),body)
    def test_missing_selected_identity_and_conflicting_existing_bytes_fail(self):
        with patch('scripts.compile_disclosures.subprocess.run',side_effect=self.text):
            compile_bundle([self.source],self.root/'base')
            with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'missing-selected',base=self.root/'base',selected_ids=['999999'])
            record=self.records[-1];path=self.source/record['raw'];body=path.read_bytes()+b'changed';path.write_bytes(body);record['sha256']=sha(body);self.save()
            with self.assertRaises(ValueError):compile_bundle([self.source],self.root/'conflict',base=self.root/'base')
        self.assertFalse((self.root/'conflict').exists())
    def test_share_listing_table_and_image_cover_require_code_name_and_period(self):
        table='驰宏锌锗 公司股票简况 股票种类 股票上市交易所 股票简称 股票代码 变更前股票简称\n A股 上海证券交易所 驰宏锌锗 600497 —'
        result=verify_pdf_identity(table,'600497','驰宏锌锗','2024',ocr='云南驰宏锌锗股份有限公司\n2024\n年度报告\nANNUAL REPORT')
        self.assertEqual(result['stock_code_basis'],'company_share_listing_table');self.assertEqual(result['period_basis'],'cover_ocr_year_and_annual_report')
        for text,ocr in [(table,'2025 ANNUAL REPORT'),(table,'2024 company profile'),(table,'2024 2025 ANNUAL REPORT'),
                         ('驰宏锌锗 email600497@example.com','2024 ANNUAL REPORT'),(table.replace('600497','600000'),'2024 ANNUAL REPORT'),
                         (table+' 2025年年度报告','2024 ANNUAL REPORT')]:
            with self.subTest(text=text[-40:],ocr=ocr),self.assertRaises(ValueError):verify_pdf_identity(text,'600497','驰宏锌锗','2024',ocr=ocr)
