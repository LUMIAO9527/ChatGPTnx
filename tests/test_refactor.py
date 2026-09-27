"""Root-cause regressions for the 5.7.0 refactor. Synthetic data only.

Windows UIA/process calls are mocked or checked as source contracts here;
this file deliberately does not claim native Windows integration coverage.
"""
from __future__ import annotations
from contextlib import closing
import base64
import copy
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.core import Service, relay_candidates
from nx.desktop import Bridge, system_prefers_dark
from nx.desktop_resume import attempt_continuation, navigate_existing_task, title_prefix
from nx.history_store import read_only
from nx.limit_watch import UsageLimitWatcher
from nx.quota_policy import complete_windows, fresh_windows, sanitize_cached_account
from nx.resume_flow import ResumeCoordinator
from nx.settings import normalize_settings, valid_setting
from nx.storage import Accounts, Paths, State, atomic_bytes, identity

THREAD = '67cc833f-6330-5bae-a638-9232b5ddfa21'
TURN = '42d1e863-8084-556e-a03c-d7c800c7055b'
ROOT = Path(__file__).resolve().parents[1]


def credential(email, workspace='shared-workspace', claimed_workspace='claim-workspace'):
    claims = {'email': email, 'sub': 'person-' + email,
              'https://api.openai.com/auth': {'chatgpt_account_id': claimed_workspace}}
    middle = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return json.dumps({'account_id': 'legacy-workspace',
                       'tokens': {'id_token': 'test.' + middle + '.unsigned',
                                  'account_id': workspace}}).encode()


def quota(**changes):
    return {'email': 'b@example.com', 'ok': True, 'fetched_at': time.time(),
            'windows': [{'used': 20, 'resets_at': time.time() + 3600,
                         'label': '周', 'duration_mins': 10080}], **changes}


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = Paths(root, root / 'desktop')
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)

    def coordinator(self):
        return ResumeCoordinator(self.paths, lambda: 'b@example.com', self.stop,
                                 Mock(), Mock(), threading.Lock(),
                                 settings=lambda: {'auto_relay': True, 'task_continuation': True,
                                                   'resume_message': '继续'})

    @staticmethod
    def event(**extras):
        return {'thread_id': THREAD, 'turn_id': TURN, **extras}


class SettingsAndQuotaTests(unittest.TestCase):
    def test_system_dark_registry_zero_is_not_coerced_to_one(self):
        registry = MagicMock()
        for value, expected in ((0, True), (1, False)):
            registry.QueryValueEx.return_value = (value, 4)
            with patch.dict(sys.modules, {'winreg': registry}):
                self.assertIs(system_prefers_dark(), expected)

    def test_invalid_automation_values_fail_closed(self):
        for value in ('false', 'true', 0, 1, None, [], {}):
            with self.subTest(value=value):
                settings = normalize_settings({'auto_relay': value, 'task_continuation': value})
                self.assertIs(settings['auto_relay'], False)
                self.assertIs(settings['task_continuation'], False)

    def test_settings_types_ranges_and_message_contract(self):
        for key, value in [('query_workers', True), ('query_workers', 3), ('query_timeout', 0),
                           ('poll_minutes', float('inf')), ('notify_low_threshold', '20'),
                           ('resume_message', 'x\nx'), ('resume_message', ' x'),
                           ('resume_message', '\u200b'), ('resume_message', '😀' * 201)]:
            with self.subTest(key=key, value=value):
                self.assertFalse(valid_setting(key, value))
        self.assertTrue(valid_setting('resume_message', '😀' * 200))
        self.assertTrue(valid_setting('task_continuation', True))

    def test_exclusions_are_deduplicated_without_shared_defaults(self):
        one = normalize_settings({'auto_relay_excluded': ['a', 'a', '', 'b']})
        self.assertEqual(one['auto_relay_excluded'], ['a', 'b'])
        one['auto_relay_excluded'].append('c')
        self.assertEqual(normalize_settings({})['auto_relay_excluded'], [])

    def test_malformed_quota_numbers_never_enter_ranking(self):
        for value in (True, None, '20', -1, 101, float('nan'), float('inf'), 10**1000):
            with self.subTest(value=repr(value)[:20]):
                q = quota(windows=[{'used': value, 'resets_at': time.time()+3600}])
                self.assertFalse(complete_windows(q['windows']))
                self.assertEqual(relay_candidates([q], None), [])
                self.assertFalse(sanitize_cached_account(q)['ok'])

    def test_quota_without_timestamp_is_not_a_relay_candidate(self):
        q = quota(); q.pop('fetched_at')
        self.assertFalse(fresh_windows(q))
        self.assertEqual(relay_candidates([q], None), [])

    def test_stale_future_or_reset_boundary_is_not_usable(self):
        stamp = time.time()
        for q in (quota(fetched_at=stamp-601), quota(fetched_at=stamp+61),
                  quota(ok='false'), quota(windows=[]),
                  quota(windows=[{'used': 0, 'resets_at': stamp}]),
                  quota(windows=[{'used': 0, 'resets_at': 10**1000}])):
            with self.subTest(q=q):
                self.assertFalse(fresh_windows(q, stamp))
        self.assertTrue(fresh_windows(quota(fetched_at=stamp), stamp))

    def test_exactly_zero_remaining_does_not_become_relay_ready(self):
        q = quota(windows=[{'used': 100, 'resets_at': time.time()+1000}])
        self.assertTrue(fresh_windows(q))
        self.assertEqual(relay_candidates([q], None), [])


