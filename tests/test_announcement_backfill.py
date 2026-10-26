"""Historical packages are reverified from dated raw evidence, never trusted as detached normalized data."""
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from announcement_backfill import PROFILE,verify,load
from announcement_clues import AnnouncementClues,INDEX
from market import DataError
from scripts.official_collect import Collector
from test_announcement_clues import row,Response,DAY,NOTICE


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.folder=self.root/DAY/PROFILE;self.folder.mkdir(parents=True)
        self.meta=dict(schema_version=1,day=DAY,notice_day=NOTICE)
        (self.folder/'package.json').write_text(json.dumps(self.meta))
        self.add('seed-1',[row(1),row(2)],3)
        self.add('additional',[row(3)],1,stock='600003,org3')

    def add(self,part,rows,total,page=1,stock='',params=None):
        c=Collector(self.folder/part,max_requests={'seed-1':50,'seed-2':12,'additional':20}[part],
            transport=lambda *a,**kw:Response(json.dumps(dict(totalAnnouncement=total,announcements=rows)).encode()))
        q=AnnouncementClues.query(NOTICE,'all',page);q['stock']=stock
        if params:q.update(params)
        return c.fetch(INDEX,method='POST',data=urlencode(q))

    def replace_additional(self,rows,total=1,**kwargs):
        import shutil
        shutil.rmtree(self.folder/'additional');return self.add('additional',rows,total,**kwargs)

    def test_complete_package_is_rebuilt_from_raw_evidence(self):
        d=load(self.folder,DAY)
        self.assertTrue(d['pagination_reconciled']);self.assertEqual(d['unique_verified'],3)
        self.assertEqual(d['backfill']['additional_requests'],1)
        self.assertTrue(all(e['notice_date']==NOTICE and e['available_at'][:10]==DAY for r in d['item']for e in r['evidence']))

    def test_adapter_get_and_read_do_not_fetch_after_approved_package(self):
        def forbidden(*args,**kwargs):raise AssertionError('network collector must not be created')
        source=AnnouncementClues(self.root,forbidden)
        self.assertEqual(source.get(DAY)['item'],source.read(DAY)['item'])

    def test_incomplete_package_is_not_trusted_or_automatically_retried(self):
        self.replace_additional([],total=1,stock='600003,org3')
        state=verify(self.folder,DAY,require_complete=False);self.assertFalse(state['complete'])
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'incomplete')

    def test_hash_tamper_blocks_both_adapter_paths(self):
        next((self.folder/'additional'/'raw').glob('*.bin')).write_bytes(b'bad')
        source=AnnouncementClues(self.root)
        for f in [source.get,source.read]:
            with self.assertRaises(DataError)as exc:f(DAY)
            self.assertEqual(exc.exception.reason,'invalid_snapshot')

    def test_wrong_notice_date_is_rejected(self):
        self.replace_additional([row(3,day=DAY)],stock='600003,org3')
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'date_mismatch')

    def test_issuer_scope_cannot_be_ignored(self):
        self.replace_additional([row(9)],stock='600003,org3')
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'invalid_snapshot')

    def test_conflicting_identity_does_not_overwrite_old_evidence(self):
        self.replace_additional([row(1,'不同的业绩预告')],stock='600001,org1')
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'invalid_snapshot')

    def test_exclusions_also_require_valid_date_and_original_link(self):
        self.replace_additional([{**row(3),'secCode':'200530'}],stock='200530,org3')
        d=load(self.folder,DAY);self.assertEqual(d['excluded_non_a'],1);self.assertEqual(d['unique_verified'],2)
        self.replace_additional([{**row(3,day=DAY),'secCode':'200530'}],stock='200530,org3')
        with self.assertRaises(DataError):load(self.folder,DAY)

    def test_changing_index_total_does_not_claim_complete(self):
        self.replace_additional([row(3)],total=4,page=2)
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'incomplete')

    def test_page_continuity_is_required_even_when_identity_count_matches(self):
        import shutil
        shutil.rmtree(self.folder/'seed-1');self.add('seed-1',[row(i)for i in range(1,31)],31)
        self.replace_additional([row(31)],stock='600031,org31')
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'incomplete')

    def test_wrong_query_date_or_sort_cannot_be_used(self):
        self.replace_additional([row(3)],params=dict(sortName='time'))
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'invalid_snapshot')

    def test_declared_completion_does_not_override_missing_evidence(self):
        (self.folder/'package.json').write_text(json.dumps({**self.meta,'complete':True}))
        (self.folder/'additional'/'raw'/'001.bin').unlink()
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'invalid_snapshot')

    def test_malformed_package_and_budget_are_rejected(self):
        p=self.folder/'additional'/'ledger.json';d=json.loads(p.read_text());d['max_requests']=50;p.write_text(json.dumps(d))
        with self.assertRaises(DataError):load(self.folder,DAY)
        (self.folder/'package.json').write_text('{bad')
        with self.assertRaises(DataError)as exc:load(self.folder,DAY)
        self.assertEqual(exc.exception.reason,'invalid_snapshot')
