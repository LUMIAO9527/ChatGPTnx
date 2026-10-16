"""Offline release metadata and staged update tests; no downloaded EXE runs."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import os
from nx.updater import UpdateManager, UpdateError, release_asset, safe_url, version_key, startup_ack
from nx.version import APP_VERSION


def fixture_release(content, tag='v1.4'):
    return {'tag_name':tag,'draft':False,'prerelease':False,'body':'A <script>must stay plain text</script>',
            'assets':[{'name':'ChatGPTnx.exe','state':'uploaded','size':len(content),
                'digest':'sha256:'+hashlib.sha256(content).hexdigest(),
                'browser_download_url':f'https://github.com/LUMIAO9527/ChatGPTnx/releases/download/{tag}/ChatGPTnx.exe'}]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exe = self.root/'ChatGPTnx.exe'
        self.exe.write_bytes(b'MZ' + b'old'*500)
        self.original = self.exe.read_bytes()
        self.resources = self.root/'resources'
        self.resources.mkdir()
        (self.resources/'ChatGPTnx.Update.exe').write_bytes(b'MZ' + b'helper' * 300)
        self.content = b'MZ' + b'new'*1000
        self.document = fixture_release(self.content)
        self.accounts = self.root/'accounts.txt'
        self.accounts.write_bytes(b'synthetic-account-list')
        self.data = self.root/'_data'
        self.data.mkdir()
        (self.data/'settings.json').write_bytes(b'original-settings')
        def opener(url):
            return io.BytesIO(json.dumps(self.document).encode() if url.endswith('/latest') else self.content)
        self.manager = UpdateManager(self.root,self.resources,executable=self.exe,frozen=True,
                                     opener=opener,current='1.3')

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self):
        deadline = time.monotonic()+3
        while self.manager.snapshot()['status'] in ('checking','downloading'):
            if time.monotonic()>deadline:self.fail('update worker did not finish')
            time.sleep(.005)
        return self.manager.snapshot()

    def download(self):
        self.manager.check();self.wait()
        self.assertTrue(self.manager.download()['ok'])
        return self.wait()

    def unchanged(self):
        self.assertEqual(self.exe.read_bytes(),self.original)
        self.assertEqual(self.accounts.read_bytes(),b'synthetic-account-list')
        self.assertEqual((self.data/'settings.json').read_bytes(),b'original-settings')

    def prepared_launcher(self):
        process = Mock(pid=4242)
        process.poll.return_value = None
        def launch(*args, **kwargs):
            batch = Path(kwargs['cwd'])
            plan = json.loads((batch / 'plan.json').read_text(encoding='utf-8'))
            (batch / 'prepared.json').write_text(json.dumps(
                {'ready': True, 'token': plan['token'], 'pid': process.pid}), encoding='utf-8')
            return process
        return Mock(side_effect=launch)

    def test_version_comparison_is_numeric_and_stable_only(self):
        self.assertGreater(version_key('v1.0.10'),version_key('1.0.9'))
        self.assertEqual(version_key('v1.3'), version_key('1.3.0'))
        self.assertGreater(version_key('v1.3'), version_key('1.0.3'))
        self.assertGreater(version_key('1.3.1'), version_key('v1.3'))
        self.assertGreater(version_key('v1.4'), version_key('1.3.9'))
        for value in ('1.4-beta','latest','1.3/../../x','-1.3'):
            with self.assertRaises(UpdateError):version_key(value)

    def test_untrusted_assets_and_redirects_are_rejected(self):
        for url in ('http://github.com/file','https://github.com@evil.test/file',
                    'https://github.com:444/file','https://evil.test/ChatGPTnx.exe'):
            with self.assertRaises(UpdateError):safe_url(url)
        for change in ({'digest':None},{'browser_download_url':'https://github.com/other/app/releases/download/v1.4/ChatGPTnx.exe'},{'size':1}):
            document=fixture_release(self.content);document['assets'][0].update(change)
            with self.assertRaises(UpdateError):release_asset(document,'1.3')

    def test_complete_download_is_staged_and_verified_without_user_data_changes(self):
        self.assertEqual(self.download()['status'],'ready')
        self.assertEqual((self.manager.batch/'ChatGPTnx.new.exe').read_bytes(),self.content)
        self.unchanged()

    def test_corrupt_or_truncated_download_never_changes_existing_exe(self):
        self.content=self.content[:-10]
        self.assertEqual(self.download()['status'],'error')
        self.assertEqual(list((self.root/'_wip/update').glob('*/ChatGPTnx.new.exe')),[])
        self.unchanged()

    def test_missing_digest_disables_update(self):
        self.document['assets'][0]['digest']=None
        self.manager.check()
        self.assertEqual(self.wait()['status'],'error')
        self.assertFalse(self.manager.download()['ok'])
        self.unchanged()

    def test_same_and_older_versions_are_not_available(self):
        for tag in ('v1.3','v1.0.2'):
            self.document=fixture_release(self.content,tag)
            self.manager.check()
            self.assertEqual(self.wait()['status'],'current')
            self.assertFalse(self.manager.download()['ok'])

    def test_changed_staged_exe_cannot_launch_helper(self):
        self.download()
        (self.manager.batch/'ChatGPTnx.new.exe').write_bytes(b'MZ-corrupt')
        launcher=Mock()
        self.assertFalse(self.manager.install(123,launcher)['ok'])
        launcher.assert_not_called()
        self.unchanged()

    def test_missing_standalone_updater_stops_before_launch(self):
        self.download()
        (self.resources / 'ChatGPTnx.Update.exe').unlink()
        launcher = Mock()
        with self.assertRaises(UpdateError):
            self.manager.install(123, launcher)
        launcher.assert_not_called()
        self.unchanged()

    def test_helper_uses_only_bundled_executable_and_structured_arguments(self):
        self.download()
        launcher=self.prepared_launcher()
        self.assertTrue(self.manager.install(123,launcher)['ok'])
        args,kw=launcher.call_args
        self.assertEqual((self.manager.batch/'ChatGPTnx.Update.exe').read_bytes(),
                         (self.resources/'ChatGPTnx.Update.exe').read_bytes())
        self.assertNotIn('shell',kw)
        self.assertEqual(args[0][0], str(self.manager.batch/'ChatGPTnx.Update.exe'))
        self.assertEqual(args[0][1], '-Plan')
        plan=json.loads((self.manager.batch/'plan.json').read_text())
        self.assertEqual(plan['parent_pid'],123)
        self.assertEqual(plan['worker_pid'],os.getpid())
        self.assertEqual(plan['sha256'],hashlib.sha256(self.content).hexdigest())
        self.assertEqual(plan['previous_version'], '1.3')
        self.assertEqual(plan['previous_sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertNotIn('accounts',plan)
        self.unchanged()

    def test_independent_helper_owns_restart_environment_without_changing_parent_environment(self):
        self.download()
        launcher = self.prepared_launcher()
        inherited = {'_PYI_APPLICATION_HOME_DIR': 'old-extracted-runtime',
                     'PYINSTALLER_RESET_ENVIRONMENT': '0'}
        with patch.dict(os.environ, inherited):
            self.assertTrue(self.manager.install(123, launcher)['ok'])
            environment = launcher.call_args.kwargs['env']
            self.assertEqual(environment['PYINSTALLER_RESET_ENVIRONMENT'], '0')
            self.assertEqual(environment['TEMP'], os.environ['TEMP'])
            self.assertEqual(environment['TMP'], os.environ['TMP'])
            self.assertEqual(os.environ['PYINSTALLER_RESET_ENVIRONMENT'], '0')
            self.assertEqual(os.environ['_PYI_APPLICATION_HOME_DIR'], 'old-extracted-runtime')
        self.unchanged()

    def test_failed_helper_preparation_keeps_current_app_available(self):
        self.download()
        process = Mock(pid=4242)
        process.poll.return_value = 1
        result = self.manager.install(123, Mock(return_value=process))
        self.assertFalse(result['ok'])
        self.assertEqual(self.manager.snapshot()['status'], 'ready')
        self.unchanged()

    def test_unresponsive_helper_is_stopped_without_closing_current_app(self):
        self.download()
        process = Mock(pid=4242)
        process.poll.return_value = None
        # A confirmation from another process cannot authorize shutdown.
        (self.manager.batch / 'prepared.json').write_text(json.dumps(
            {'ready': True, 'token': 'a'*32, 'pid': 4241}), encoding='utf-8')
        result = self.manager.install(123, Mock(return_value=process), ready_timeout=.02)
        self.assertFalse(result['ok'])
        process.terminate.assert_called_once()
        self.assertEqual(self.manager.snapshot()['status'], 'ready')
        self.unchanged()

    def test_failed_preparation_can_be_retried_in_same_download_batch(self):
        self.download()
        process = Mock(pid=4242)
        process.poll.return_value = 1
        self.assertFalse(self.manager.install(123, Mock(return_value=process))['ok'])
        self.assertTrue(self.manager.install(123, self.prepared_launcher())['ok'])
        self.unchanged()

    def test_source_mode_can_check_but_cannot_replace_interpreter(self):
        self.manager.installable=False
        self.manager.check();self.wait()
        self.assertFalse(self.manager.download()['ok'])
        self.unchanged()

    def test_startup_ack_requires_the_matching_executable_and_plan(self):
        self.download()
        ack=self.manager.batch/'started.json'
        plan={'token':'a'*32,'version':APP_VERSION,'executable':str(self.exe),
              'sha256':hashlib.sha256(self.exe.read_bytes()).hexdigest()}
        (ack.parent/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        with self.assertRaises(UpdateError):startup_ack(self.root,self.exe,ack,'b'*32)
        self.assertFalse(ack.exists())
        plan['version'] = '0.0.1'
        (ack.parent/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        with self.assertRaises(UpdateError):startup_ack(self.root,self.exe,ack,'a'*32)
        self.assertFalse(ack.exists())
        plan['version'] = APP_VERSION
        (ack.parent/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
        startup_ack(self.root,self.exe,ack,'a'*32)
        self.assertTrue(json.loads(ack.read_text())['ready'])
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