class StorageRecoveryTests(TemporaryCase):
    def test_memory_and_disk_stay_at_last_commit_on_write_failure(self):
        state = State(self.paths)
        before, raw = copy.deepcopy(state.value), state.path.read_bytes()
        with patch('nx.storage.atomic_bytes', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                state.setting(auto_relay=True)
        self.assertEqual(state.value, before)
        self.assertEqual(state.path.read_bytes(), raw)

    def test_atomic_read_modify_write_preserves_concurrent_updates(self):
        state = State(self.paths)
        barrier, errors = threading.Barrier(3), []
        def change(prefix):
            try:
                barrier.wait()
                for n in range(12):
                    state.change('account_meta', lambda old: {**old, f'{prefix}{n}': {'alias': str(n)}})
            except Exception as exc:
                errors.append(exc)
        workers = [threading.Thread(target=change, args=(p,)) for p in ('a', 'b')]
        for t in workers: t.start()
        barrier.wait()
        for t in workers: t.join(5)
        self.assertFalse(errors)
        self.assertFalse(any(t.is_alive() for t in workers))
        self.assertEqual(len(State(self.paths).get('account_meta')), 24)

    def test_corrupt_json_is_backed_up_exactly_and_automation_disabled(self):
        raw = b'{"settings":{"auto_relay":true}, BROKEN'
        path = self.paths.data / 'state.json'; path.write_bytes(raw)
        state = State(self.paths)
        self.assertEqual(state.recovery_path.read_bytes(), raw)
        self.assertFalse(state.get('settings')['auto_relay'])
        self.assertFalse(state.get('settings')['task_continuation'])
        self.assertIsInstance(json.loads(path.read_bytes()), dict)

    def test_nan_json_is_preserved_not_reemitted_as_invalid_json(self):
        path = self.paths.data / 'state.json'; path.write_text('{"cache":NaN}')
        state = State(self.paths)
        self.assertIsNotNone(state.recovery_path)
        self.assertNotIn('NaN', path.read_text(encoding='utf-8'))

    def test_read_permission_failure_is_not_treated_as_empty_state(self):
        state = State(self.paths)
        raw = state.path.read_bytes()
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError): State(self.paths)
        self.assertEqual(state.path.read_bytes(), raw)

    def test_malformed_cache_shape_cannot_crash_bridge_iteration(self):
        self.paths.data.joinpath('state.json').write_text(json.dumps({
            'cache': {'accounts': [None, 1, {}, {'email': 'a@example.com', 'ok': True,
                                               'windows': [{'used': 'bad', 'resets_at': 1}]}]},
            'account_meta': [], 'hotkeys': {'a': {}, 'b': 'ctrl+alt+1'},
            'usage_revision': 'NaN', 'usage': {'a': 5}, 'subscriptions': False}))
        state = State(self.paths)
        self.assertEqual(state.get('usage'), {})
        self.assertEqual(state.get('hotkeys'), {'b': 'ctrl+alt+1'})
        self.assertEqual(state.get('usage_revision'), 0)
        self.assertEqual(len(state.get('cache')['accounts']), 1)
        self.assertFalse(state.get('cache')['accounts'][0]['ok'])

    def test_workspace_id_does_not_match_another_person(self):
        accounts = Accounts(self.paths)
        accounts.write(['a@example.com', 'b@example.com'])
        for email in accounts.all(): atomic_bytes(self.paths.snapshot(email), credential(email))
        atomic_bytes(self.paths.auth, credential('b@example.com'))
        self.assertEqual(accounts.current(), 'b@example.com')
        atomic_bytes(self.paths.auth, credential('external@example.com'))
        self.assertIsNone(accounts.current())

    def test_same_person_wrong_workspace_does_not_match(self):
        accounts = Accounts(self.paths); accounts.write(['a@example.com'])
        atomic_bytes(self.paths.snapshot('a@example.com'), credential('a@example.com'))
        atomic_bytes(self.paths.auth, credential('a@example.com', 'another-workspace'))
        self.assertIsNone(accounts.current())
        self.assertEqual(identity(self.paths.auth)[1], 'another-workspace')


