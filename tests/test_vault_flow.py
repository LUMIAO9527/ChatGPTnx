import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nx.account_vault import Vault, parse_line, material_fields
from nx.core import Service
from test_authenticator_import import qr_image, transfer_uri, SECRET


class VaultFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service.__new__(Service)
        s = self.service
        s.vault = Vault(Path(self.temp.name) / 'vault.json')
        s.vault_error = ''
        s.lock = threading.RLock()
        s.notify = Mock()
        s._mfa_pending = {}
        s._authenticator_pending = {}
        s.accounts = SimpleNamespace(all=lambda: ['a@example.com', 'b@example.com'], current=lambda: 'a@example.com')
        s.desktop_transitioning = lambda: False

    def test_four_parts_and_combined_link_preserve_account_material(self):
        entry = parse_line('a@example.com----Password----redeem-123----https://example.com/redeem')
        self.assertEqual(entry['exchange_code'], 'redeem-123')
        self.assertEqual(entry['exchange_url'], 'https://example.com/redeem')
        self.assertNotIn('secret', entry)
        combined = parse_line('a@example.com----Password----https://example.com/get?code=123')
        self.assertIn('code=123', combined['exchange_url'])

    def test_url_seed_is_parsed_locally(self):
        fields = material_fields('https://example.com/totp?seed=' + SECRET)
        self.assertEqual(fields['secret'], SECRET)

    def test_two_columns_keep_password_even_when_it_looks_like_base32(self):
        self.assertEqual(parse_line('a@example.com----' + SECRET)['password'], SECRET)

    def test_import_keeps_existing_secret_when_omitted(self):
        s = self.service
        s.vault.put('a@example.com', secret=SECRET, label='GPT-001')
        result = s.vault_import({'text': 'a@example.com----UpdatedPassword'})
        self.assertTrue(result['ok'])
        self.assertEqual(s.vault.get('a@example.com').secret, SECRET)
        self.assertEqual(s.vault.get('a@example.com').label, 'GPT-001')

    def test_batch_write_failure_restores_entire_vault(self):
        s = self.service
        s.vault.put('a@example.com', password='old')
        before = s.vault.path.read_bytes()
        with patch.object(s.vault, '_save', side_effect=OSError('fixture')):
            result = s.vault_import({'text': 'a@example.com----new\nb@example.com----new'})
        self.assertFalse(result['ok'])
        self.assertEqual(s.vault.path.read_bytes(), before)
        self.assertEqual(s.vault.get('a@example.com').password, 'old')
        self.assertIsNone(s.vault.get('b@example.com'))

    def test_replacing_a_saved_secret_resets_its_enrolment_status(self):
        s = self.service
        s.vault.put('a@example.com', secret='JBSWY3DPEHPK3PXP', secret_source='enrolled', migrated_at=123)
        s.vault.put('a@example.com', secret=SECRET)
        entry = s.vault.get('a@example.com')
        self.assertEqual(entry.secret_source, 'imported')
        self.assertEqual(entry.migrated_at, 0)

    def test_password_edit_clears_outdated_login_result(self):
        s = self.service
        s.vault.put('a@example.com', password='old')
        s.vault.record_login('a@example.com', 'wrong_password')
        self.assertTrue(s.vault_save({'email': 'a@example.com', 'password': 'new'})['ok'])
        self.assertEqual(s.vault.get('a@example.com').last_result, '')

    def test_phone_transfer_preview_maps_email_and_never_returns_seed(self):
        result = self.service.authenticator_preview({'text': transfer_uri()})
        self.assertTrue(result['ok'])
        self.assertEqual(result['rows'][0]['email'], 'a@example.com')
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertIsNone(self.service.vault.get('a@example.com'))

    def test_phone_transfer_requires_an_email_even_for_saved_aliases(self):
        self.service.vault.put('a@example.com', label='GPT-001', password='saved')
        result = self.service.authenticator_preview({'text': transfer_uri('GPT-001')})
        self.assertEqual(result['rows'], [{'source': 'GPT-001', 'problem': '二维码未标邮箱'}])

    def test_phone_transfer_commit_preserves_saved_password(self):
        s = self.service
        s.vault.put('a@example.com', label='GPT-001', password='saved')
        preview = s.authenticator_preview({'text': transfer_uri()})
        result = s.authenticator_commit({'token': preview['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})
        self.assertEqual(result, {'ok': True, 'imported': 1})
        saved = Vault(s.vault.path).get('a@example.com')
        self.assertEqual((saved.password, saved.secret, saved.label), ('saved', SECRET, 'GPT-001'))
        self.assertEqual(s._authenticator_pending, {})

    def test_cancelled_or_expired_phone_transfer_cannot_be_committed(self):
        s = self.service
        result = s.authenticator_preview({'text': transfer_uri()})
        s.authenticator_cancel()
        self.assertFalse(s.authenticator_commit({'token': result['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})['ok'])
        result = s.authenticator_preview({'text': transfer_uri()})
        s._authenticator_pending[result['token']]['expires_at'] = 0
        self.assertFalse(s.authenticator_commit({'token': result['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})['ok'])

    def test_selected_google_export_rows_are_committed_atomically(self):
        s = self.service
        s.vault.put('a@example.com', password='old')
        with (qr_image(transfer_uri('OpenAI:A@EXAMPLE.COM', batch_size=2, version=2)) as first,
              qr_image(transfer_uri('OpenAI:b@example.com', batch_size=2, batch_index=1, version=2)) as second):
            self.assertFalse(s.authenticator_preview({'paths': [first]})['ok'])
            result = s.authenticator_preview({'paths': [second, first]})
        self.assertEqual([row['email'] for row in result['rows']], ['a@example.com', 'b@example.com'])
        selections = [{key: row[key] for key in ('email', 'id')} for row in result['rows']]
        self.assertIsNone(s.vault.get('b@example.com'))
        before = s.vault.path.read_bytes()
        request = {'token': result['token'], 'selections': selections}
        swapped = {**request, 'selections': [selections[0], {**selections[1], 'email': 'a@example.com'}]}
        self.assertFalse(s.authenticator_commit(swapped)['ok'])
        with patch.object(s.vault, '_save', side_effect=OSError('fixture')):
            self.assertFalse(s.authenticator_commit(request)['ok'])
        self.assertEqual(s.vault.path.read_bytes(), before)
        self.assertFalse(s.vault.get('a@example.com').secret)
        self.assertIsNone(s.vault.get('b@example.com'))
        self.assertEqual(s.authenticator_commit(request), {'ok': True, 'imported': 2})
        saved = Vault(s.vault.path)
        self.assertEqual(saved.get('a@example.com').password, 'old')
        self.assertEqual(saved.get('b@example.com').secret, SECRET)

    def test_batch_cancel_does_not_cancel_a_new_review(self):
        s = self.service
        first = s.authenticator_preview({'text': transfer_uri()})
        second = s.authenticator_preview({'text': transfer_uri('OpenAI:b@example.com')})
        s.authenticator_cancel(first['token'])
        self.assertEqual(s.authenticator_commit({'token': second['token'], 'selections': [
            {'id': '0', 'email': 'b@example.com'}
        ]}), {'ok': True, 'imported': 1})
        self.assertIsNone(s.vault.get('a@example.com'))

    def test_conflicting_qrs_for_the_same_email_are_skipped(self):
        s = self.service
        with (qr_image(transfer_uri('a@example.com')) as first,
              qr_image(transfer_uri('A@EXAMPLE.COM', secret=b'0123456789abcdefghij')) as second):
            preview = s.authenticator_preview({'paths': [first, second]})
        self.assertEqual(len(preview['rows']), 1)
        self.assertEqual(preview['rows'][0]['problem'], '同一邮箱有多个验证器')
        self.assertFalse(s.authenticator_commit({'token': preview['token'], 'selections': [
            {'id': '0', 'email': 'a@example.com'}
        ]})['ok'])

    def test_single_qr_binds_selected_saved_account_and_preserves_material(self):
        s = self.service
        s.vault.put('b@example.com', password='saved', recovery_codes='synthetic recovery')
        with qr_image(transfer_uri('OpenAI:B@EXAMPLE.COM')) as image:
            self.assertFalse(s.mfa_preview_images({'email': 'a@example.com', 'paths': [image]})['ok'])
            preview = s.mfa_preview_images({'email': 'b@example.com', 'paths': [image]})
        self.assertTrue(preview['account_matched'])
        self.assertRegex(preview['code'], r'^\d{6}$')
        self.assertNotIn(SECRET, json.dumps(s.mfa_public()))
        request = {'email': 'b@example.com', 'token': preview['token'], 'confirmed': True}
        self.assertFalse(s.mfa_commit({**request, 'email': 'a@example.com'})['ok'])
        self.assertTrue(s.mfa_commit(request)['ok'])
        self.assertEqual(s.accounts.current(), 'a@example.com')
        entry = Vault(s.vault.path).get('b@example.com')
        self.assertEqual((entry.secret, entry.password, entry.recovery_codes), (SECRET, 'saved', 'synthetic recovery'))

    def test_screenshot_without_email_can_only_be_reviewed_for_a_saved_account(self):
        s = self.service
        with qr_image(transfer_uri('OpenAI:verifier')) as image:
            self.assertFalse(s.mfa_preview_images({'email': 'unknown@example.com', 'paths': [image]})['ok'])
            first = s.mfa_preview_images({'email': 'b@example.com', 'paths': [image]})
            second = s.mfa_preview_images({'email': 'b@example.com', 'paths': [image]})
        self.assertFalse(first['account_matched'])
        s.mfa_cancel({'email': 'b@example.com', 'token': first['token']})
        self.assertEqual([row['token'] for row in s.mfa_public()], [second['token']])

    def test_enrolment_waits_for_service_confirmation_and_current_account(self):
        s = self.service
        s.vault.put('a@example.com', password='saved', secret='JBSWY3DPEHPK3PXP')
        preview = s.mfa_preview({'email': 'a@example.com', 'secret': SECRET})
        self.assertTrue(preview['ok'])
        self.assertNotIn(SECRET, json.dumps(preview))
        request = {'email': 'a@example.com', 'token': preview['token']}
        self.assertFalse(s.mfa_commit(request)['ok'])
        s.accounts.current = lambda: 'b@example.com'
        self.assertFalse(s.mfa_commit({**request, 'confirmed': True})['ok'])
        s.accounts.current = lambda: 'a@example.com'
        self.assertTrue(s.mfa_commit({**request, 'confirmed': True, 'recovery_codes': 'RECOVERY'})['ok'])
        entry = s.vault.get('a@example.com')
        self.assertEqual((entry.secret, entry.password, entry.recovery_codes), (SECRET, 'saved', 'RECOVERY'))
