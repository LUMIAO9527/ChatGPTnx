"""A distributable must include every build module, not only edited fragments."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from package import package

class PackageTests(unittest.TestCase):
    def test_complete_source_without_runtime_data(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'source.zip';package(target)
            with zipfile.ZipFile(target) as archive:
                names=set(archive.namelist())
                for name in ('build.cmd','LICENSE','src/assets/nx.ico','src/nx/settings.py',
                             'src/nx/quota_policy.py','src/ui/runtime.js',
                             'src/ui/views/settings.js','tests/runtime_checks.cjs',
                             'tests/ui_refactor_checks.py','tools/browser_session.py',
                             'src/continue_in_desktop.ps1',
                             'preview.cmd','src/ui/views/onboarding.js','src/ui/preview.js',
                             'tools/screen_catalog.py','tools/templates/explorer.html',
                             'tools/build_explorer.py','tools/build_gallery.py',
                             'tests/ui_final_checks.py','tests/quota_columns_checks.cjs','src/ui/preferences.js','src/ui/views/editors.js','tools/test_resume_priority.ps1','tools/test_automatic_resume.ps1','src/nx/resume_policy.py'):
                    self.assertIn(name,names)
                self.assertFalse(any(n.startswith(('_data/','snapshots/','reference/','.git/','_wip/','docs/')) for n in names))
                self.assertNotIn('accounts.txt',names)
                self.assertIsNone(archive.testzip())

    def test_manifest_covers_every_payload_once(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'source.zip';package(target)
            with zipfile.ZipFile(target) as archive:
                manifest=archive.read('MANIFEST.sha256').decode().splitlines()
                listed=set()
                for row in manifest:
                    digest,name=row.split('  ',1);self.assertNotIn(name,listed);listed.add(name)
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
                self.assertEqual(listed,set(archive.namelist())-{'MANIFEST.sha256'})
