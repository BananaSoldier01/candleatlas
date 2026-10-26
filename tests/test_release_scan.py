"""Public images cannot silently bypass the release boundary scan."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release_scan',Path(__file__).resolve().parents[1]/'scripts'/'check_release.py')
scan=importlib.util.module_from_spec(spec);spec.loader.exec_module(scan)
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jAUcAAAAASUVORK5CYII=')


class ReleaseScanTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.image=self.root/'docs/images/chart.png';self.image.parent.mkdir(parents=True);self.image.write_bytes(PNG)
        self.manifest=self.root/scan.MEDIA_MANIFEST
        self.media={'dataset':'synthetic','reviewed':True,'files':{'docs/images/chart.png':{'sha256':hashlib.sha256(PNG).hexdigest(),'width':1,'height':1}}}
        self.save()
    def save(self):self.manifest.write_text(json.dumps(self.media))
    def run_scan(self,exclude=()):
        paths=[p for p in self.root.rglob('*')if p.is_file()and p.relative_to(self.root).as_posix()not in exclude]
        output=io.StringIO()
        with patch.object(scan,'ROOT',self.root),patch.object(scan,'files',return_value=paths),contextlib.redirect_stdout(output):result=scan.main()
        return result,output.getvalue()
    def test_approved_synthetic_image_passes(self):
        code,out=self.run_scan();self.assertEqual(code,0);self.assertIn('1 approved images',out)
    def test_changed_image_requires_review_again(self):
        self.image.write_bytes(PNG+b'changed');code,out=self.run_scan();self.assertEqual(code,1);self.assertIn('reviewed_image_changed',out)
    def test_unlisted_binary_remains_blocked(self):
        (self.image.parent/'private.png').write_bytes(PNG);code,out=self.run_scan();self.assertEqual(code,1);self.assertIn('unreviewed_binary',out)
    def test_outside_path_cannot_be_approved(self):
        self.media['files']={'../../private.png':next(iter(self.media['files'].values()))};self.save();code,out=self.run_scan();self.assertEqual(code,1);self.assertIn('invalid_media_manifest',out)
    def test_approval_cannot_live_outside_scanned_files(self):
        code,out=self.run_scan(exclude=(scan.MEDIA_MANIFEST,));self.assertEqual(code,1);self.assertIn('invalid_media_manifest',out)
    def test_missing_or_wrong_dimensions_fail(self):
        self.assertEqual(self.run_scan(exclude=('docs/images/chart.png',))[0],1)
        self.media['files']['docs/images/chart.png']['width']=2;self.save();self.assertEqual(self.run_scan()[0],1)
    def test_invalid_or_unreviewed_manifest_fails_without_crashing(self):
        for content in ['[]','null','bad-json',json.dumps({**self.media,'reviewed':False})]:
            self.manifest.write_text(content);code,out=self.run_scan();self.assertEqual(code,1);self.assertIn('invalid_media_manifest',out)
    def test_text_secret_scan_still_runs(self):
        secret='test-only-'+('x'*20);(self.root/'example.py').write_text('api'+'_key = '+repr(secret));code,out=self.run_scan();self.assertEqual(code,1);self.assertIn('credential_literal',out);self.assertNotIn(secret,out)
