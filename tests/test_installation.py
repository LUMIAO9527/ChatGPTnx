"""Uninstall plans target only the application's files; registry calls are mocked."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nx.installation import register_application,uninstall_plan,request_uninstall,REQUEST

class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'app';self.root.mkdir()
        self.exe=self.root/'ChatGPTnx.exe';self.exe.write_bytes(b'synthetic-program')
        self.service=SimpleNamespace(paths=SimpleNamespace(root=self.root),executable=self.exe,update_parent_pid=None)
    def tearDown(self):self.tmp.cleanup()
    def test_registration_opens_this_programs_uninstall_page(self):
        registry=Mock(HKEY_CURRENT_USER='user',REG_SZ=1,REG_DWORD=2)
        registry.CreateKey.return_value.__enter__=Mock(return_value='key');registry.CreateKey.return_value.__exit__=Mock(return_value=False)
        with patch.dict(sys.modules,{'winreg':registry}):register_application(self.exe)
        entries={c.args[1]:c.args[4] for c in registry.SetValueEx.call_args_list}
        self.assertEqual(entries['DisplayName'],'ChatGPTnx');self.assertEqual(entries['UninstallString'],f'"{self.exe}" --uninstall')
        self.assertEqual(entries['InstallLocation'],str(self.root));self.assertEqual(entries['NoModify'],1)
    def test_keep_data_plan_leaves_all_account_data(self):
        targets={Path(p).relative_to(self.root).as_posix() for p in uninstall_plan(self.service,True)['targets']}
        self.assertEqual(targets,{'ChatGPTnx.exe','_wip/runtime','_wip/run','_wip/update'})
    def test_delete_data_plan_is_explicit_and_excludes_unrelated_files(self):
        targets={Path(p).relative_to(self.root).as_posix() for p in uninstall_plan(self.service,False)['targets']}
        self.assertIn('_data',targets);self.assertIn('snapshots',targets);self.assertIn('accounts.txt',targets)
        self.assertNotIn('_wip',targets);self.assertNotIn('docs',targets);self.assertNotIn('notes.txt',targets)
    def test_request_only_writes_the_existing_application_data_directory(self):
        self.assertFalse(request_uninstall(self.root));(self.root/'_data').mkdir()
        self.assertTrue(request_uninstall(self.root));self.assertTrue((self.root/'_data'/REQUEST).exists())
    def test_backup_dialog_protects_panel_and_releases_on_cancellation(self):
        from nx.desktop import Desktop
        host=object.__new__(Desktop);host.native_dialog=False;host.window=Mock()
        def dialog(*args,**kwargs):
            self.assertTrue(host.native_dialog)
            for reason in ('blur','focus','outside'):host.hide(reason=reason)
            return None
        host.window.create_file_dialog.side_effect=dialog
        result=host.choose_backup_file(False)
        self.assertTrue(result['cancelled']);self.assertFalse(host.native_dialog)
        host.window.create_file_dialog.side_effect=RuntimeError('synthetic dialog failure')
        self.assertFalse(host.choose_backup_file(True)['ok']);self.assertFalse(host.native_dialog)
    @unittest.skipUnless(os.name=='nt','Windows worker')
    def test_worker_preserves_unrelated_files_and_handles_both_data_choices(self):
        for keep in (True,False):
            folder=self.root/('keep' if keep else 'remove');folder.mkdir();exe=folder/'ChatGPTnx.exe';exe.write_bytes(b'synthetic-worker-program')
            fixture=SimpleNamespace(paths=SimpleNamespace(root=folder),executable=exe,update_parent_pid=None)
            for name in ('_wip/runtime/cache','_wip/run/session','_wip/update/old','snapshots','_data'):
                target=folder/name;target.mkdir(parents=True,exist_ok=True);(target/'synthetic.txt').write_text('fixture')
            for name in ('accounts.txt','.chatgptnx-location','notes.txt'):(folder/name).write_text('fixture')
            plan=uninstall_plan(fixture,keep);plan.update(pids=[],quiet=True)
            batch=folder/'_wip/uninstall/test';batch.mkdir(parents=True)
            worker=batch/'uninstall.ps1';worker.write_bytes((ROOT/'src/uninstall.ps1').read_bytes())
            document=batch/'plan.json';document.write_text(json.dumps(plan),encoding='utf-8')
            resolved=folder.resolve();self.assertTrue(resolved.is_relative_to(Path(self.tmp.name).resolve()))
            result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(worker),'-Plan',str(document)],capture_output=True,timeout=30,creationflags=0x08000000)
            failure=(batch/'result.json').read_text(encoding='utf-8-sig') if (batch/'result.json').exists() else ''
            self.assertEqual(result.returncode,0,failure+result.stderr.decode('utf-8',errors='replace'))
            self.assertFalse(exe.exists());self.assertFalse((folder/'_wip/runtime').exists());self.assertFalse(batch.exists())
            self.assertTrue((folder/'notes.txt').is_file())
            self.assertEqual((folder/'_data').exists(),keep);self.assertEqual((folder/'snapshots').exists(),keep)
            self.assertEqual((folder/'accounts.txt').exists(),keep)

if __name__=='__main__':unittest.main()