class ResumeDurabilityTests(TemporaryCase):
    def ready_session(self, c):
        ident = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        c.switched(ident)
        return ident

    def test_ready_is_not_returned_before_durable_intent(self):
        c = self.coordinator(); self.ready_session(c)
        with patch('nx.resume_flow.atomic_bytes', side_effect=PermissionError('disk full')):
            with self.assertRaises(PermissionError): c._ready()
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'waiting')
        self.assertEqual(json.loads(c.path.read_bytes())['sessions'][0]['items'][0]['state'], 'waiting')

    def test_result_commit_retries_disk_not_desktop_effect(self):
        c = self.coordinator(); ident = self.ready_session(c)
        actual = atomic_bytes
        failures, writes = [], []
        def flaky(path, raw):
            document = json.loads(raw)
            status = document['sessions'][-1]['items'][0]['state']
            writes.append(status)
            if status == 'done' and not failures:
                failures.append(True)
                raise PermissionError('transient reader lock')
            actual(path, raw)
        with patch('nx.resume_flow.atomic_bytes', side_effect=flaky), \
             patch('nx.resume_flow.attempt_continuation', return_value=('done', 'new_turn_observed')) as effect:
            c.start()
            end = time.monotonic() + 4
            while c.sessions[0]['phase'] != 'done' and time.monotonic() < end: time.sleep(.01)
            self.stop.set(); c.wake.set(); c.worker.join(3)
        self.assertEqual(effect.call_count, 1)
        self.assertEqual(writes.count('done'), 2)
        self.assertEqual(c.sessions[0]['phase'], 'done')
        self.assertEqual(json.loads(c.path.read_bytes())['sessions'][0]['items'][0]['attempts'], 1)

    def test_restart_of_acting_item_is_uncertain_never_queued(self):
        c = self.coordinator(); self.ready_session(c); c._ready()
        recovered = self.coordinator()
        self.assertEqual(recovered.sessions[0]['items'][0]['reason'], 'action_outcome_unknown')
        self.assertIsNone(recovered._ready())
        self.assertFalse(recovered.retry_task(recovered.sessions[0]['id'], THREAD)['ok'])

    def test_clear_history_preserves_active_and_pending_items(self):
        c = self.coordinator()
        ident = self.ready_session(c)
        c.note_limit_events([self.event(thread_id='ea10a953-d3a4-53b9-b010-6361794c2a22')],
                            'b@example.com', True)
        old = copy.deepcopy(c.sessions[0]); old.update(id='old', phase='failed')
        old['items'][0].update(state='failed', reason='unrelated_failure')
        c.sessions.append(old); c._save()
        self.assertEqual(c.clear_history()['removed'], 1)
        self.assertEqual([s['id'] for s in c.sessions], [ident])
        self.assertEqual(len(c.pending), 1)
        self.assertEqual(self.coordinator().sessions[0]['id'], ident)

    def test_terminal_retention_remains_bounded_with_more_than_twenty_active(self):
        c = self.coordinator(); stamp = time.time()
        def session(n, active):
            return {'id': f'{active}-{n}', 'created_at': stamp, 'updated_at': stamp-n,
                    'phase': 'resuming' if active else 'done', 'target': 'b@example.com',
                    'items': [{**c._item(self.event()), 'state': 'waiting' if active else 'done'}]}
        c.sessions = [session(n, active) for active, count in ((True, 25), (False, 32)) for n in range(count)]
        c._save()
        self.assertEqual(sum(s['phase']=='resuming' for s in c.sessions), 25)
        self.assertEqual(sum(s['phase']=='done' for s in c.sessions), 20)
        self.assertIn('False-0', {s['id'] for s in c.sessions})
        self.assertNotIn('False-31', {s['id'] for s in c.sessions})
        detail = c.details()
        self.assertEqual([s['updated_at'] for s in detail], sorted((s['updated_at'] for s in detail), reverse=True))

    def test_corrupt_resume_journal_kept_for_diagnostics(self):
        path = self.paths.data/'resume.json'; path.write_bytes(b'broken resume metadata')
        c = self.coordinator()
        self.assertEqual(c.recovery_path.read_bytes(), b'broken resume metadata')
        self.assertEqual(c.details(), [])
        self.assertIsNone(c._ready())

    def test_malformed_persisted_tasks_are_not_executable(self):
        path = self.paths.data/'resume.json'
        path.write_text(json.dumps({'sessions': [None, {'id': 'broken', 'items': [True,
            {'thread_id': '../../bad', 'turn_id': TURN}], 'phase': 'resuming'}], 'pending': [True, {}]}))
        c = self.coordinator()
        self.assertEqual(c.pending, [])
        self.assertIsNone(c._ready())


