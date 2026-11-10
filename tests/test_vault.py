"""Round-trip and hygiene checks for nx.account_vault.

The encryption path is Windows-only (DPAPI for the current user), which is also
where this program runs. These tests assert the properties that matter to the
program: the file on disk never contains a password or a secret in the clear,
a reload restores the same values, and a damaged file is refused instead of
silently becoming an empty roster.
"""
import json
import tempfile
import unittest
from pathlib import Path

from nx import totp
from nx.account_vault import Vault, VaultError

KEY = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
PASSWORD = 'Passw0rd-Letmein-42'


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'data' / 'vault.json'

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        vault = Vault(self.path)
        vault.put('Me@Example.com ', password=PASSWORD, secret=KEY)
        reloaded = Vault(self.path)
        entry = reloaded.get('me@example.com')
        self.assertIsNotNone(entry)
        self.assertEqual(entry.password, PASSWORD)
        self.assertEqual(entry.secret, KEY)
        self.assertEqual(entry.email, 'Me@Example.com')

    def test_disk_never_holds_plaintext(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD, secret=KEY)
        raw = self.path.read_bytes()
        self.assertNotIn(PASSWORD.encode(), raw)
        self.assertNotIn(KEY.encode(), raw)
        self.assertIn(b'chatgptnx_credential', raw)

    def test_public_view_hides_secrets(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD, secret=KEY)
        row = vault.public()[0]
        self.assertTrue(row['has_password'])
        self.assertTrue(row['has_secret'])
        self.assertNotIn('password', row)
        self.assertNotIn('secret', row)
        self.assertNotIn(PASSWORD, json.dumps(row))
        self.assertNotIn(KEY, json.dumps(row))

    def test_omitted_field_keeps_value(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD, secret=KEY)
        vault.put('a@b.com', label='主力号')
        entry = vault.get('a@b.com')
        self.assertEqual(entry.password, PASSWORD)
        self.assertEqual(entry.secret, KEY)
        self.assertEqual(entry.label, '主力号')

    def test_secret_is_normalised(self):
        vault = Vault(self.path)
        vault.put('a@b.com', secret=' gezd gnbv gy3t qojq gezd gnbv gy3t qojq ')
        self.assertEqual(vault.get('a@b.com').secret, KEY)

    def test_forget(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD)
        self.assertTrue(vault.forget('A@B.com'))
        self.assertFalse(vault.forget('a@b.com'))
        self.assertEqual(len(Vault(self.path)), 0)

    def test_record_login(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD)
        vault.record_login('a@b.com', 'phone')
        entry = Vault(self.path).get('a@b.com')
        self.assertEqual(entry.last_result, 'phone')
        self.assertGreater(entry.last_login_at, 0)

    def test_unknown_result_is_recorded_as_stopped(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD)
        vault.record_login('a@b.com', 'something_new')
        self.assertEqual(vault.get('a@b.com').last_result, 'stopped')

    def test_rejects_bad_email(self):
        vault = Vault(self.path)
        for bad in ('', 'nope', 'a b@c.com', None):
            with self.subTest(value=bad):
                with self.assertRaises(VaultError):
                    vault.put(bad, password=PASSWORD)

    def test_rejects_bad_secret(self):
        vault = Vault(self.path)
        with self.assertRaises(totp.TotpError):
            vault.put('a@b.com', secret='tooshort')

    def test_refuses_foreign_document(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from nx.credentials import write_credential_bytes
        write_credential_bytes(self.path, json.dumps({'schema': 'other'}).encode())
        with self.assertRaises(VaultError):
            Vault(self.path)

    def test_refuses_plaintext_json_on_disk(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({'schema': 'chatgptnx_vault', 'version': 1,
                                         'accounts': [{'email': 'a@b.com'}]}), encoding='utf-8')
        # A vault is always an encrypted envelope; an unencrypted roster must not
        # be adopted, or a downgrade could be used to seed credentials in the open.
        with self.assertRaises(VaultError):
            Vault(self.path)

    def test_failed_save_keeps_memory_and_disk_equal(self):
        vault = Vault(self.path)
        vault.put('a@b.com', password=PASSWORD)
        before = self.path.read_bytes()
        original = vault._save

        def boom():
            raise VaultError('无法保存账号库')
        vault._save = boom
        with self.assertRaises(VaultError):
            vault.put('c@d.com', password='x')
        vault._save = original
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(vault.get('c@d.com'))
        self.assertIsNotNone(vault.get('a@b.com'))


if __name__ == '__main__':
    unittest.main()