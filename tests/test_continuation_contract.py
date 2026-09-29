"""Two-route contract regressions. Synthetic data; no Windows E2E claim.

The integrated fixture uses real local SQLite/JSON/journaling. Only the desktop
pipe and UIA process are replaced with deterministic test doubles.
"""
from pathlib import Path
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from nx import app_bridge
from nx.desktop_resume import (continuation_guard, observe_start, attempt_continuation,
                               continuation_route, title_prefix)
from nx.desktop_location import canonical_task
from nx.resume_flow import ResumeCoordinator
from nx.storage import Paths, atomic_bytes, account_identity_key, fingerprint
from test_refactor import credential

TASK = '11111111-1111-4111-8111-111111111111'
ALIAS = '22222222-2222-4222-8222-222222222222'
SOURCE = '33333333-3333-4333-8333-333333333333'
TURN = '44444444-4444-4444-8444-444444444444'
NEW = '55555555-5555-4555-8555-555555555555'
OTHER = '66666666-6666-4666-8666-666666666666'
EMAIL = 'contract@example.com'


def reply(value):
    return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(value)}]}


class ContinuationContractTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / '_wip' / 'temp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.tmp.cleanup)
        self.paths = Paths(Path(self.tmp.name), Path(self.tmp.name)/'desktop')
        atomic_bytes(self.paths.auth, credential(EMAIL))
        atomic_bytes(self.paths.snapshot(EMAIL), credential(EMAIL))
        self.settings = self.paths.data/'state.json'
        self.settings.write_text(json.dumps({'settings': {
            'task_continuation': True, 'resume_source_thread_id': SOURCE,
            'resume_message': '接着核对测试结果'}}), encoding='utf-8')
        with sqlite3.connect(self.paths.home/'state_1.sqlite') as db:
            db.execute('CREATE TABLE threads (id TEXT, archived INTEGER, rollout_path TEXT, title TEXT)')
            db.execute('INSERT INTO threads VALUES (?,0,?,?)', (TASK, f'rollout_{ALIAS}.jsonl', 'Synthetic contract task'))
            db.execute('INSERT INTO threads VALUES (?,0,NULL,?)', (SOURCE, 'Synthetic caller task'))
        db.close()
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute('CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT, '
                       'error_json TEXT, started_at INTEGER, completed_at INTEGER, rollout_ordinal INTEGER)')
        db.close()
        self.add_turn(TURN, 'failed', 1)
        self.item = {'thread_id': ALIAS, 'turn_id': TURN, 'settings_file': str(self.settings),
                     'expected_account_key': account_identity_key(self.paths.auth, EMAIL)}
        self.stop = threading.Event()
        self.fast_stop = Mock(is_set=lambda: False, wait=lambda _: False)
        self.log = Mock()

    def add_turn(self, turn, status, ordinal, started=1900000000):
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                       (ALIAS, turn, status, json.dumps({'codexErrorInfo': 'usageLimitExceeded'})
                        if status == 'failed' else None, started, None, ordinal))
        db.close()

    def coordinator(self):
        return ResumeCoordinator(self.paths, lambda: EMAIL, self.stop, self.log,
                                 Mock(), threading.Lock())

    def queue(self, c, task=ALIAS):
        ident = c.prepare('previous@example.com', EMAIL, 'manual', [{'thread_id': task, 'turn_id': TURN}])
        c.switched(ident)
        return ident

    def pipe(self, *, acknowledgement=True):
        pipe = Mock()
        def request(method, params, **kw):
            tool = params['tool']
            if tool == 'read_thread':
                self.assertEqual(params['arguments']['threadId'], TASK)
                self.assertFalse(params['arguments']['includeOutputs'])
                return reply({'thread': {'id': TASK, 'kind': 'codex', 'status': {'type': 'idle'}},
                              'turns': [{'id': TURN, 'status': 'failed'}]})
            self.assertEqual(tool, 'send_message_to_thread')
            self.assertTrue(kw['side_effect'])
            self.assertEqual(params['threadId'], SOURCE)
            self.assertEqual(params['arguments'], {'threadId': TASK, 'hostId': 'local', 'prompt': '接着核对测试结果'})
            self.add_turn(NEW, 'inProgress', 2)
            if not acknowledgement:
                raise app_bridge.BridgeUncertain('test_lost_ack')
            return reply({'threadId': TASK, 'turnId': NEW})
        pipe.request.side_effect = request
        return pipe

    def test_real_local_state_to_bridge_to_durable_observation(self):
        c = self.coordinator(); ident = self.queue(c)
        _, item = c._ready()
        pipe = self.pipe()
        with patch('nx.app_bridge.discover', return_value=pipe), patch('nx.desktop_resume._invoke') as native:
            state, reason = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                                item, self.fast_stop, self.log)
        native.assert_not_called()
        self.assertEqual((state, reason), ('done', 'new_turn_observed'))
        self.assertEqual(pipe.request.call_count, 2)
        c._persist_outcome(ident, item, state, reason)
        saved = json.loads(c.path.read_text())
        self.assertEqual(saved['sessions'][0]['items'][0]['observed_turn_id'], NEW)
        self.assertEqual(saved['sessions'][0]['items'][0]['attempts'], 1)
        self.assertEqual(len(saved['claims']), 1)

    def test_quota_handoff_then_overload_recovers_with_second_exact_turn(self):
        c = self.coordinator(); ident = self.queue(c)

        def pipe_for(original, status, next_turn, ordinal):
            pipe = Mock()
            def request(method, params, **kwargs):
                self.assertEqual(params['arguments']['threadId'], TASK)
                if params['tool'] == 'read_thread':
                    return reply({'thread': {'id': TASK, 'kind': 'codex',
                                             'status': {'type': 'idle'}},
                                  'turns': [{'id': original, 'status': status}]})
                self.assertEqual(params['tool'], 'send_message_to_thread')
                self.add_turn(next_turn, 'inProgress', ordinal)
                return reply({'threadId': TASK, 'turnId': next_turn})
            pipe.request.side_effect = request
            return pipe

        _, first = c._ready()
        with patch('nx.app_bridge.discover', return_value=pipe_for(TURN, 'failed', NEW, 2)):
            state, reason = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                                 first, self.fast_stop, self.log)
        self.assertEqual((state, reason), ('done', 'new_turn_observed'))
        c._persist_outcome(ident, first, state, reason)
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute('UPDATE thread_turns SET status=?, error_json=? WHERE turn_id=?',
                       ('failed', json.dumps({'codexErrorInfo': 'serverOverloaded'}), NEW))
        db.close()
        self.assertIsNone(c._ready())
        queued = c.sessions[0]['items'][0]
        self.assertEqual((queued['state'], queued['turn_id']), ('waiting', NEW))
        queued['next_try'] = 0
        _, second = c._ready()
        with patch('nx.app_bridge.discover', return_value=pipe_for(NEW, 'failed', OTHER, 3)):
            state, reason = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                                 second, self.fast_stop, self.log)
        self.assertEqual((state, reason), ('done', 'new_turn_observed'))
        c._persist_outcome(ident, second, state, reason)
        saved = json.loads(c.path.read_text())
        self.assertEqual(saved['sessions'][0]['items'][0]['observed_turn_id'], OTHER)
        self.assertEqual(saved['sessions'][0]['items'][0]['attempts'], 2)
        self.assertEqual(len(saved['claims']), 2)

    def test_archived_configured_source_can_send_to_active_target(self):
        with sqlite3.connect(self.paths.home/'state_1.sqlite') as db:
            db.execute('UPDATE threads SET archived=1 WHERE id=?', (SOURCE,))
        db.close()
        self.assertEqual(canonical_task(self.paths.home, SOURCE, allow_archived=True), SOURCE)
        self.assertIsNone(canonical_task(self.paths.home, SOURCE))
        pipe = self.pipe()
        with patch('nx.app_bridge.discover', return_value=pipe):
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.fast_stop, self.log)
        self.assertEqual(result, ('done', 'new_turn_observed'))

    def test_stale_running_index_uses_exact_interrupted_desktop_turn(self):
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute("UPDATE thread_turns SET status='inProgress', error_json=NULL")
        db.close()
        pipe = Mock()
        continued = False
        def request(method, params, **kwargs):
            if params['tool'] == 'navigate_to_codex_page':
                return reply({'navigated': True})
            self.assertEqual(params['tool'], 'read_thread')
            turn = ({'id': TURN, 'status': 'inProgress', 'startedAt': 1900000000}
                    if continued else {'id': TURN, 'status': 'interrupted'})
            return reply({'thread': {'id': TASK, 'kind': 'codex', 'status': {'type': 'idle'}},
                          'turns': [turn]})
        pipe.request.side_effect = request
        def native_click(command):
            nonlocal continued
            continued = True
            return Mock(stdout='invoked:native_continue', returncode=0)
        with patch('nx.app_bridge.discover', return_value=pipe), \
             patch('nx.desktop_resume._invoke', side_effect=native_click) as native:
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.fast_stop, self.log)
        self.assertEqual(result, ('done', 'native_turn_resumed'))
        self.assertEqual(self.item['observed_turn_id'], TURN)
        self.assertEqual(pipe.request.call_count, 3)
        native.assert_called_once()

    def test_stale_running_index_does_not_send_to_running_desktop_turn(self):
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute("UPDATE thread_turns SET status='inProgress', error_json=NULL")
        db.close()
        pipe = Mock()
        pipe.request.return_value = reply({
            'thread': {'id': TASK, 'kind': 'codex', 'status': {'type': 'active'}},
            'turns': [{'id': TURN, 'status': 'inProgress'}]})
        with patch('nx.app_bridge.discover', return_value=pipe):
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.fast_stop, self.log)
        self.assertEqual(result, ('failed', 'desktop_task_not_idle'))
        self.assertEqual(pipe.request.call_count, 1)

    def test_lost_ack_with_real_started_turn_still_cannot_replay(self):
        c = self.coordinator(); ident = self.queue(c)
        _, item = c._ready(); pipe = self.pipe(acknowledgement=False)
        with patch('nx.app_bridge.discover', return_value=pipe):
            state, reason = app_bridge.resume_existing(self.paths.home, item, self.fast_stop, self.log)
        self.assertEqual((state, reason), ('failed', 'action_outcome_unknown'))
        c._persist_outcome(ident, item, state, reason)
        self.assertFalse(c.retry_task(ident, ALIAS)['ok'])
        c.clear_history()
        replacement = self.coordinator(); self.queue(replacement)
        self.assertIsNone(replacement._ready())
        self.assertEqual(pipe.request.call_count, 2)

    def test_editor_fields_cannot_block_bridge_route(self):
        for editor in ({'text': 'synthetic draft'}, {'selection': [1, 4]}, {'attachments': ['synthetic']}):
            with self.subTest(editor=list(editor)):
                self.item['editor_state'] = editor
                pipe = self.pipe()
                with patch('nx.app_bridge.discover', return_value=pipe), patch('nx.desktop_resume._invoke') as native:
                    state, reason = app_bridge.resume_existing(self.paths.home, self.item, self.fast_stop, self.log)
                self.assertEqual((state, reason), ('done', 'new_turn_observed'))
                native.assert_not_called()
                with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
                    db.execute('DELETE FROM thread_turns WHERE turn_id=?', (NEW,))
                db.close()
                self.assertEqual(self.item['editor_state'], editor)

    def test_account_mismatch_prevents_even_bridge_discovery(self):
        atomic_bytes(self.paths.auth, credential('other@example.com'))
        with patch('nx.app_bridge.discover') as discover:
            self.assertEqual(app_bridge.resume_existing(self.paths.home, self.item, self.fast_stop, self.log),
                             ('failed', 'account_changed'))
        discover.assert_not_called()

    def test_same_person_different_workspace_is_rejected(self):
        atomic_bytes(self.paths.auth, credential(EMAIL, workspace='different-workspace'))
        self.assertEqual(continuation_guard(self.paths.home, self.item), (None, 'account_changed'))

    def test_missing_queued_identity_is_not_inferred_from_stable_auth(self):
        self.item.pop('expected_account_key')
        self.assertEqual(continuation_guard(self.paths.home, self.item), (None, 'account_guard_unavailable'))

    def test_missing_subject_cannot_fall_back_to_email_identity(self):
        atomic_bytes(self.paths.auth, b'{"tokens":{"account_id":"test-workspace"}}')
        self.assertEqual(continuation_guard(self.paths.home, self.item), (None, 'account_guard_unavailable'))

    def test_atomic_auth_replacement_invalidates_same_size_mtime_cache(self):
        original = self.paths.auth.stat()
        self.assertEqual(continuation_guard(self.paths.home, self.item)[1], '')
        atomic_bytes(self.paths.auth, credential('contrast@example.com'))
        os.utime(self.paths.auth, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(continuation_guard(self.paths.home, self.item), (None, 'account_changed'))

    def test_invalid_original_turn_id_has_no_desktop_actions(self):
        self.item['turn_id'] = 'invalid'
        with patch('nx.app_bridge.discover') as discover, patch('nx.desktop_resume._invoke') as native:
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.stop, self.log)
        self.assertEqual(result, ('failed', 'invalid_task_id'))
        discover.assert_not_called(); native.assert_not_called()

    def test_route_is_selected_only_from_exact_turn_and_status(self):
        quota = {'turn_id': TURN, 'status': 'failed',
                 'error': {'codexErrorInfo': 'usageLimitExceeded'}}
        self.assertEqual(continuation_route(quota, TURN), ('message', None))
        self.assertEqual(continuation_route({**quota, 'status': 'interrupted'}, TURN),
                         ('native', None))
        self.assertEqual(continuation_route({**quota, 'status': 'inProgress'}, TURN),
                         ('native', None))
        self.assertEqual(continuation_route(quota, NEW),
                         (None, ('skipped', 'newer_turn')))
        self.assertEqual(continuation_route({**quota, 'error': {'codexErrorInfo': 'serverOverloaded'}}, TURN),
                         ('message', None))
        self.assertEqual(continuation_route({**quota, 'error': {
            'codexErrorInfo': 'other', 'message': 'network error'}}, TURN), ('message', None))
        self.assertEqual(continuation_route({**quota, 'error': {
            'codexErrorInfo': 'other', 'message': 'unauthorized 401'}}, TURN),
            (None, ('failed', 'unrelated_failure')))

    def test_interrupted_task_uses_bridge_only_when_native_button_is_missing(self):
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute("UPDATE thread_turns SET status='interrupted'")
        db.close()
        with patch('nx.desktop_location.locate_task', return_value=('located', 'task_opened_by_id')), \
             patch('nx.app_bridge.resume_existing', return_value=('done', 'new_turn_observed')) as send, patch('nx.desktop_resume._invoke',
                return_value=Mock(stdout='skip:native_continue_unavailable', returncode=2)) as native:
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.stop, self.log)
        self.assertEqual(result, ('done', 'new_turn_observed'))
        self.assertTrue(send.call_args.kwargs['interrupted']); native.assert_called_once()

    def test_bridge_unavailable_never_falls_back_to_native(self):
        with patch('nx.app_bridge.discover', side_effect=app_bridge.BridgeUnavailable()), \
             patch('nx.desktop_resume._invoke') as native:
            result = attempt_continuation(self.paths.home, self.paths.desktop_resume_ps1,
                                          self.item, self.stop, self.log)
        self.assertEqual(result, ('failed', 'desktop_bridge_unavailable'))
        native.assert_not_called()

    def test_new_id_without_started_state_is_not_success(self):
        self.add_turn(NEW, 'pending', 2)
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth)), ('failed', 'start_not_observed'))
        self.assertNotIn('observed_turn_id', self.item)

    def test_started_state_without_start_timestamp_is_not_success(self):
        self.add_turn(NEW, 'inProgress', 2, started=None)
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth)), ('failed', 'start_not_observed'))

    def test_ack_turn_mismatch_is_uncertain_not_success(self):
        self.add_turn(OTHER, 'inProgress', 2)
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth), expected_turn=NEW), ('failed', 'action_outcome_unknown'))

    def test_native_same_turn_transition_can_be_confirmed(self):
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute("UPDATE thread_turns SET status='inProgress'")
        db.close()
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth), allow_same_turn=True), ('done', 'native_turn_resumed'))
        self.assertEqual(self.item['observed_turn_id'], TURN)

    def test_immediate_new_turn_failure_is_stored_not_success(self):
        self.add_turn(NEW, 'failed', 2)
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth)), ('failed', 'resumed_turn_limit'))
        self.assertEqual(self.item['observed_turn_id'], NEW)

    def test_new_turn_overload_is_not_misreported_as_routing_failure(self):
        self.add_turn(NEW, 'failed', 2)
        with sqlite3.connect(self.paths.home/'thread_history_1.sqlite') as db:
            db.execute('UPDATE thread_turns SET error_json=? WHERE turn_id=?',
                       (json.dumps({'codexErrorInfo': 'serverOverloaded',
                                    'message': 'Selected model is at capacity.'}), NEW))
        db.close()
        self.assertEqual(observe_start(self.paths.home, self.item, self.fast_stop,
            expected_auth=fingerprint(self.paths.auth)), ('failed', 'resumed_turn_overloaded'))
        self.assertEqual(self.item['observed_turn_id'], NEW)

    def test_alias_collision_against_exact_id_is_ambiguous(self):
        with sqlite3.connect(self.paths.home/'state_1.sqlite') as db:
            db.execute('INSERT INTO threads VALUES (?,0,NULL,?)', (ALIAS, 'Another synthetic task'))
        db.close()
        self.assertIsNone(canonical_task(self.paths.home, ALIAS))
        self.assertIsNone(title_prefix(self.paths.home, ALIAS))

    def test_claim_survives_clear_restart_and_alternate_task_alias(self):
        c = self.coordinator(); ident = self.queue(c); _, item = c._ready()
        c._persist_outcome(ident, item, 'failed', 'action_outcome_unknown')
        c.clear_history(); c = self.coordinator(); self.queue(c, TASK)
        self.assertIsNone(c._ready())
        self.assertEqual(c.sessions[-1]['items'][0]['reason'], 'duplicate_attempt')

    def test_claim_is_on_disk_before_action_and_contains_no_plain_task_id(self):
        c = self.coordinator(); self.queue(c); self.assertIsNotNone(c._ready())
        claims = json.loads(c.path.read_text())['claims']
        self.assertEqual(len(claims), 1)
        self.assertRegex(claims[0], r'^[0-9a-f]{64}$')
        self.assertNotIn(TURN, str(claims)); self.assertNotIn(ALIAS, str(claims))

    def test_claim_write_failure_cannot_return_executable_work(self):
        c = self.coordinator(); self.queue(c)
        with patch('nx.resume_flow.atomic_bytes', side_effect=PermissionError('synthetic-denied')):
            with self.assertRaises(PermissionError): c._ready()
        self.assertEqual(c.claims, set())
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'waiting')

    def test_stored_acting_is_uncertain_after_restart_without_retry(self):
        c = self.coordinator(); ident = self.queue(c); c._ready()
        replacement = self.coordinator()
        self.assertIsNone(replacement._ready())
        self.assertEqual(replacement.sessions[0]['items'][0]['reason'], 'action_outcome_unknown')
        self.assertFalse(replacement.retry_task(ident, ALIAS)['ok'])

    def test_preflight_failure_is_retried_after_a_delay_without_replaying_unknown_effects(self):
        c = self.coordinator(); ident = self.queue(c); _, item = c._ready()
        c._persist_outcome(ident, item, 'failed', 'desktop_bridge_unavailable')
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'waiting')
        self.assertGreater(c.sessions[0]['items'][0]['next_try'], 0)
        for _ in range(3): self.assertIsNone(c._ready())
        c.sessions[0]['items'][0]['next_try'] = 0
        self.assertIsNotNone(c._ready())
        self.assertEqual(len(c.claims), 1)

    def test_only_pre_action_desktop_transition_can_release_claim(self):
        c = self.coordinator(); ident = self.queue(c); _, item = c._ready()
        c._persist_outcome(ident, item, 'defer', 'desktop_transitioning')
        self.assertEqual(c.claims, set())
        self.assertEqual(c.sessions[0]['items'][0]['attempts'], 0)
        c.sessions[0]['items'][0]['next_try'] = 0
        self.assertIsNotNone(c._ready())

    def test_corrupt_journal_blocks_actions_across_restart_and_preserves_bytes(self):
        raw = b'{synthetic-corrupt-journal'
        (self.paths.data/'resume.json').write_bytes(raw)
        c = self.coordinator(); self.assertEqual(c.recovery_path.read_bytes(), raw)
        ident = self.queue(c); self.assertIsNone(c._ready())
        self.assertTrue(c.blocked)
        self.assertEqual(c.sessions[0]['items'][0]['reason'], 'resume_state_unavailable')
        c = self.coordinator(); self.assertTrue(c.blocked)
        self.assertFalse(c.retry_task(ident, ALIAS)['ok'])

    def test_malformed_claims_cannot_silently_disable_deduplication(self):
        (self.paths.data/'resume.json').write_text('{"claims":[false,"invalid"]}')
        c = self.coordinator(); self.queue(c)
        self.assertTrue(c.blocked); self.assertIsNone(c._ready())


