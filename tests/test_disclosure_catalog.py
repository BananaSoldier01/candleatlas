"""Strict dates, no cross-stock pairing, and real original/correction metadata boundary."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import tempfile
import subprocess
import sys
from scripts.disclosure_catalog import available_at,materials_asof,metadata,build
from scripts.official_collect import Collector,sha

DOCUMENTS=json.loads((Path(__file__).parent/'fixtures/disclosure_metadata.json').read_text())['documents']

class DisclosureMaterialsTests(unittest.TestCase):
    def test_original_and_real_correction_boundaries(self):
        def at(value):return materials_asof(DOCUMENTS,'603558','2024-12-31',value)
        self.assertEqual(at('2025-03-25')['status'],'unavailable')
        first=at('2025-03-26T00:00:00+08:00')
        self.assertEqual(first['base']['document_kind'],'annual_report')
        self.assertEqual(first['corrections'],[])
        self.assertEqual(at('2025-07-12')['corrections'],[])
        corrected=at('2025-07-13T00:00:00+08:00')
        self.assertEqual(corrected['base']['id'],first['base']['id'])
        self.assertEqual(len(corrected['corrections']),1)
        self.assertTrue(corrected['corrections'][0]['has_before_after'])
        self.assertIsNone(corrected['corrections'][0]['financial_values'])
        self.assertEqual(at('2025-07-12T16:00:00+00:00')['corrections'],corrected['corrections'])
    def test_missing_date_bad_asof_and_cross_stock_fail_closed(self):
        self.assertEqual(materials_asof(DOCUMENTS,'603558','2023-12-31','2026-01-01')['status'],'unavailable')
        self.assertEqual(materials_asof(DOCUMENTS,'600000','2024-12-31','2026-01-01')['status'],'unavailable')
        for value in ('bad','2025-03-26T10:00:00',None):
            self.assertEqual(materials_asof(DOCUMENTS,'603558','2024-12-31',value)['status'],'invalid')
        for value in ('2025-01-01bad','2025-02-30','9999-12-31',None): self.assertIsNone(available_at(value))
    def test_archive_path_does_not_supply_publication_date(self):
        text='公司代码：603558 公司简称：健盛集团 2023 年年度报告'
        result=metadata(text,'https://static.cninfo.com.cn/finalpage/2024-03-16/1.PDF')
        self.assertEqual(result['archive_date'],'2024-03-16')
        self.assertIsNone(result['notice_date'])
        self.assertEqual(result['period_end'],'2023-12-31')
    def test_corrupt_or_future_material_not_selected(self):
        docs=copy.deepcopy(DOCUMENTS)
        for item in docs: item['integrity']='failed'
        self.assertEqual(materials_asof(docs,'603558','2024-12-31','2026-01-01')['status'],'unavailable')
        for item in docs: item.update(integrity='match',available_at='bad')
        self.assertEqual(materials_asof(docs,'603558','2024-12-31','2026-01-01')['status'],'unavailable')
    def test_empty_catalog_is_unverified_and_cli_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            Collector(folder).save()
            self.assertEqual(build(folder)['status'],'unverified')
            result=subprocess.run([sys.executable,'-B','-m','scripts.disclosure_catalog','--folder',folder],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
    def test_missing_date_and_partial_samples_do_not_pass(self):
        # Parser boundary fixture only, not counted as an official document sample.
        with tempfile.TemporaryDirectory() as folder:
            collector=Collector(folder)
            path=Path(folder)/'raw/001.bin';path.parent.mkdir();body=b'%PDF-1.7\n%%EOF';path.write_bytes(body)
            collector.data['requests']=[{'id':1,'url':'https://static.cninfo.com.cn/finalpage/2024-03-16/1.PDF',
                'ok':True,'result':'response','raw':'raw/001.bin','sha256':sha(body),'fetched_at':'2026-10-23T00:00:00+00:00'}]
            collector.save()
            with patch('scripts.disclosure_catalog.subprocess.run',return_value=SimpleNamespace(stdout='公司代码：603558 公司简称：健盛集团 2023 年年度报告')):
                report=build(folder)
            self.assertEqual(report['status'],'incomplete')
            self.assertEqual(report['date_missing'],1)
            path.write_bytes(body+b'corrupt')
            self.assertEqual(build(folder)['status'],'failed')
        docs=copy.deepcopy(DOCUMENTS)
        for item in docs: item['stock_code']='600000'
        self.assertEqual(materials_asof(docs,'603558','2024-12-31','2026-01-01')['status'],'unavailable')
