"""Offline DPAPI/ACL and transaction checks using synthetic credentials only."""
from pathlib import Path
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nx.credentials import (CredentialProtectionError, assert_safe_path, credential_store_lock,
                            protect_store, read_credential_bytes, write_credential_bytes, _current_sid)
from nx.storage import Accounts, identity


def fixture(email='fixture@example.com'):
    payload = base64.urlsafe_b64encode(json.dumps({'email': email}).encode()).decode().rstrip('=')
    return b'\xef\xbb\xbf' + json.dumps({'tokens': {'id_token': 'fixture.' + payload + '.unsigned',
                         'account_id': 'synthetic-account', 'refresh_token': 'synthetic-private-fixture'}},
                        indent=2).encode() + b'\r\n'


@unittest.skipUnless(os.name == 'nt', 'Windows DPAPI and ACL integration')
class CredentialTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / '_wip' / 'credential-tests'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.paths = SimpleNamespace(snapshots=self.root/'snapshots', data=self.root/'_data',
                                     order=self.root/'accounts.txt')
        self.paths.data.mkdir()
        self.raw = fixture()

    def tearDown(self):
        self.temp.cleanup()

    def ps(self, code):
        env = dict(os.environ, NX_TEST_ROOT=str(self.root), NX_TEST_SCRIPT=str(ROOT/'src/switch_account.ps1'))
        command = base64.b64encode(code.encode('utf-16le')).decode()
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', command],
                                capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def functions(self):
        return r'''
$ErrorActionPreference='Stop'
$Utf8=New-Object Text.UTF8Encoding($false)
$SnapshotDir=Join-Path $env:NX_TEST_ROOT 'snapshots'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:NX_TEST_SCRIPT,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Helper parse failure'}
$ast.FindAll({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst]},$true) | ForEach-Object {Invoke-Expression $_.Extent.Text}
'''

    def test_roundtrip_is_encrypted_and_metadata_remains_compatible(self):
        path = self.paths.snapshots/'fixture@example.com.json'
        write_credential_bytes(path, self.raw)
        self.assertNotIn(b'synthetic-private-fixture', path.read_bytes())
        self.assertEqual(read_credential_bytes(path), self.raw)
        self.assertEqual(identity(path), ('fixture@example.com', 'synthetic-account'))
        first = path.read_bytes()
        write_credential_bytes(path, self.raw)
        self.assertNotEqual(path.read_bytes(), first)

    def test_migration_preserves_timestamps_auth_and_all_backups(self):
        targets = [self.paths.snapshots/'fixture@example.com.json',
                   self.paths.snapshots/'removed'/'old.json', self.paths.snapshots/'recovery'/'auth-recovery-old.json']
        for path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.raw)
            os.utime(path, ns=(1700000000000000000, 1700000000000000000))
        auth = self.root/'auth.json'
        auth.write_bytes(self.raw)
        self.paths.order.write_text('fixture@example.com\n')
        (self.paths.data/'run.log').write_text('synthetic old diagnostic')
        self.assertEqual(protect_store(self.paths), {'migrated': 3, 'protected': 3})
        for path in targets:
            self.assertEqual(path.stat().st_mtime_ns, 1700000000000000000)
            self.assertEqual(read_credential_bytes(path), self.raw)
            self.assertNotIn(b'synthetic-private-fixture', path.read_bytes())
        self.assertEqual(auth.read_bytes(), self.raw)
        self.assertEqual(protect_store(self.paths)['migrated'], 0)
        sid = _current_sid()
        code = "$ErrorActionPreference='Stop'; $paths=@('snapshots','snapshots/fixture@example.com.json','_data','_data/run.log','accounts.txt'); foreach($p in $paths) { $full=Join-Path $env:NX_TEST_ROOT $p; $a=if([IO.Directory]::Exists($full)){[IO.Directory]::GetAccessControl($full)}else{[IO.File]::GetAccessControl($full)}; if(-not $a.AreAccessRulesProtected){throw 'Unprotected DACL'}; $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | ForEach-Object {$_.IdentityReference.Value} }"
        found = self.ps(code).splitlines()
        self.assertEqual(set(found), {sid, 'S-1-5-18', 'S-1-5-32-544'})
        self.assertEqual(len(found), 15)

    def test_failed_encryption_or_replace_keeps_exact_original(self):
        path = self.paths.snapshots/'original.json'
        path.parent.mkdir()
        path.write_bytes(self.raw)
        with patch('nx.credentials._dpapi', side_effect=CredentialProtectionError('Synthetic failure')):
            with self.assertRaises(CredentialProtectionError):
                protect_store(self.paths)
        self.assertEqual(path.read_bytes(), self.raw)
        with patch('nx.credentials.os.replace', side_effect=PermissionError('Synthetic failure')):
            with self.assertRaises(PermissionError):
                write_credential_bytes(path, self.raw)
        self.assertEqual(path.read_bytes(), self.raw)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_accounts_roster_create_and_replace_remain_private(self):
        accounts = Accounts(self.paths)
        for email in ('first@example.com', 'replacement@example.com'):
            accounts.write([email])
            self.assertIn(email, self.paths.order.read_text(encoding='utf-8'))
            code = r'''
$ErrorActionPreference='Stop'
$acl=[IO.File]::GetAccessControl((Join-Path $env:NX_TEST_ROOT 'accounts.txt'))
if(-not $acl.AreAccessRulesProtected){throw 'Roster DACL inherited'}
$acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | ForEach-Object {$_.IdentityReference.Value}
'''
            found = self.ps(code).splitlines()
            self.assertEqual(set(found), {_current_sid(), 'S-1-5-18', 'S-1-5-32-544'})
            self.assertEqual(len(found), 3)

    def test_corrupt_envelope_fails_closed_before_migrating_other_files(self):
        self.paths.snapshots.mkdir()
        original = self.paths.snapshots/'original.json'
        original.write_bytes(self.raw)
        broken = self.paths.snapshots/'broken.json'
        broken.write_text('{"chatgptnx_credential":1,"protection":"dpapi-current-user","data":"!!!"}')
        with self.assertRaises(CredentialProtectionError):
            protect_store(self.paths)
        self.assertEqual(original.read_bytes(), self.raw)

    def test_lock_excludes_python_and_powershell(self):
        with credential_store_lock(self.paths.snapshots):
            with self.assertRaises(CredentialProtectionError):
                protect_store(self.paths)
            result = self.ps("$ErrorActionPreference='Stop'; try { $s=[IO.File]::Open((Join-Path $env:NX_TEST_ROOT 'snapshots/.credentials.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); $s.Dispose(); throw 'Unexpected lock acquisition' } catch [IO.IOException] { 'busy' }")
            self.assertEqual(result, 'busy')

    def test_hard_link_is_rejected(self):
        original = self.root/'original.json'
        original.write_bytes(self.raw)
        linked = self.root/'linked.json'
        os.link(original, linked)
        with self.assertRaises(CredentialProtectionError):
            assert_safe_path(linked)

    def test_python_powershell_interop_and_exact_rollback_bytes(self):
        py_path = self.paths.snapshots/'python.json'
        write_credential_bytes(py_path, self.raw)
        (self.root/'auth.json').write_bytes(self.raw)
        script = r'''
$ErrorActionPreference='Stop'
$Utf8=New-Object Text.UTF8Encoding($false)
$SnapshotDir=Join-Path $env:NX_TEST_ROOT 'snapshots'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:NX_TEST_SCRIPT,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Helper parse failure'}
$ast.FindAll({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst]},$true) | ForEach-Object {Invoke-Expression $_.Extent.Text}
$python=Join-Path $SnapshotDir 'python.json'
$plain=Join-Path $env:NX_TEST_ROOT 'auth.json'
if([Convert]::ToBase64String((Read-CredentialBytes $python)) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($plain))){throw 'Python decrypt mismatch'}
$backup=Join-Path $SnapshotDir 'recovery/fixture.json'
Write-ProtectedCredential ([IO.File]::ReadAllBytes($plain)) $backup
Atomic-Copy $backup (Join-Path $env:NX_TEST_ROOT 'restored.json')
'ok'
'''
        self.assertEqual(self.ps(script), 'ok')
        self.assertEqual(read_credential_bytes(self.paths.snapshots/'recovery'/'fixture.json'), self.raw)
        self.assertEqual((self.root/'restored.json').read_bytes(), self.raw)

    def test_powershell_rejects_hardlink_without_changing_target(self):
        original = self.root/'original.json'
        original.write_bytes(self.raw)
        os.link(original, self.root/'linked.json')
        code = self.functions() + r'''
$blocked=$false
try { Protect-Path (Join-Path $env:NX_TEST_ROOT 'linked.json') }
catch { if($_.Exception.Message -like '*hard links*'){$blocked=$true}else{throw} }
if(-not $blocked){throw 'Hard link was accepted'}
'blocked'
'''
        self.assertEqual(self.ps(code), 'blocked')
        self.assertEqual(original.read_bytes(), self.raw)

    def test_powershell_retries_transient_reader_and_keeps_atomic_bytes(self):
        path = self.root/'auth.json'
        path.write_bytes(self.raw)
        code = self.functions() + r'''
$path=Join-Path $env:NX_TEST_ROOT 'auth.json'
$global:reader=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
$global:retries=0
function Start-Sleep { param([int]$Milliseconds) $global:retries++; $global:reader.Dispose() }
try { Atomic-WriteBytes ([Text.Encoding]::UTF8.GetBytes('synthetic replacement')) $path }
finally { $global:reader.Dispose() }
if($global:retries -ne 1){throw 'Replacement did not retry exactly once'}
'ok'
'''
        self.assertEqual(self.ps(code), 'ok')
        self.assertEqual(path.read_bytes(), b'synthetic replacement')

    def test_full_transactions_never_rollback_into_a_running_app(self):
        # Execute the real transaction body; only desktop process operations
        # are replaced. Every credential and output stays in this fixture root.
        target_raw = fixture('target@example.com')
        updated_raw = self.raw.replace(b'synthetic-private-fixture', b'synthetic-renewed-fixture')
        auth = self.root/'auth.json'
        (self.root/'updated.json').write_bytes(updated_raw)
        write_credential_bytes(self.paths.snapshots/'target@example.com.json', target_raw)
        cases = [('initial_stop_failure', updated_raw, 1, 0),
                 ('rollback_stop_failure', target_raw, 2, 1),
                 ('rollback_success', self.raw, 2, 2),
                 ('snapshot_failure', self.raw, 1, 1)]
        for scenario, expected, stops, starts in cases:
            with self.subTest(scenario=scenario):
                auth.write_bytes(self.raw)
                code = r'''
$ErrorActionPreference='Stop'
$global:stops=0; $global:starts=0
$global:scenario='SCENARIO'
$mock=@'
function Stop-App {
    $global:stops++
    if($global:scenario -eq 'initial_stop_failure') {
        [IO.File]::WriteAllBytes($AuthFile,[IO.File]::ReadAllBytes((Join-Path $env:NX_TEST_ROOT 'updated.json')))
        throw 'Synthetic initial stop failure'
    }
    if($global:scenario -eq 'rollback_stop_failure' -and $global:stops -eq 2){throw 'Synthetic rollback stop failure'}
}
function Start-App {
    $global:starts++
    if($global:scenario -in @('rollback_stop_failure','rollback_success') -and $global:starts -eq 1){throw 'Synthetic launch failure'}
}
if($global:scenario -eq 'snapshot_failure'){function Save-Snapshot {throw 'Synthetic snapshot failure'}}
'@
$source=[IO.File]::ReadAllText($env:NX_TEST_SCRIPT)
$offset=$source.IndexOf('if ($List -or')
if($offset -lt 0){throw 'Transaction boundary missing'}
$source=$source.Insert($offset,$mock+[Environment]::NewLine)
$failed=$false
try { & ([scriptblock]::Create($source)) -To 'target@example.com' -AuthFile (Join-Path $env:NX_TEST_ROOT 'auth.json') -SnapshotDir (Join-Path $env:NX_TEST_ROOT 'snapshots') }
catch {$failed=$true}
if(-not $failed){throw 'Failure was not reported'}
@{stops=$global:stops; starts=$global:starts} | ConvertTo-Json -Compress
'''.replace('SCENARIO', scenario)
                result = json.loads(self.ps(code).splitlines()[-1])
                self.assertEqual(result, {'stops': stops, 'starts': starts})
                self.assertEqual(auth.read_bytes(), expected)
        backups = list((self.paths.snapshots/'recovery').glob('*.json'))
        self.assertEqual(len(backups), 4)
        for backup in backups:
            self.assertNotIn(b'synthetic-private-fixture', backup.read_bytes())


if __name__ == '__main__':
    unittest.main()
