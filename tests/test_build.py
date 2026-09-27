"""Resource composition stays offline and shares native panel geometry."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
from build import CONFIG, panel
from nx.desktop import DEFAULT_CONFIG


class BuildTests(unittest.TestCase):
    def test_native_and_html_share_geometry(self):
        self.assertEqual(CONFIG, DEFAULT_CONFIG)

    def test_production_has_no_demo_data_or_external_resources(self):
        html = panel()
        self.assertNotIn('@example.com', html)
        self.assertNotIn('function seed(', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link ', html)
        self.assertIn('class="live"', html)

    def test_modules_are_loaded_once_before_app_initialization(self):
        for demo in (False, True):
            with self.subTest(demo=demo):
                html = panel(demo=demo)
                for marker in ('window.NXFeedback =', 'window.NXMath =', 'window.NXComponents =', 'window.NXRuntime =',
                               'window.NXViews.accounts =', 'window.NXViews.resume =',
                               'window.NXViews.usage =', 'window.NXViews.settings ='):
                    self.assertEqual(html.count(marker), 1)
                    self.assertLess(html.index(marker), html.index('const config = window.NX_CONFIG;'))
                self.assertEqual(html.count('function seed('), int(demo))
