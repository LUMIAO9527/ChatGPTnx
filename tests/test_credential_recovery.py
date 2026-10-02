"""Rollback fixtures; never operate on an installed app or actual credentials."""
from contextlib import nullcontext
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('credential_recovery', ROOT/'tools/credential_recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
from nx.credentials import CredentialProtectionError, write_credential_bytes


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI integration')
class RollbackTests(unittest.TestCase):
    def setUp(self):
        base = ROOT/'_wip'/'rollback-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.home = Path(self.temp.name)
        self.snapshot = self.home/'snapshots'/'recovery'/'fixture.json'
        self.raw = b'{"tokens":{"access_token":"synthetic-rollback"}}\r\n'
        write_credential_bytes(self.snapshot, self.raw)
        self.auth = self.home/'auth.json'
        self.auth.write_bytes(b'official-fixture')

    def tearDown(self):
        self.temp.cleanup()

    def test_rollback_exact_bytes_idempotent_auth_untouched(self):
        os.utime(self.snapshot, ns=(1700000000000000000,1700000000000000000))
        with patch.object(recovery, 'application_stopped', return_value=nullcontext()):
            result = recovery.decrypt_for_rollback(self.home)
            self.assertEqual(result['restored'], 1)
            self.assertEqual(self.snapshot.read_bytes(), self.raw)
            self.assertEqual(self.snapshot.stat().st_mtime_ns,1700000000000000000)
            self.assertEqual(self.auth.read_bytes(), b'official-fixture')
            self.assertEqual(recovery.decrypt_for_rollback(self.home)['restored'], 0)

    def test_invalid_backup_prevents_all_plaintext_restoration(self):
        original = self.snapshot.read_bytes()
        (self.snapshot.parent/'broken.json').write_bytes(b'{broken')
        with patch.object(recovery, 'application_stopped', return_value=nullcontext()):
            with self.assertRaises(CredentialProtectionError):
                recovery.decrypt_for_rollback(self.home)
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_running_application_guard_preserves_encrypted_snapshot(self):
        original = self.snapshot.read_bytes()
        with patch.object(recovery, 'application_stopped', side_effect=CredentialProtectionError('busy')):
            with self.assertRaises(CredentialProtectionError):
                recovery.decrypt_for_rollback(self.home)
        self.assertEqual(self.snapshot.read_bytes(), original)
