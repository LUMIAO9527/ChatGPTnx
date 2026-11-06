"""Run the real Windows helper against isolated desktop/account fixtures."""
from pathlib import Path
import base64
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'src/switch_account.ps1'
OLD = hashlib.sha256(b'["old-user","old-account"]').hexdigest()
NEW = hashlib.sha256(b'["new-user","new-account"]').hexdigest()
PROJECT = '11111111-1111-4111-8111-111111111111'
THREAD = '22222222-2222-4222-8222-222222222222'
HOST = 'local:C:\\fixture\\.codex'


def credential(user, account, email):
    claims = {'email': email, 'https://api.openai.com/auth': {
        'chatgpt_user_id': user, 'chatgpt_account_id': account}}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return json.dumps({'tokens': {'id_token': 'fixture.'+encoded+'.unsigned',
                                 'account_id': account}}).encode()


def workspace():
    return {'local-projects': {PROJECT: {'id': PROJECT, 'name': 'Research',
            'rootPaths': ['D:\\fixture\\research'], 'createdAt': 1, 'updatedAt': 2}},
        'project-order': [PROJECT], 'selected-project': {'projectKind': 'local', 'projectId': PROJECT},
        'thread-project-assignments': {THREAD: {'projectKind': 'local', 'projectId': PROJECT}},
        'thread-project-membership-host-ids': {THREAD: 'local'},
        'app-server-project-id-by-legacy-project-id-by-host': {HOST: {PROJECT: 'server-project'}},
        'app-server-projects-migration-by-host': {HOST: {'version': 1, 'projectsMigrated': True,
            'threadAssignmentsMigrated': False, 'pendingThreadAssignmentIds': [THREAD]}}}


def document(active=True):
    result = {'electron-account-renderer-state-v1': {'owner': OLD, 'inactive': {}},
              'electron-persisted-atom-state': {'private-draft': 'old-account-private',
                  'sidebar-project-expanded-v1-codex:'+PROJECT: True},
              'unrelated-global': {'exact': ['preserve', 7, False]}}
    if active:
        result.update(workspace())
    else:
        result['electron-account-renderer-state-v1']['owner'] = NEW
        result['electron-account-renderer-state-v1']['inactive'][OLD] = {
            'globals': workspace(), 'atoms': {'private-draft': 'old-account-private'}}
    return result