class WatcherTransactionTests(TemporaryCase):
    def database(self):
        self.paths.home.mkdir()
        self.path = self.paths.home/'thread_history_1.sqlite'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,status TEXT,error_json TEXT,started_at INTEGER,completed_at INTEGER)')
        self.watcher = UsageLimitWatcher(self.paths.home); self.assertTrue(self.watcher.prime())

    def insert(self, count=1, stamp=100):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?,?,?)', [
                (f'task-{i}', f'turn-{i}', 'failed', '{"codexErrorInfo":"usageLimitExceeded"}', 1, stamp)
                for i in range(count)])

    def test_1100_failures_at_one_timestamp_are_each_consumed_once(self):
        self.database(); self.insert(1100)
        self.assertEqual(len(self.watcher.poll()), 1100)
        for _ in range(3): self.assertEqual(self.watcher.poll(), [])

    def test_cursor_only_commits_after_consumer_durability(self):
        self.database(); self.insert()
        consume = Mock(side_effect=PermissionError('journal locked'))
        with self.assertRaises(PermissionError): self.watcher.poll(consume)
        self.assertEqual(self.watcher.completed_at, 0)
        successful = Mock(); self.assertEqual(len(self.watcher.poll(successful)), 1)
        successful.assert_called_once()
        self.assertEqual(self.watcher.poll(successful), [])
        self.assertEqual(successful.call_count, 1)

    def test_database_failure_is_recoverable_next_poll(self):
        self.database(); self.insert()
        with patch('nx.limit_watch.read_only', side_effect=sqlite3.OperationalError('locked')):
            self.assertEqual(self.watcher.poll(), [])
        self.assertEqual(len(self.watcher.poll()), 1)

    def test_read_only_open_does_not_create_missing_database(self):
        missing = self.paths.home/'does-not-exist.sqlite'
        with self.assertRaises(sqlite3.OperationalError):
            with read_only(missing): pass
        self.assertFalse(missing.exists())


class ExistingDesktopSafetyTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        atomic_bytes(self.paths.auth, credential('b@example.com'))
        self.record = {'turn_id': TURN, 'status': 'interrupted', 'error': None}

    def attempt(self, output=None, error=None, stop=None):
        with patch('nx.desktop_resume.latest_turn', return_value=self.record), \
             patch('nx.desktop_resume.title_prefix', return_value='A unique task'), \
             patch('nx.desktop_resume.subprocess.run', return_value=output, side_effect=error) as run:
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.event(expected_account_key=__import__('nx.storage',fromlist=['account_identity_key']).account_identity_key(self.paths.auth, 'b@example.com')), stop or self.stop, Mock())
        return result, run

    def test_timeout_is_uncertain_and_cannot_be_retried(self):
        result, _ = self.attempt(error=subprocess.TimeoutExpired('powershell', 28))
        self.assertEqual(result, ('failed', 'action_outcome_unknown'))

    def test_missing_native_action_is_terminal_without_input(self):
        for reason in ('native_continue_unavailable', 'native_continue_not_ready',
                       'native_continue_ambiguous', 'account_changed', 'continuation_disabled'):
            with self.subTest(reason=reason):
                result, run = self.attempt(output=Mock(stdout='skip:'+reason, returncode=2))
                self.assertEqual(result, ('failed', reason))
                self.assertNotIn('-Message', run.call_args.args[0])
                self.assertIn('-ExpectedAuthHash', run.call_args.args[0])

    def test_helper_start_failure_is_terminal_without_duplicate_effect(self):
        result, _ = self.attempt(error=FileNotFoundError('powershell'))
        self.assertEqual(result, ('failed', 'desktop_not_running'))

    def test_unknown_helper_output_does_not_claim_success_or_retry(self):
        for label in ('', 'invoked:unexpected', 'uncertain:desktop_error'):
            with self.subTest(label=label):
                result, _ = self.attempt(output=Mock(stdout=label, returncode=0))
                self.assertEqual(result, ('failed', 'action_outcome_unknown'))

    def test_native_invocation_without_observed_turn_is_not_reissued(self):
        stop = Mock(); stop.is_set.return_value=False; stop.wait.return_value=False
        result, run = self.attempt(output=Mock(stdout='invoked:native_continue', returncode=0), stop=stop)
        self.assertEqual(result, ('failed', 'start_not_observed'))
        run.assert_called_once()

    def test_open_task_uses_pinned_navigation_helper_not_protocol_handler(self):
        with patch('nx.desktop_resume.title_prefix', return_value='Unique task'), \
             patch('nx.desktop_resume.subprocess.run', return_value=Mock(stdout='opened:existing_task',returncode=0)) as run:
            self.assertTrue(navigate_existing_task(self.paths.home,self.paths.desktop_resume_ps1,THREAD)['ok'])
        self.assertIn('-NavigateOnly', run.call_args.args[0])
        self.assertNotIn('-SettingsFile', run.call_args.args[0])

    def test_bridge_refuses_unknown_or_busy_task_before_navigation(self):
        service = SimpleNamespace(get_resume_details=lambda:[{'items':[self.event()]}],
                                  desktop_gate=threading.Lock(),paths=self.paths)
        bridge = Bridge(service, None)
        with patch('nx.desktop_resume.navigate_existing_task') as navigate:
            self.assertFalse(bridge.open_resume_task('bad-id')['ok'])
            self.assertFalse(bridge.open_resume_task(TURN)['ok'])
            service.desktop_gate.acquire()
            self.assertFalse(bridge.open_resume_task(THREAD)['ok'])
            service.desktop_gate.release()
        navigate.assert_not_called()

    def test_helper_source_has_no_draft_replacement_input_or_launch_path(self):
        path = ROOT/'src/continue_in_desktop.ps1'
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        script = path.read_text(encoding='utf-8-sig')
        for forbidden in (r'\.SetValue\s*\(', r'\bSendKeys\b', r'\bkeybd_event\b',
                          r'\bStart-Process\b', r'\bSet-Clipboard\b', r'codex://'):
            with self.subTest(forbidden=forbidden): self.assertNotRegex(script, forbidden)
        self.assertNotIn('Assert-EmptyComposer $composer', script)
        self.assertNotIn("Skip 'composer_state_unknown'", script)
        self.assertIn('SessionId', script)
        self.assertNotIn('Send-ResumeMessage', script)
        self.assertNotIn('SendInput', script)
        self.assertNotIn('Assert-CollapsedCaret $composer', script)
        self.assertNotIn('class NXInputGuard', script)
        self.assertIn('Started=$process.StartTime.Ticks', script)


class TransactionResultTests(TemporaryCase):
    def test_post_commit_refresh_failure_does_not_mark_committed_operation_failed(self):
        service = Service(self.paths, query=Mock(), runner=Mock())
        try:
            effect = Mock()
            with patch.object(service, '_refresh', side_effect=OSError('network disconnected')):
                result = service.begin('adopt', 'b@example.com', effect, refresh_after=True)
                self.assertTrue(result['accepted'])
                end = time.monotonic()+3
                while service.gate.locked() and time.monotonic()<end: time.sleep(.01)
            effect.assert_called_once()
            self.assertTrue(service.last_result['ok'])
            self.assertEqual(service.last_error['kind'], 'refresh')
            self.assertEqual(service.recent_results[-1]['id'], result['operation_id'])
        finally:
            service.stop.set()
            for handler in list(service.log.handlers): handler.close();service.log.removeHandler(handler)

    def test_acknowledging_one_error_does_not_hide_a_newer_error(self):
        service = Service(self.paths, query=Mock(), runner=Mock())
        try:
            service.last_error={'id':'new','created_at':time.time(),'seen':False}
            service.dismiss_error('old')
            self.assertIsNotNone(service.visible_error())
            service.dismiss_error('new')
            self.assertIsNone(service.visible_error())
            service.last_error={'id':'expired','created_at':time.time()-86401,'seen':False}
            self.assertIsNone(service.visible_error())
        finally:
            service.stop.set()
            for handler in list(service.log.handlers): handler.close();service.log.removeHandler(handler)


if __name__ == '__main__': unittest.main()
