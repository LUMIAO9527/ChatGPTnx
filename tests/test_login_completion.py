"""Synthetic credentials only: debounce, cancellation and commit boundaries."""
import time
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_core
from nx.credentials import read_credential_bytes, write_credential_bytes
from nx.desktop import Desktop
from nx.storage import atomic_bytes


class LoginCompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_core.Fixture()
        self.fixture.setUp()
        self.s = self.fixture.service
        self.paths = self.fixture.paths
        self.wait = self.fixture.wait

    def tearDown(self):
        self.fixture.tearDown()

    def ready(self, kind='reauth', email='b@example.com'):
        self.s.reauth_start(email) if kind == 'reauth' else self.s.add_start()
        self.wait()
        atomic_bytes(self.paths.auth, test_core.auth(email))
        return time.monotonic()

    def test_reauth_debounces_bytes_and_commits_once_without_ui(self):
        t = self.ready()
        self.assertFalse(self.s.tick_login(t))
        atomic_bytes(self.paths.auth, test_core.auth('b@example.com', {'revision': 2}))
        self.assertFalse(self.s.tick_login(t + 1))
        self.assertFalse(self.s.tick_login(t + 2.5))
        self.assertTrue(self.s.tick_login(t + 3.1))
        self.wait()
        self.assertIsNone(self.s.state.get('reauth'))
        self.assertEqual(read_credential_bytes(self.paths.snapshot('b@example.com')), self.paths.auth.read_bytes())
        self.assertFalse(self.s.tick_login(t + 5))
        self.assertEqual(len(self.fixture.query.calls), 1)
        self.assertTrue(self.s.login_result['quota_ok'])

    def test_new_account_is_verified_before_it_enters_roster(self):
        t = self.ready('adding', 'new@example.com')
        self.s.tick_login(t)
        self.s.tick_login(t + 2.1)
        self.wait()
        self.assertIn('new@example.com', self.s.accounts.all())
        self.assertEqual(self.fixture.query.calls, [('new@example.com', True, False)])

    def test_new_plus_participates_in_relay_and_preheat_without_enabling_automation(self):
        self.ready('adding', 'new@example.com')
        atomic_bytes(self.paths.auth, test_core.auth('new@example.com', {'chatgpt_plan_type': 'plus'}))
        self.s.state.setting(auto_relay_excluded=['b@example.com', 'new@example.com'],
                             early_anchor_accounts=['b@example.com'])
        self.assertTrue(self.s.add_finish()['accepted'])
        self.wait()
        settings = self.s.state.get('settings')
        self.assertEqual(settings['auto_relay_excluded'], ['b@example.com'])
        self.assertEqual(settings['early_anchor_accounts'], ['b@example.com', 'new@example.com'])
        self.assertFalse(settings['auto_relay'])
        self.assertFalse(settings['early_anchor'])

    def test_new_non_plus_is_not_selected_for_plus_only_preheat(self):
        self.ready('adding', 'new@example.com')
        atomic_bytes(self.paths.auth, test_core.auth('new@example.com', {'chatgpt_plan_type': 'pro'}))
        self.assertTrue(self.s.add_finish()['accepted'])
        self.wait()
        self.assertNotIn('new@example.com', self.s.state.get('settings')['early_anchor_accounts'])

    def test_reauthentication_preserves_explicit_participation_choices(self):
        self.ready('reauth', 'b@example.com')
        atomic_bytes(self.paths.auth, test_core.auth('b@example.com', {'chatgpt_plan_type': 'plus'}))
        self.s.state.setting(auto_relay_excluded=['b@example.com'], early_anchor_accounts=[])
        self.assertTrue(self.s.reauth_finish()['accepted'])
        self.wait()
        self.assertEqual(self.s.state.get('settings')['auto_relay_excluded'], ['b@example.com'])
        self.assertEqual(self.s.state.get('settings')['early_anchor_accounts'], [])

    def test_wrong_identity_does_not_query_or_overwrite_snapshot(self):
        original = self.paths.snapshot('b@example.com').read_bytes()
        t = self.ready(email='b@example.com')
        atomic_bytes(self.paths.auth, test_core.auth('other@example.com'))
        self.s.tick_login(t)
        self.s.tick_login(t + 4)
        self.assertEqual(self.fixture.query.calls, [])
        self.assertEqual(self.paths.snapshot('b@example.com').read_bytes(), original)
        self.assertEqual(self.s.login_progress['status'], 'wrong')

    def test_network_failure_is_pending_and_automatic_retries_are_bounded(self):
        t = self.ready()
        self.fixture.query.codes['b@example.com'] = 'network'
        self.s.tick_login(t)
        for elapsed in (3, 65, 130, 195, 260):
            self.s.tick_login(t + elapsed)
            self.wait()
        self.assertEqual(len(self.fixture.query.calls), 3)
        self.assertIsNotNone(self.s.state.get('reauth'))
        self.assertEqual(self.s.login_progress['status'], 'retry')
        self.assertIn('联网验证', self.s.login_progress['message'])

    def test_denial_stops_retries_for_same_credential(self):
        t = self.ready()
        self.fixture.query.codes['b@example.com'] = 403
        self.s.tick_login(t)
        self.s.tick_login(t + 3)
        self.wait()
        self.s.tick_login(t + 1000)
        self.assertEqual(len(self.fixture.query.calls), 1)
        self.assertEqual(self.s.login_progress['status'], 'blocked')

    def test_identity_proof_can_commit_without_quota_success(self):
        t = self.ready()
        self.fixture.query.run = lambda *a, **k: {'ok': False, 'identity_verified': True, 'error_code': 'schema'}
        self.s.tick_login(t)
        self.s.tick_login(t + 3)
        self.wait()
        self.assertIsNone(self.s.state.get('reauth'))
        self.assertFalse(self.s.login_result['quota_ok'])
        self.assertIn('登录已保存', self.s.login_result['message'])

    def test_credential_change_during_query_cannot_be_saved(self):
        original = self.paths.snapshot('b@example.com').read_bytes()
        self.ready()
        def change(*args, **kwargs):
            atomic_bytes(self.paths.auth, test_core.auth('b@example.com', {'revision': 99}))
            return {'ok': True}
        self.fixture.query.run = change
        self.s.reauth_finish()
        self.wait()
        self.assertIsNotNone(self.s.state.get('reauth'))
        self.assertEqual(self.paths.snapshot('b@example.com').read_bytes(), original)

    def test_cancel_during_verification_restores_original_without_commit(self):
        original = self.paths.snapshot('b@example.com').read_bytes()
        t = self.ready()
        self.fixture.query.delay = 1
        self.s.tick_login(t)
        self.s.tick_login(t + 3)
        result = self.s.reauth_cancel()
        self.assertTrue(result['ok'])
        self.wait()
        self.assertIsNone(self.s.state.get('reauth'))
        self.assertEqual(self.s.accounts.current(), 'a@example.com')
        self.assertEqual(self.paths.snapshot('b@example.com').read_bytes(), original)
        self.assertIsNone(self.s.login_result)

    def test_pending_login_cannot_launch_update(self):
        self.ready()
        with patch.object(self.s.updater, 'install') as install:
            self.assertFalse(self.s.install_update()['ok'])
            install.assert_not_called()
        self.assertFalse(self.s.gate.locked())
        self.assertFalse(self.s.desktop_gate.locked())

    def test_cancel_at_committed_save_does_not_restore_a_stale_workflow(self):
        self.ready()
        writing, release = threading.Event(), threading.Event()
        cancelled = []
        def writer(*args):
            writing.set()
            if not release.wait(3):
                raise RuntimeError('synthetic commit timeout')
            return write_credential_bytes(*args)
        with patch('nx.core.write_credential_bytes', side_effect=writer):
            self.s.reauth_finish()
            self.assertTrue(writing.wait(3))
            thread = threading.Thread(target=lambda: cancelled.append(self.s.reauth_cancel()))
            thread.start()
            release.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.wait()
        self.assertFalse(cancelled[0]['accepted'])
        self.assertIsNone(self.s.state.get('reauth'))
        self.assertEqual(self.s.accounts.current(), 'b@example.com')
        self.assertIsNotNone(self.s.login_result)