@unittest.skipUnless(os.name == 'nt', 'Windows desktop-state transactions')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT / '_wip/workspace-tests'
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.root = Path(self.temp.name)
        self.state = self.root / '.codex-global-state.json'
        self.auth = self.root / 'auth.json'
        self.snapshots = self.root / 'snapshots'
        self.auth.write_bytes(credential('old-user', 'old-account', 'old@example.com'))

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, code, *, success=True):
        preamble = r'''
$ErrorActionPreference='Stop'
$Utf8=New-Object Text.UTF8Encoding($false)
$AuthFile=Join-Path $env:NX_TEST_ROOT 'auth.json'
$SnapshotDir=Join-Path $env:NX_TEST_ROOT 'snapshots'
$DataDir=Join-Path $SnapshotDir 'recovery'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:NX_TEST_SCRIPT,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Helper parse failure'}
$ast.FindAll({param($a) $a -is [Management.Automation.Language.FunctionDefinitionAst]},$true) | ForEach-Object {Invoke-Expression $_.Extent.Text}
'''
        encoded = base64.b64encode((preamble+code).encode('utf-16le')).decode()
        env = dict(os.environ, NX_TEST_ROOT=str(self.root), NX_TEST_SCRIPT=str(SCRIPT))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
            '-EncodedCommand', encoded], capture_output=True, text=True, env=env, timeout=35)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stdout.strip()

    def transform(self, doc, owner=NEW):
        self.state.write_text(json.dumps(doc), encoding='utf-8')
        output = self.invoke("$doc=Get-Content -LiteralPath (Join-Path $env:NX_TEST_ROOT '.codex-global-state.json') -Raw | ConvertFrom-Json; "
                             f"$r=Workspace-Update $doc '{owner}'; if($null -eq $r){{'null'}}else{{$r|ConvertTo-Json -Depth 100 -Compress}}")
        return json.loads(output)

    def test_new_account_keeps_local_layout_without_copying_account_atoms(self):
        doc = document()
        result = self.transform(doc)
        target = result['electron-account-renderer-state-v1']['inactive'][NEW]
        self.assertEqual(target['globals']['local-projects'], workspace()['local-projects'])
        self.assertEqual(target['globals']['thread-project-assignments'], workspace()['thread-project-assignments'])
        self.assertNotIn('private-draft', target['atoms'])
        self.assertTrue(target['atoms']['sidebar-project-expanded-v1-codex:'+PROJECT])
        self.assertEqual(result['electron-persisted-atom-state'], doc['electron-persisted-atom-state'])
        self.assertEqual(result['unrelated-global'], doc['unrelated-global'])
        self.assertEqual(result['electron-account-renderer-state-v1']['owner'], OLD)

    def test_current_empty_account_recovers_the_one_original_layout(self):
        doc = document(False)
        result = self.transform(doc)
        self.assertEqual(result['local-projects'], workspace()['local-projects'])
        self.assertEqual(result['thread-project-assignments'], workspace()['thread-project-assignments'])
        self.assertEqual(result['electron-account-renderer-state-v1'], doc['electron-account-renderer-state-v1'])

    def test_existing_target_preferences_and_other_account_remain_intact(self):
        doc = document()
        saved = {'atoms': {'appearance': 'light', 'private-draft': 'target-private'},
                 'globals': {'custom-global': 17}}
        doc['electron-account-renderer-state-v1']['inactive'][NEW] = saved
        doc['electron-account-renderer-state-v1']['inactive']['a'*64] = copy.deepcopy(saved)
        result = self.transform(doc)
        self.assertEqual(result['electron-account-renderer-state-v1']['inactive'][NEW]['atoms']['private-draft'], 'target-private')
        self.assertEqual(result['electron-account-renderer-state-v1']['inactive']['a'*64], saved)

    def test_remote_project_and_remote_thread_do_not_cross_accounts(self):
        doc = document()
        remote = 'remote-project'
        doc['local-projects'][remote] = {'id': remote, 'rootPaths': ['/home/remote'], 'name': 'remote'}
        doc['thread-project-assignments']['remote-thread'] = {'projectKind': 'local', 'projectId': PROJECT}
        doc['thread-project-membership-host-ids']['remote-thread'] = 'ssh-host'
        result = self.transform(doc)
        target = result['electron-account-renderer-state-v1']['inactive'][NEW]['globals']
        self.assertNotIn(remote, target['local-projects'])
        self.assertNotIn('remote-thread', target['thread-project-assignments'])

    def test_legacy_desktop_and_already_shared_account_are_noops(self):
        self.assertIsNone(self.transform({'local-projects': workspace()['local-projects']}))
        self.assertIsNone(self.transform(document(), OLD))

    def test_ambiguous_or_conflicting_layouts_fail_before_any_write(self):
        doc = document(False)
        doc['electron-account-renderer-state-v1']['inactive']['b'*64] = {
            'globals': workspace(), 'atoms': {}}
        doc['electron-account-renderer-state-v1']['inactive']['b'*64]['globals']['local-projects'][PROJECT]['rootPaths'] = ['D:\\other-layout']
        self.state.write_text(json.dumps(doc))
        before = self.state.read_bytes()
        self.invoke(f"$doc=Get-Content '{self.state}' -Raw|ConvertFrom-Json; Workspace-Update $doc '{NEW}'", success=False)
        self.assertEqual(self.state.read_bytes(), before)
        doc = document()
        target = workspace()
        target['local-projects'][PROJECT]['rootPaths'] = ['D:\\different']
        doc['electron-account-renderer-state-v1']['inactive'][NEW] = {'globals': target, 'atoms': {}}
        self.state.write_text(json.dumps(doc))
        self.invoke(f"$doc=Get-Content '{self.state}' -Raw|ConvertFrom-Json; Workspace-Update $doc '{NEW}'", success=False)

    def test_identity_hash_matches_the_installed_desktop_algorithm(self):
        output = self.invoke('(Read-Identity $AuthFile).RendererOwner')
        self.assertEqual(output, OLD)

    def test_identical_inactive_layouts_are_unambiguous_and_signed_out_state_works(self):
        doc = document(False)
        doc['electron-account-renderer-state-v1']['owner'] = None
        doc['electron-account-renderer-state-v1']['inactive']['b'*64] = {
            'globals': workspace(), 'atoms': {'private-draft': 'another-account'}}
        result = self.transform(doc)
        target = result['electron-account-renderer-state-v1']['inactive'][NEW]
        self.assertEqual(target['globals']['local-projects'], workspace()['local-projects'])
        self.assertNotIn('private-draft', target['atoms'])

    def test_new_assignments_reopen_the_desktops_metadata_migration(self):
        doc = document()
        saved = workspace()
        saved['thread-project-assignments'] = {}
        saved['app-server-projects-migration-by-host'][HOST].update(
            threadAssignmentsMigrated=True, threadAssignmentsReadMigrated=True, pendingThreadAssignmentIds=[])
        doc['electron-account-renderer-state-v1']['inactive'][NEW] = {'globals': saved, 'atoms': {}}
        result = self.transform(doc)
        migration = result['electron-account-renderer-state-v1']['inactive'][NEW]['globals']['app-server-projects-migration-by-host'][HOST]
        self.assertFalse(migration['threadAssignmentsMigrated'])
        self.assertFalse(migration['threadAssignmentsReadMigrated'])
        self.assertIn(THREAD, migration['pendingThreadAssignmentIds'])

    def test_state_backup_is_encrypted_and_can_restore_exact_original_bytes(self):
        original = json.dumps(document(), indent=3).encode()+b'\r\n'
        self.state.write_bytes(original)
        target = self.root / 'target.json'
        target.write_bytes(credential('new-user', 'new-account', 'new@example.com'))
        self.invoke(r'''
$r=Preserve-LocalWorkspace (Join-Path $env:NX_TEST_ROOT 'target.json') (Join-Path $DataDir 'workspace.json')
if(-not $r){throw 'No transfer'}
$now=[IO.File]::ReadAllBytes($r.Path)
Replace-WorkspaceBytes (Read-CredentialBytes $r.Backup) $r.Path $now
''')
        self.assertEqual(self.state.read_bytes(), original)
        backup = self.snapshots/'recovery/workspace.json'
        self.assertNotIn(b'old-account-private', backup.read_bytes())

    def test_concurrent_writer_is_preserved(self):
        self.state.write_bytes(b'{"external":"new"}')
        self.invoke(f"Replace-WorkspaceBytes ($Utf8.GetBytes('{{}}')) '{self.state}' ($Utf8.GetBytes('{{}}'))", success=False)
        self.assertEqual(self.state.read_bytes(), b'{"external":"new"}')

    def test_failed_desktop_launch_rolls_back_auth_and_workspace(self):
        original = json.dumps(document(), indent=2).encode()
        self.state.write_bytes(original)
        auth_before = self.auth.read_bytes()
        self.snapshots.mkdir()
        (self.snapshots/'new@example.com.json').write_bytes(credential('new-user', 'new-account', 'new@example.com'))
        self.invoke(r'''
$To='new@example.com';$RestoreProjects=$false;$List=$false;$DryRun=$false;$Snapshot=$false;$Park=$false
function Stop-App {}
$script:starts=0
function Start-App { $script:starts++; if($script:starts -eq 1){throw 'Synthetic launch failure'} }
$full=[IO.File]::ReadAllText($env:NX_TEST_SCRIPT)
Invoke-Expression $full.Substring($full.IndexOf('if ($RestoreProjects -and'))
''', success=False)
        self.assertEqual(self.auth.read_bytes(), auth_before)
        self.assertEqual(self.state.read_bytes(), original)

    def test_repair_current_account_preserves_auth_and_starts_the_desktop_once(self):
        self.state.write_text(json.dumps(document(False)), encoding='utf-8')
        self.auth.write_bytes(credential('new-user', 'new-account', 'new@example.com'))
        auth_before = self.auth.read_bytes()
        self.invoke(r'''
$To=$null;$RestoreProjects=$true;$List=$false;$DryRun=$false;$Snapshot=$false;$Park=$false
function Stop-App {}
$script:starts=0
function Start-App { $script:starts++ }
$full=[IO.File]::ReadAllText($env:NX_TEST_SCRIPT)
Invoke-Expression $full.Substring($full.IndexOf('if ($RestoreProjects -and'))
if($script:starts -ne 1){throw 'Unexpected restart count'}
''')
        result = json.loads(self.state.read_text(encoding='utf-8'))
        self.assertEqual(self.auth.read_bytes(), auth_before)
        self.assertEqual(result['local-projects'], workspace()['local-projects'])
        self.assertEqual(result['thread-project-assignments'], workspace()['thread-project-assignments'])
        self.assertEqual(result['electron-account-renderer-state-v1']['owner'], NEW)

    def test_repair_dry_run_does_not_create_files_or_stop_the_desktop(self):
        original = json.dumps(document(False)).encode()
        self.state.write_bytes(original)
        auth_before = self.auth.read_bytes()
        self.invoke(r'''
$To=$null;$RestoreProjects=$true;$List=$false;$DryRun=$true;$Snapshot=$false;$Park=$false
function Stop-App { throw 'Dry run stopped the desktop' }
$full=[IO.File]::ReadAllText($env:NX_TEST_SCRIPT)
Invoke-Expression $full.Substring($full.IndexOf('if ($RestoreProjects -and'))
''')
        self.assertEqual(self.auth.read_bytes(), auth_before)
        self.assertEqual(self.state.read_bytes(), original)
        self.assertFalse(self.snapshots.exists())


if __name__ == '__main__':
    unittest.main()
