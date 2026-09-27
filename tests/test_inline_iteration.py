"""5.7.4 metadata patches, source contracts and desktop guard regressions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from test_core import Fixture

ROOT=Path(__file__).resolve().parents[1]

class MetadataPatchTests(Fixture):
    def test_alias_does_not_replace_saved_expiry(self):
        self.service.set_account_meta('a@example.com','Old','2027-01-15')
        result=self.service.update_account_meta('a@example.com',{'alias':' New '})
        self.assertEqual(result['meta'],{'alias':'New','subscription_date':'2027-01-15'})
    def test_date_does_not_replace_alias(self):
        self.service.set_account_meta('a@example.com','My account',None)
        result=self.service.update_account_meta('a@example.com',{'subscription_date':'2027-01-15'})
        self.assertEqual(result['meta'],{'alias':'My account','subscription_date':'2027-01-15'})
    def test_date_clear_is_explicit_and_retains_alias(self):
        self.service.set_account_meta('a@example.com','My account','2027-01-15')
        result=self.service.update_account_meta('a@example.com',{'subscription_date':None})
        self.assertEqual(result['meta'],{'alias':'My account','subscription_date':None})
    def test_blank_nickname_is_a_valid_clear(self):
        self.service.set_account_meta('a@example.com','Old','2027-01-15')
        result=self.service.update_account_meta('a@example.com',{'alias':''})
        self.assertEqual(result['meta']['alias'],'')
        self.assertEqual(result['meta']['subscription_date'],'2027-01-15')
    def test_invalid_shapes_and_fields_do_not_mutate(self):
        before=self.service.state.get('account_meta')
        for changes in [None,[],{}, {'plan':'pro'}, {'alias':'valid','unexpected':1}]:
            with self.subTest(changes=changes):
                self.assertFalse(self.service.update_account_meta('a@example.com',changes)['ok'])
                self.assertEqual(self.service.state.get('account_meta'),before)
    def test_malformed_alias_does_not_mutate(self):
        for alias in [False,24,[],None,'x'*25,'x\ny','secret\x00draft']:
            with self.subTest(alias=alias):
                self.assertFalse(self.service.update_account_meta('a@example.com',{'alias':alias})['ok'])
    def test_invalid_dates_do_not_mutate(self):
        for value in ['2027-02-30','20270115','2027-1-1','2027-01-15T10:00:00',False,0,{},'0000-01-01']:
            with self.subTest(value=value):
                self.assertFalse(self.service.update_account_meta('a@example.com',{'subscription_date':value})['ok'])
    def test_nonexistent_account_rejected(self):
        self.assertFalse(self.service.update_account_meta('gone@example.com',{'alias':'x'})['ok'])
    def test_concurrent_different_fields_both_persist(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(self.service.update_account_meta,'a@example.com',change) for change in [{'alias':'Concurrent'},{'subscription_date':'2028-02-29'}]]
            self.assertTrue(all(j.result()['ok'] for j in jobs))
        self.assertEqual(self.service.state.get('account_meta')['a@example.com'],{'alias':'Concurrent','subscription_date':'2028-02-29'})
    def test_disk_error_keeps_memory_and_both_fields(self):
        self.service.set_account_meta('a@example.com','Old','2027-01-15')
        before=self.service.state.get('account_meta')
        with patch('nx.storage.atomic_bytes',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.service.update_account_meta('a@example.com',{'alias':'New'})
        self.assertEqual(self.service.state.get('account_meta'),before)
    def test_reloading_reads_saved_partial_patch(self):
        from nx.storage import State
        self.service.update_account_meta('a@example.com',{'alias':'Persisted'})
        self.service.update_account_meta('a@example.com',{'subscription_date':'2028-02-29'})
        self.assertEqual(State(self.paths).get('account_meta')['a@example.com'],{'alias':'Persisted','subscription_date':'2028-02-29'})
    def test_return_value_cannot_mutate_state(self):
        result=self.service.update_account_meta('a@example.com',{'alias':'Persisted'})
        result['meta']['alias']='Outside mutation'
        self.assertEqual(self.service.state.get('account_meta')['a@example.com']['alias'],'Persisted')

class InlineSourceContracts(unittest.TestCase):
    def test_no_experimental_layout_files_in_source_tree(self):
        self.assertFalse((ROOT/'tools/proposals').exists())
        self.assertFalse((ROOT/'docs/proposals').exists())
    def test_native_bridge_exposes_partial_metadata_api(self):
        from nx.desktop import Bridge
        self.assertTrue(callable(Bridge.update_account_meta))
    def test_native_resume_does_not_touch_composer(self):
        ps=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('Send-ResumeMessage',ps)
        self.assertNotIn('Find-Composer',ps)
        self.assertNotIn('$unique[0]',ps)
    def test_input_mutating_fallback_still_absent(self):
        ps=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
        for forbidden in ['.SetValue(', 'SendKeys(', 'Set-Clipboard', 'Start-Process']:
            self.assertNotIn(forbidden,ps)
    def test_controller_has_no_obsolete_editor_or_settings_subpage_views(self):
        source=(ROOT/'src/ui/app.js').read_text(encoding='utf-8').split('function renderSheet(')[1].split('const inlineWrites=')[0]
        for route in ['edit','automation','notifications','relay-accounts','resume-message','hotkeys','archives']:
            self.assertNotIn("case '"+route+"':",source)
    def test_settings_list_is_separate_from_switcher_information(self):
        settings=(ROOT/'src/ui/views/settings.js').read_text(encoding='utf-8')
        relay=settings.split('function relay(c)')[1].split('function hotkeys(c)')[0]
        self.assertNotIn('accountChoice',relay)
        self.assertNotIn('quotaSummary',relay)
        self.assertIn('quotaSummary(account)',(ROOT/'src/ui/components.js').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
