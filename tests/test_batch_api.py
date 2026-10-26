"""Real HTTP handler + Analysis + batch lifecycle; temporary SQLite and fakes only."""
import datetime as dt
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from analysis import Analysis
from batch import SqliteStore
from market import DataError
from report_batch import BatchService
from server import Handler

DAY = '2026-03-21'


class FakeMarket:
    def __init__(self):
        self.calls = []
        self.block = threading.Event()
        self.block.set()
        self.entered = threading.Event()
        self.fail = set()

    def calendar(self):
        return [DAY]

    def prices(self, code, *args):
        self.calls.append(code)
        self.entered.set()
        if not self.block.wait(4):
            raise DataError('fake request timed out')
        if code in self.fail:
            raise DataError('synthetic market failure')
        return {'items': [dict(date=(dt.date(2026, 1, 1)+dt.timedelta(days=i)).isoformat(),
                               close_price=10+i*.1, volume=100) for i in range(80)]}


class FakeNews:
    def __init__(self):
        self.fail = set()

    def stock(self, code, *args):
        if code in self.fail:
            raise RuntimeError('synthetic news failure')
        return {'items': []}


class BatchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.market, self.news, self.model = FakeMarket(), FakeNews(), Mock()
        self.model.complete.side_effect = AssertionError('paid model must not be called')
        self.analysis = Analysis(self.folder/'reports.db', self.market, self.news, None, self.model)
        self.batch = BatchService(self.analysis, self.folder/'batches.db', timeout_s=.08)
        self.batch.bridge.poll_s = .005
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.analysis, self.http.batch = self.analysis, self.batch
        self.port = self.http.server_port
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.market.block.set()
        self.http.batch.wait()
        self.wait_reports()
        self.http.shutdown()
        self.thread.join(2)
        self.http.server_close()
        self.model.complete.assert_not_called()
        self.tmp.cleanup()

    def request(self, path, body=None, *, origin=True, raw=None):
        conn = HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = f'http://127.0.0.1:{self.port}'
        try:
            conn.request('POST' if body is not None or raw is not None else 'GET', path,
                         body=raw if raw is not None else json.dumps(body) if body is not None else None,
                         headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, json.loads(data)
        finally:
            conn.close()

    def submit(self, codes=('600000.SH',), **extra):
        status, data = self.request('/api/batch', {'date': DAY, 'members': [
            {'code': c, 'name': '合成 '+c} for c in codes], **extra})
        self.assertEqual(status, 202, data)
        return data['batch']['batch_id']

    def settled(self, identifier):
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            status, data = self.request('/api/batch?id='+identifier)
            self.assertEqual(status, 200, data)
            if not data['active']:
                return data
            time.sleep(.005)
        self.fail('batch did not finish')

    def wait_reports(self):
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            with self.http.analysis.db() as db:
                rows = db.execute("SELECT status FROM reports").fetchall()
            if all(r['status'] != 'running' for r in rows):
                return
            time.sleep(.005)
        self.fail('report did not finish')

    def test_success_dedup_redo_and_report_wiring(self):
        first = self.settled(self.submit(('600000.SH', '600001.SH')))
        self.assertEqual(first['batch']['status'], 'done')
        rid = first['items'][0]['report_id']
        status, report = self.request('/api/analysis?id='+rid)
        self.assertEqual(status, 200)
        self.assertIsNotNone(report['report']['assessment'])
        second = self.settled(self.submit(('600000.SH', '600001.SH')))
        self.assertEqual([i['status'] for i in second['items']], ['skipped_duplicate']*2)
        self.assertEqual(len(self.market.calls), 2)
        redo = self.settled(self.submit(reanalyze=True))
        new_id = redo['items'][0]['report_id']
        self.assertNotEqual(new_id, rid)
        again = self.settled(self.submit())
        self.assertEqual(again['items'][0]['report_id'], new_id)
        self.assertEqual(len(self.market.calls), 3)
        status, report = self.request('/api/analysis?id='+new_id)
        self.assertEqual(report['delta']['raw']['selection']['rule'], 'same_day_previous_version')
        self.assertEqual(len(report['delta']['rows']), 8)

    def test_partial_keeps_status_on_repeat_and_reopen(self):
        self.news.fail.add('600000.SH')
        first = self.settled(self.submit())
        self.assertEqual(first['batch']['status'], 'partial')
        rid = first['items'][0]['report_id']
        for reopen in (False, True):
            if reopen:
                self.http.batch = BatchService(self.analysis, self.folder/'batches.db')
                self.http.batch.bridge.poll_s = .005
            result = self.settled(self.submit())
            item = result['items'][0]
            self.assertEqual(result['batch']['status'], 'partial')
            self.assertEqual((item['status'], item['report_status'], item['report_id']),
                             ('skipped_duplicate', 'partial', rid))
            self.assertIn('partial', item['error'])
        self.assertEqual(self.market.calls, ['600000.SH'])

    def test_manual_contention_and_retry_only_failed(self):
        self.market.block.clear()
        status, manual = self.request('/api/analysis', {'code': '600000.SH', 'date': DAY, 'ai': False})
        self.assertEqual(status, 202)
        self.assertTrue(self.market.entered.wait(2))
        bid = self.submit(('600001.SH',))
        result = self.settled(bid)
        self.assertEqual(result['items'][0]['status'], 'failed')
        self.assertIn('start_rejected', result['items'][0]['error'])
        self.assertEqual(self.market.calls, ['600000.SH'])
        self.market.block.set()
        self.wait_reports()
        self.assertEqual(self.request('/api/batch/retry', {'id': bid})[0], 202)
        self.assertEqual(self.settled(bid)['batch']['status'], 'done')
        self.assertEqual(self.market.calls, ['600000.SH', '600001.SH'])

    def test_timeout_keeps_id_blocks_redo_and_manual_review(self):
        self.market.block.clear()
        bid = self.submit()
        first = self.settled(bid)
        self.assertEqual(first['batch']['status'], 'needs_review')
        rid = first['items'][0]['report_id']
        self.assertTrue(rid)
        status, retry = self.request('/api/batch/retry', {'id': bid})
        self.assertEqual(retry['items'][0]['report_id'], rid)
        self.assertEqual(retry['batch']['status'], 'needs_review')
        blocked = self.settled(self.submit(reanalyze=True))
        self.assertEqual(blocked['batch']['status'], 'needs_review')
        self.assertEqual(blocked['items'][0]['report_id'], rid)
        self.assertEqual(self.request('/api/batch/review', {'id': bid, 'index': 0})[0], 400)
        self.market.block.set()
        self.wait_reports()
        status, reviewed = self.request('/api/batch/review', {'id': bid, 'index': 0})
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed['batch']['status'], 'done')
        self.assertEqual(self.settled(self.submit())['items'][0]['report_id'], rid)
        self.assertEqual(self.market.calls, ['600000.SH'])

    def test_cancel_does_not_execute_queued_and_survives_reopen(self):
        self.market.block.clear()
        self.batch.bridge.timeout_s = 2
        bid = self.submit(('600000.SH', '600001.SH'))
        self.assertTrue(self.market.entered.wait(2))
        self.assertEqual(self.request('/api/batch/cancel', {'id': bid})[0], 200)
        self.assertEqual(self.request('/api/batch/retry', {'id': bid})[0], 400)
        self.market.block.set()
        result = self.settled(bid)
        self.assertEqual([i['status'] for i in result['items']], ['done', 'cancelled'])
        self.http.batch = BatchService(self.analysis, self.folder/'batches.db')
        status, result = self.request('/api/batch/retry', {'id': bid})
        self.assertEqual(result['batch']['status'], 'cancelled')
        self.assertEqual(self.market.calls, ['600000.SH'])

    def test_partial_batch_retries_only_failed_member(self):
        self.market.fail.add('600001.SH')
        bid = self.submit(('600000.SH', '600001.SH'))
        first = self.settled(bid)
        self.assertEqual(first['batch']['status'], 'partial')
        successful_id = first['items'][0]['report_id']
        self.market.fail.clear()
        self.request('/api/batch/retry', {'id': bid})
        final = self.settled(bid)
        self.assertEqual(final['batch']['status'], 'done')
        self.assertEqual(final['items'][0]['report_id'], successful_id)
        self.assertEqual(self.market.calls, ['600000.SH', '600001.SH', '600001.SH'])

    def test_rejected_redo_preserves_previous_report(self):
        first = self.settled(self.submit())
        rid = first['items'][0]['report_id']
        self.market.entered.clear()
        self.market.block.clear()
        self.request('/api/analysis', {'code': '600001.SH', 'date': DAY, 'ai': False})
        self.assertTrue(self.market.entered.wait(2))
        result = self.settled(self.submit(reanalyze=True))
        self.assertEqual(result['batch']['status'], 'failed')
        self.market.block.set()
        self.wait_reports()
        result = self.settled(self.submit())
        self.assertEqual(result['items'][0]['report_id'], rid)
        self.assertEqual(self.market.calls, ['600000.SH', '600001.SH'])

    def test_origin_validation_ai_rejection_and_read_history(self):
        body = {'date': DAY, 'members': [{'code': '600000.SH'}]}
        self.assertEqual(self.request('/api/batch', body, origin=False)[0], 403)
        for bad in ([1], {**body, 'ai': True}, {**body, 'mode': 'ai'},
                    {**body, 'members': []}, {**body, 'members': [{'code': 'BAD'}]},
                    {**body, 'date': 'not-a-day'}):
            self.assertEqual(self.request('/api/batch', bad)[0], 400)
        self.assertEqual(self.request('/api/batch', raw='{')[0], 400)
        self.assertEqual(self.request('/api/batch/cancel', {'id': {}})[0], 400)
        self.assertEqual(self.request('/api/batch?id=invalid')[0], 400)
        self.assertEqual(self.market.calls, [])
        bid = self.submit()
        self.settled(bid)
        status, history = self.request('/api/batch?date='+DAY)
        self.assertEqual(status, 200)
        self.assertEqual(history['items'][0]['batch_id'], bid)

    def test_runtime_checkpoint_error_releases_gate(self):
        original = self.batch.runner._persist
        failed = []
        def persist(identifier):
            if not failed and self.batch.runner.batches[identifier]['status'] == 'running':
                failed.append(identifier)
                raise OSError('synthetic checkpoint failure')
            original(identifier)
        self.batch.runner._persist = persist
        first = self.settled(self.submit())
        self.assertEqual(first['batch']['status'], 'interrupted')
        self.assertIsNone(self.batch.gate.holder)
        self.assertEqual(self.settled(self.submit(('600001.SH',)))['batch']['status'], 'done')
        self.assertEqual(self.market.calls, ['600001.SH'])

    def test_restart_after_real_process_exit_does_not_resume(self):
        child = r'''
import os,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from test_batch_api import FakeMarket,FakeNews,DAY
from unittest.mock import Mock
from analysis import Analysis
from report_batch import BatchService
p=Path(sys.argv[2]);m=FakeMarket();model=Mock()
model.complete.side_effect=AssertionError('model forbidden')
a=Analysis(p/'crash-reports.db',m,FakeNews(),None,model)
s=BatchService(a,p/'crash-batches.db');s.bridge.poll_s=.005
commit=s.fingerprints.commit
def crash(key,rid,**kw):
    if key.startswith('600001.SH|'):os._exit(23)
    commit(key,rid,**kw)
s.fingerprints.commit=crash
b=s.submit({'date':DAY,'members':[{'code':'600000.SH'},{'code':'600001.SH'}]})
(p/'crash-id.txt').write_text(b['batch']['batch_id'])
s.wait(5)
'''
        run = subprocess.run([sys.executable, '-B', '-c', child, str(Path(__file__).resolve().parents[1]), str(self.folder)],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 23, run.stderr)
        self.http.analysis = Analysis(self.folder/'crash-reports.db', self.market, self.news, None, self.model)
        self.http.batch = BatchService(self.http.analysis, self.folder/'crash-batches.db')
        bid = (self.folder/'crash-id.txt').read_text()
        status, result = self.request('/api/batch?id='+bid)
        self.assertEqual(result['batch']['status'], 'interrupted')
        self.assertEqual([i['status'] for i in result['items']], ['done', 'needs_review'])
        self.assertTrue(result['items'][0]['report_id'])
        self.assertEqual(self.request('/api/batch/retry', {'id': bid})[0], 400)
        self.assertEqual(self.market.calls, [])

    def test_legacy_fingerprint_schema_is_upgraded_on_open(self):
        p = self.folder/'old.db'
        db = sqlite3.connect(p)
        try:
            with db:
                db.execute('CREATE TABLE fingerprints(fp TEXT PRIMARY KEY, report_id TEXT, created TEXT)')
                db.execute("INSERT INTO fingerprints VALUES('old','r1','now')")
        finally:
            db.close()
        store = SqliteStore(p)
        self.assertEqual(store.get_fp('old')['report_status'], 'unknown')
        store.set_fp('new', 'r2', 'partial')
        self.assertEqual(SqliteStore(p).get_fp('new'), {'report_id': 'r2', 'report_status': 'partial'})


if __name__ == '__main__':
    unittest.main()