class LoginWindowTests(test_core.unittest.TestCase):
    def test_update_ack_waits_for_loaded_ui_and_a_native_form(self):
        service=SimpleNamespace(listeners=[],log=test_core.Mock())
        acknowledge=test_core.Mock()
        panel=Desktop(service,startup_ready=acknowledge)
        panel.ready.set()
        panel.window=test_core.Mock()
        panel.window.evaluate_js.return_value=True
        with patch.object(panel,'_form',return_value=object()):
            panel._acknowledge_startup()
        acknowledge.assert_called_once()
        acknowledge.reset_mock()
        panel.window.evaluate_js.return_value=False
        with patch.object(panel,'_form',return_value=object()), \
             patch('nx.desktop.time.monotonic',side_effect=[0,0,16]),patch('nx.desktop.time.sleep'):
            panel._acknowledge_startup()
        acknowledge.assert_not_called()

    def test_native_focus_hide_is_ignored_during_login_but_user_hide_works(self):
        service = SimpleNamespace(listeners=[], operation=None,
            state=SimpleNamespace(get=lambda key: {'phase':'login','id':'fixture'} if key=='reauth' else None),
            log=test_core.Mock())
        panel = Desktop(service)
        panel.window, panel.visible = object(), True
        panel.hide(reason='focus')
        self.assertTrue(panel.visible)
        form = test_core.Mock()
        with patch.object(panel, '_form', return_value=form), patch.object(panel, '_set_panel_topmost'), \
             patch.object(panel, '_post_script'), patch.object(panel, '_dispatch_ui', side_effect=lambda f:f()):
            panel.hide(reason='user')
        self.assertFalse(panel.visible)
        form.Hide.assert_called_once()


if __name__ == '__main__':
    unittest.main()
