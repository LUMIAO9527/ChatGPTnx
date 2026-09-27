"""Second-pass regressions: data semantics, catalog and demo/production separation."""
import re
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from nx.quota import normalize_usage_credits
from screen_catalog import CASES
from build import panel
from build_explorer import build_explorer

class CreditsTests(unittest.TestCase):
    def test_decimal_precision_and_zero_are_preserved(self):
        for raw,expected in [('12.50','12.50'),('0.00','0.00'),(0,'0'),('-0.00','0.00'),('123456789012345.6789','123456789012345.6789')]:
            with self.subTest(raw=raw):self.assertEqual(normalize_usage_credits({'balance':raw}),{'status':'available','balance':expected})
    def test_absence_is_not_zero(self):
        for raw in (None,{}, {'hasCredits':False}, {'balance':None}):
            with self.subTest(raw=raw):self.assertEqual(normalize_usage_credits(raw),{'status':'not_provided','balance':None})
    def test_unlimited_requires_literal_true(self):
        self.assertEqual(normalize_usage_credits({'unlimited':True,'balance':None})['status'],'unlimited')
        self.assertEqual(normalize_usage_credits({'unlimited':'true','balance':None})['status'],'not_provided')
    def test_invalid_values_never_become_displayable_balances(self):
        for value in (True,False,{},[],float('nan'),float('inf'),'-1','NaN','Infinity','', '1e50000','1'*81):
            with self.subTest(value=value):self.assertEqual(normalize_usage_credits({'balance':value}),{'status':'invalid','balance':None})
    def test_non_dictionary_is_invalid(self):
        for raw in ('12.50',[],True):
            with self.subTest(raw=raw):self.assertEqual(normalize_usage_credits(raw)['status'],'invalid')

class CatalogTests(unittest.TestCase):
    def test_unique_catalog_entries_and_required_fields(self):
        self.assertEqual(len(CASES),len({c['id'] for c in CASES}))
        self.assertGreater(len(CASES),130)
        for case in CASES:
            for key in ('id','group','label','route','query','steps','expected'):
                self.assertIn(key,case)
    def test_every_sheet_route_has_preview_coverage(self):
        source=(ROOT/'src/ui/app.js').read_text(encoding='utf-8')
        section=source.split('function renderSheet(')[1].split('const actionLabels=')[0]
        routes=set(re.findall(r"case '([^']+)'",section))
        routes.discard('error')  # Legacy route closes the sheet; it renders no page.
        covered={c['route'] for c in CASES}|{c['expected'] for c in CASES}
        self.assertFalse(routes-covered, routes-covered)
    def test_mock_tools_and_catalog_never_enter_production_resources(self):
        live=panel(demo=False);demo=panel(demo=True)
        for marker in ('function simulate(event)','window.NX_CATALOG=','source:\'chatgptnx-preview\''):
            self.assertNotIn(marker,live);self.assertIn(marker,demo)
        self.assertNotIn('@example.com',live)
    def test_first_use_is_separate_from_home_cards(self):
        source=(ROOT/'src/ui/app.js').read_text(encoding='utf-8')
        self.assertIn('NXViews.onboarding',source)
        self.assertNotIn('card onboarding',source)
        self.assertIn("detail('Credits',creditValue(a))",source)
    def test_capture_validates_route_and_scroll_content(self):
        source=(ROOT/'tools/capture_previews.py').read_text(encoding='utf-8')
        self.assertIn("case['expected']",source)
        self.assertIn('--full.png',source)
    def test_browser_explorer_is_single_file_and_offline(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            html=build_explorer(Path(folder)/'explorer.html')
        self.assertNotIn('<script src=',html)
        self.assertNotIn('<link ',html)
        self.assertIn("connect-src 'none'",html)
        self.assertIn('frame.srcdoc=',html)

if __name__=='__main__':unittest.main()
