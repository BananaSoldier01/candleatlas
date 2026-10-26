import json
import tempfile
import unittest
from unittest.mock import patch
from market import Market, DataError


class ArchiveTests(unittest.TestCase):
    def test_old_complete_pool_survives_restart_without_requests(self):
        with tempfile.TemporaryDirectory() as folder, patch('market.today', return_value='2026-09-22'):
            m = Market(folder)
            m.get = lambda *a, **k: {'pagination': {'total': 1}, 'item': [{'thscode': '000001.SZ'}]}
            m.pool('2026-09-01')
            m = Market(folder)
            m.get = lambda *a, **k: self.fail('历史数据不应请求上游')
            self.assertEqual(len(m.pool('2026-09-01')), 1)

    def test_incomplete_resync_preserves_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            m = Market(folder)
            m.get = lambda *a, **k: {'pagination': {'total': 1}, 'item': [{'thscode': '000001.SZ'}]}
            m.pool('2026-09-01')
            path = m.archive_dir / '2026-09-01-up.json'
            original = path.read_bytes()
            m.get = lambda *a, **k: {'pagination': {'total': 2}, 'item': []}
            with self.assertRaises(DataError):
                m.pool('2026-09-01', force=True)
            self.assertEqual(path.read_bytes(), original)

    def test_intraday_snapshot_is_not_permanently_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            m = Market(folder)
            path = m.archive_dir / '2026-09-01-up.json'
            path.write_text(json.dumps({'version': 1, 'saved_at': 0, 'items': []}))
            calls = []
            def get(*args, **kwargs):
                calls.append(kwargs['ttl'])
                return {'pagination': {'total': 1}, 'item': [{'thscode': '000001.SZ'}]}
            m.get = get
            self.assertEqual(len(m.pool('2026-09-01')), 1)
            self.assertEqual(calls, [0])

    def test_recent_expired_and_manual_sync_bypass_request_cache(self):
        with tempfile.TemporaryDirectory() as folder, patch('market.today', return_value='2026-09-22'):
            m = Market(folder)
            calls = []
            def get(*a, **k):
                calls.append(k['ttl'])
                return {'pagination': {'total': 0}, 'item': []}
            m.get = get
            m.pool('2026-09-21')
            path = m.archive_dir / '2026-09-21-up.json'
            d = json.loads(path.read_text());d['saved_at'] = 0;path.write_text(json.dumps(d))
            m.pool('2026-09-21')
            m.pool('2026-09-21', force=True)
            self.assertEqual(calls, [21600, 0, 0])

    def test_empty_hot_not_archived(self):
        with tempfile.TemporaryDirectory() as folder:
            m = Market(folder);m.window = lambda *a: ['2026-09-01']
            m.get = lambda *a, **k: {'date': '2026-09-01', 'item': []}
            with self.assertRaises(DataError): m.hot('2026-09-01')
            self.assertFalse(list(m.archive_dir.glob('*.json')))