class BridgeCatalogTests(unittest.TestCase):
    @staticmethod
    def catalog():
        return {'tools': [{'namespace': 'codex_app', 'name': name,
                           'inputSchema': {'properties': {key: {} for key in keys}}}
                          for name, keys in [('read_thread', ['threadId']),
                                             ('send_message_to_thread', ['threadId', 'prompt'])]]}

    def test_stale_pipe_names_do_not_count_as_ambiguity(self):
        names = [f'codex-browser-use-{i:08x}-0000-4000-8000-000000000000'
                 for i in range(14)]
        with patch.dict('nx.app_bridge.os.environ', {'CODEX_APP_TOOLS_PIPE_PATH': ''}), \
             patch('nx.app_bridge.os.listdir', return_value=names), \
             patch('nx.app_bridge.os.name', 'nt'):
            paths = app_bridge.candidates()
        self.assertEqual(len(paths), 14)
        live = Mock(); live.request.return_value = self.catalog()
        with patch('nx.app_bridge.candidates', return_value=paths), \
             patch('nx.app_bridge.Pipe', side_effect=lambda path, timeout: live if path == paths[-1] else (_ for _ in ()).throw(OSError())):
            selected = app_bridge.discover()
        self.assertIs(selected, live)
        self.assertEqual(live.request.call_count, 1)

    def test_current_executor_pipe_wins_over_other_compatible_pipes(self):
        current, other = Mock(), Mock()
        current.request.return_value = other.request.return_value = self.catalog()
        inherited = r'\\.\pipe\codex-browser-use-11111111-1111-4111-8111-111111111111'
        with patch.dict('nx.app_bridge.os.environ', {'CODEX_APP_TOOLS_PIPE_PATH': inherited}), \
             patch('nx.app_bridge.candidates', return_value=[inherited, 'another-live-pipe']), \
             patch('nx.app_bridge.Pipe', side_effect=[current, other]):
            selected = app_bridge.discover()
        self.assertIs(selected, current)
        current.close.assert_not_called()
        other.request.assert_not_called()

    def test_multiple_compatible_pipes_are_closed_and_rejected(self):
        first, second = Mock(), Mock()
        first.request.return_value = second.request.return_value = self.catalog()
        with patch('nx.app_bridge.candidates', return_value=['a', 'b']), \
             patch('nx.app_bridge.Pipe', side_effect=[first, second]):
            with self.assertRaisesRegex(app_bridge.BridgeUnavailable, 'desktop_bridge_ambiguous'):
                app_bridge.discover()
        first.close.assert_called_once(); second.close.assert_called_once()
        self.assertTrue(all(c.args[0] == 'tools/list' for p in (first, second) for c in p.request.call_args_list))

    def test_malformed_tool_catalog_fails_before_any_write(self):
        pipe = Mock(); pipe.request.return_value = {'tools': [{'namespace': 'codex_app', 'name': 'read_thread'}]}
        with patch('nx.app_bridge.candidates', return_value=['a']), patch('nx.app_bridge.Pipe', return_value=pipe):
            with self.assertRaises(app_bridge.BridgeUnavailable): app_bridge.discover()
        pipe.close.assert_called_once()
        self.assertEqual(pipe.request.call_args.args[0], 'tools/list')

    def test_malformed_receipts_are_rejected(self):
        for value in (None, [], {'success': True, 'contentItems': [{}]},
                      {'success': True, 'contentItems': [{'type': 'inputText', 'text': '[]'}]},
                      {'success': True, 'contentItems': [{'type': 'inputText', 'text': '{}'}]*2}):
            with self.subTest(value=value), self.assertRaises(app_bridge.BridgeUnavailable):
                app_bridge.text_result(value)

    def test_changed_or_invalid_ack_turn_id_is_uncertain(self):
        for value in ({'threadId': OTHER}, {'threadId': TASK, 'turnId': 'invalid'}):
            pipe = Mock(); pipe.request.return_value = reply(value)
            with self.assertRaises(app_bridge.BridgeUncertain):
                app_bridge.dispatch_message(pipe, SOURCE, TASK, 'synthetic', call_id='nx-synthetic')
            pipe.request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
