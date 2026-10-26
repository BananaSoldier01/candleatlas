import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import settings
import market

class SettingsTests(unittest.TestCase):
    def test_save_preserves_other_config_and_never_returns_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), patch.object(settings,'ROOT',Path(tmp)), patch.object(market,'ROOT',Path(tmp)):
            path=Path(tmp)/'.env.local';path.write_text('# local\nOTHER=value\nHITHINK_FINANCE_API_KEY=old\n')
            result=settings.save_key('test-only-key')
            self.assertEqual(market.load_key(),'test-only-key')
            self.assertEqual(result,{'configured':True,'managed':False})
            self.assertIn('OTHER=value',path.read_text())
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            for key in ('', 'bad\nkey', 'a"b', None):
                with self.assertRaises(market.DataError):settings.save_key(key)
            self.assertEqual(market.load_key(),'test-only-key')
    def test_environment_does_not_silently_override_save(self):
        with patch.dict(os.environ,{'HITHINK_FINANCE_API_KEY':'environment-test'}):
            self.assertTrue(settings.status()['managed'])
            with self.assertRaises(market.DataError):settings.save_key('new-test')
