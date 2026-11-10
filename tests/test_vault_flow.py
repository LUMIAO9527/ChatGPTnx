import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nx.account_vault import Vault, parse_line, material_fields
from nx.core import Service
from test_authenticator_import import transfer_uri, SECRET


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
        s._authenticator_pending = None
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

    def test_phone_transfer_maps_confirmed_account_label(self):
        self.service.vault.put('a@example.com', label='GPT-001', password='saved')
        result = self.service.authenticator_preview({'text': transfer_uri('GPT-001')})
        self.assertEqual(result['rows'][0]['email'], 'a@example.com')

    def test_phone_transfer_commit_preserves_saved_password(self):
        s = self.service
        s.vault.put('a@example.com', label='GPT-001', password='saved')
        preview = s.authenticator_preview({'text': transfer_uri()})
        result = s.authenticator_commit({'token': preview['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})
        self.assertEqual(result, {'ok': True, 'imported': 1})
        saved = Vault(s.vault.path).get('a@example.com')
        self.assertEqual((saved.password, saved.secret, saved.label), ('saved', SECRET, 'GPT-001'))
        self.assertIsNone(s._authenticator_pending)

    def test_cancelled_or_expired_phone_transfer_cannot_be_committed(self):
        s = self.service
        result = s.authenticator_preview({'text': transfer_uri()})
        s.authenticator_cancel()
        self.assertFalse(s.authenticator_commit({'token': result['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})['ok'])
        result = s.authenticator_preview({'text': transfer_uri()})
        s._authenticator_pending['expires_at'] = 0
        self.assertFalse(s.authenticator_commit({'token': result['token'], 'selections': [{'id': '0', 'email': 'a@example.com'}]})['ok'])

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
