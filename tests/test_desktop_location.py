"""Identity navigation and safe handoff to the existing native resume route."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.app_bridge import BridgeUncertain
from nx.desktop_location import canonical_task, locate_task
from nx.desktop_resume import attempt_continuation


class LocationTests(unittest.TestCase):
    TARGET = '11111111-1111-4111-8111-111111111111'
    RUNTIME = '22222222-2222-4222-8222-222222222222'
    SOURCE = '33333333-3333-4333-8333-333333333333'

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '_wip' / 'temp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.home = Path(self.temp.name)
        (self.home / 'auth.json').write_text('{}')
        self.settings = self.home / 'settings.json'
        self.settings.write_text(json.dumps({'settings': {
            'task_continuation': True, 'resume_source_thread_id': self.SOURCE}}))
        with sqlite3.connect(self.home / 'state_1.sqlite') as db:
            db.execute('CREATE TABLE threads (id TEXT, archived INTEGER, rollout_path TEXT)')
            db.execute('INSERT INTO threads VALUES (?,0,?)', (self.TARGET, f'rollout_{self.RUNTIME}.jsonl'))
        db.close()
        self.pipe = Mock()
        self.snapshot = {'thread': {'id': self.TARGET, 'kind': 'codex'},
                         'turns': [{'id': 'old', 'status': 'failed'}]}
        self.record = {'turn_id': 'old', 'status': 'failed',
                       'error': {'codexErrorInfo': 'usageLimitExceeded'}}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def reply(value):
        return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(value)}]}

    def locate(self, ack=None, expected='old'):
        self.pipe.request.side_effect = [self.reply(self.snapshot),
            ack if isinstance(ack, Exception) else self.reply({'navigated': True} if ack is None else ack)]
        with patch('nx.desktop_location.discover', return_value=self.pipe), \
             patch('nx.desktop_resume.latest_turn', return_value=self.record):
            return locate_task(self.home, self.RUNTIME, self.settings, expected_turn=expected)

    def test_explicit_runtime_mapping_and_archived_rejection(self):
        self.assertEqual(canonical_task(self.home, self.RUNTIME), self.TARGET)
        with sqlite3.connect(self.home / 'state_1.sqlite') as db:
            db.execute('UPDATE threads SET archived=1')
        db.close()
        self.assertIsNone(canonical_task(self.home, self.RUNTIME))

    def test_duplicate_runtime_relationship_is_rejected(self):
        with sqlite3.connect(self.home / 'state_1.sqlite') as db:
            db.execute('INSERT INTO threads VALUES (?,1,?)', (self.SOURCE, f'rollout_{self.RUNTIME}.jsonl'))
        db.close()
        self.assertIsNone(canonical_task(self.home, self.RUNTIME))

    def test_navigation_uses_canonical_id_and_never_sends(self):
        self.assertEqual(self.locate(), ('located', 'task_opened_by_id'))
        calls = self.pipe.request.call_args_list
        self.assertEqual([c.args[1]['tool'] for c in calls], ['read_thread', 'navigate_to_codex_page'])
        self.assertEqual(calls[1].args[1]['arguments'], {'threadId': self.TARGET})
        self.assertEqual(calls[1].args[1]['threadId'], self.SOURCE)
        self.pipe.close.assert_called_once()

    def test_newer_turn_does_not_navigate(self):
        self.snapshot['turns'][0]['id'] = 'new'
        self.assertEqual(self.locate(), ('skipped', 'newer_turn'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_running_turn_does_not_navigate(self):
        self.snapshot['turns'][0]['status'] = 'inProgress'
        self.assertEqual(self.locate(), ('failed', 'desktop_task_not_idle'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_wrong_thread_is_rejected(self):
        self.snapshot['thread']['id'] = self.SOURCE
        self.assertEqual(self.locate(), ('failed', 'bridge_target_mismatch'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_navigation_timeout_is_not_reported_as_resumed(self):
        self.assertEqual(self.locate(BridgeUncertain()), ('failed', 'task_navigation_unconfirmed'))

    def test_negative_navigation_ack_is_not_reported_as_opened(self):
        self.assertEqual(self.locate({'navigated': False}), ('failed', 'task_navigation_unconfirmed'))

    def test_auth_change_prevents_navigation(self):
        with patch('nx.desktop_location.fingerprint', side_effect=['before', 'after']):
            self.assertEqual(self.locate(), ('failed', 'account_changed'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_disabled_continuation_prevents_navigation(self):
        self.settings.write_text(json.dumps({'settings': {
            'task_continuation': False, 'resume_source_thread_id': self.SOURCE}}))
        self.assertEqual(self.locate(), ('failed', 'continuation_disabled'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def native_attempt(self, output, records=None):
        turn = '44444444-4444-4444-8444-444444444444'
        item = {'thread_id': self.TARGET, 'turn_id': turn, 'settings_file': str(self.settings)}
        interrupted = {'turn_id': turn, 'status': 'interrupted', 'error': None}
        with patch('nx.desktop_resume.latest_turn', side_effect=records, return_value=interrupted), \
             patch('nx.desktop_resume.continuation_guard', return_value=('mock-hash', '')), \
             patch('nx.storage.fingerprint', return_value='mock-hash'), \
             patch('nx.desktop_resume.title_prefix', return_value='Unique task'), \
             patch('nx.desktop_resume._invoke', return_value=output) as invoke, \
             patch('nx.desktop_location.locate_task') as locate, \
             patch('nx.app_bridge.resume_existing') as send:
            result = attempt_continuation(self.home, self.home/'helper.ps1', item,
                                          threading.Event(), Mock())
        locate.assert_not_called()
        send.assert_not_called()
        return result, invoke

    def test_native_route_has_no_bridge_navigation_dependency(self):
        before = {'turn_id': '44444444-4444-4444-8444-444444444444', 'status': 'interrupted'}
        after = {'turn_id': '55555555-5555-4555-8555-555555555555', 'status': 'inProgress', 'started_at': 1900000000}
        result, invoke = self.native_attempt(Mock(stdout='invoked:native_continue', returncode=0), [before, before, after])
        self.assertEqual(result, ('done', 'new_turn_observed'))
        invoke.assert_called_once()
        self.assertIn('-WaitForTarget', invoke.call_args.args[0])

    def test_ambiguous_native_target_is_terminal(self):
        result, invoke = self.native_attempt(Mock(stdout='skip:desktop_window_ambiguous', returncode=2))
        self.assertEqual(result, ('failed', 'desktop_window_ambiguous'))
        invoke.assert_called_once()

    def test_uncertain_native_click_never_repeats_or_uses_bridge(self):
        result, invoke = self.native_attempt(Mock(stdout='uncertain:native_continue', returncode=2))
        self.assertEqual(result, ('failed', 'action_outcome_unknown'))
        invoke.assert_called_once()

    def test_new_turn_before_native_action_prevents_click(self):
        before = {'turn_id': '44444444-4444-4444-8444-444444444444', 'status': 'interrupted'}
        result, invoke = self.native_attempt(Mock(), [before, {'turn_id': '55555555-5555-4555-8555-555555555555'}])
        self.assertEqual(result, ('skipped', 'newer_turn'))
        invoke.assert_not_called()


if __name__ == '__main__':
    unittest.main()
