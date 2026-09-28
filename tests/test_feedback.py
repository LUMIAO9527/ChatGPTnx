"""Presentation contracts and rejected native dispatch recovery; Windows calls are mocked."""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from nx.desktop import Desktop, due_reset_expiry_notices
from build import CONFIG,panel
from screen_catalog import CASES

class PresentationContracts(unittest.TestCase):
    def test_single_panel_dimensions_are_single_source(self):
        self.assertNotIn('menu',CONFIG['sizes'])
        self.assertEqual(CONFIG['sizes']['home'],[372,520])
        self.assertEqual(CONFIG['sizes']['workspace'],[372,520])
    def test_feedback_module_is_in_live_and_demo(self):
        for demo in (True,False):
            html=panel(demo=demo)
            self.assertEqual(html.count('window.NXFeedback ='),1)
            self.assertLess(html.index('window.NXFeedback ='),html.index('const config = window.NX_CONFIG;'))
            self.assertNotIn('id="toast"',html)
    def test_new_cases_cover_actual_pending_and_error_actions(self):
        cases={c['id']:c for c in CASES}
        for key in ('first-launch-pending','first-launch-failed','detail-date-saved','edit-save-failed','settings-saving','appearance-expanded'):
            self.assertIn(key,cases)
        self.assertEqual(cases['first-launch-pending']['steps'][0]['click'],'[data-action="launch-chatgpt"]')
    def test_expiration_placeholder_is_plain_noninteractive_text(self):
        source=(ROOT/'src/ui/app.js').read_text(encoding='utf-8')
        self.assertIn('未录入到期时间',source)
        self.assertNotIn('data-action="edit-expiry"',source)
        self.assertIn('<div class="detail-expiry-note"',source)
    def test_feedback_gallery_version_uses_product_version(self):
        for filename in ('tools/build_explorer.py','tools/build_gallery.py'):
            source=(ROOT/filename).read_text(encoding='utf-8')
            self.assertIn('APP_VERSION',source)
            self.assertNotIn('5.7.1',source)

class SinglePanelTests(unittest.TestCase):
    def test_removed_mode_is_not_a_bridge_or_native_api(self):
        from nx.desktop import Bridge
        self.assertFalse(hasattr(Desktop,'switch_panel_mode'))
        self.assertFalse(hasattr(Bridge,'switch_panel_mode'))
    def test_legacy_setting_dropped_without_losing_other_choices(self):
        from nx.settings import normalize_settings
        for mode in ('compact','full','broken'):
            actual=normalize_settings({'panel_mode':mode,'notify_low':True,'appearance':'dark'})
            self.assertNotIn('panel_mode',actual)
            self.assertTrue(actual['notify_low']);self.assertEqual(actual['appearance'],'dark')
    def test_one_native_show_path(self):
        host=Desktop.__new__(Desktop);host.window=Mock();host._show_view=Mock()
        # Native window calls stay behind _show_view, which is mocked here.
        host.show()
        self.assertEqual(host._show_view.call_args.args[0],'home')
        self.assertNotIn('compact',str(host._show_view.call_args))

    def test_reset_expiry_reminders_are_fresh_available_and_once_per_stage(self):
        now=1900000000
        credit={'status':'available','expires_known':True,'expires_at':now+6*86400,
                'granted_at':now-86400,'reset_type':'codexRateLimits'}
        account={'email':'a@example.com','alias':'a','ok':True,'fetched_at':now,
                 'banked_resets':{'available_count':1,'items':[credit]}}
        seen={}
        for offset,expected in ((0,7),(3*86400+1,3),(5*86400+1,1)):
            account['fetched_at']=now+offset
            due=due_reset_expiry_notices([account],seen,now+offset)
            self.assertEqual([row[2] for row in due],[expected])
            seen[due[0][0]]=due[0][3]
            self.assertEqual(due_reset_expiry_notices([account],seen,now+offset),[])
        account['fetched_at']=now-1801
        self.assertEqual(due_reset_expiry_notices([account],{},now),[])
        account['fetched_at']=now
        for changed in ({'status':'redeemed'},{'expires_known':False},
                        {'expires_at':now-1},{'expires_at':None}):
            self.assertEqual(due_reset_expiry_notices([{
                **account,'banked_resets':{'available_count':1,'items':[{**credit,**changed}]}}],{},now),[])

if __name__=='__main__':unittest.main()
