import json
from pathlib import Path
import sys
import tempfile
import threading
import os
import struct
import time
import uuid
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.app_bridge import resume_existing, discover_when_ready, BridgeUncertain, BridgeUnavailable, text_result, Pipe


class BridgeResumeTests(unittest.TestCase):
    SOURCE = '33333333-3333-4333-8333-333333333333'
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '_wip' / 'temp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.home = Path(self.temp.name)
        from test_refactor import credential
        from nx.storage import account_identity_key
        (self.home / 'auth.json').write_bytes(credential('bridge@example.com'))
        self.settings = self.home / 'settings.json'
        self.settings.write_text(json.dumps({'settings': {'resume_source_thread_id': self.SOURCE, 'task_continuation': True,
                                                         'resume_message': '继续'}}))
        self.item = {'thread_id': '11111111-1111-4111-8111-111111111111', 'turn_id': '44444444-4444-4444-8444-444444444444', 'settings_file': str(self.settings)}
        self.item['expected_account_key'] = account_identity_key(self.home/'auth.json', 'bridge@example.com')
        self.canonical = '11111111-1111-4111-8111-111111111111'
        self.record = {'turn_id': '44444444-4444-4444-8444-444444444444', 'status': 'failed',
                       'error': {'codexErrorInfo': 'usageLimitExceeded'}}
        self.snapshot = {'thread': {'id': '11111111-1111-4111-8111-111111111111', 'kind': 'codex', 'status': {'type': 'idle'}},
                         'turns': [{'id': '44444444-4444-4444-8444-444444444444', 'status': 'failed'}]}
        self.pipe = Mock()
        self.stop = threading.Event()
        self.stop_mock = Mock(is_set=lambda: False, wait=lambda _: False)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def result(value):
        return {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(value)}]}

    def run_resume(self, replies=None, records=None, *, interrupted=False):
        self.pipe.request.side_effect = replies or [self.result(self.snapshot),
                                                   self.result({'threadId': '11111111-1111-4111-8111-111111111111'})]
        with patch('nx.app_bridge.discover', return_value=self.pipe), \
             patch('nx.desktop_location.canonical_task', side_effect=lambda home, key, **kwargs: self.SOURCE if key == self.SOURCE else self.canonical), \
             patch('nx.desktop_resume.latest_turn', side_effect=records, return_value=self.record):
            return resume_existing(self.home, self.item, self.stop_mock, Mock(), interrupted=interrupted)

    def test_send_never_uses_editor_or_changes_message(self):
        result = self.run_resume(records=[self.record, {'turn_id': '55555555-5555-4555-8555-555555555555', 'status': 'inProgress', 'started_at': 1900000000}])
        self.assertEqual(result, ('done', 'new_turn_observed'))
        call = self.pipe.request.call_args_list[1]
        self.assertEqual(call.args[1]['arguments'], {'threadId': '11111111-1111-4111-8111-111111111111', 'hostId': 'local', 'prompt': '继续'})
        self.assertEqual(call.args[1]['threadId'], self.SOURCE)
        self.assertTrue(call.kwargs['side_effect'])
        self.pipe.close.assert_called_once()

    def test_missing_native_button_sends_only_for_exact_interrupted_turn(self):
        self.snapshot['turns'][0]['status'] = 'interrupted'
        self.record = {'turn_id': self.item['turn_id'], 'status': 'interrupted', 'error': None}
        result = self.run_resume(records=[self.record, {'turn_id': '55555555-5555-4555-8555-555555555555',
                                                       'status': 'inProgress', 'started_at': 1900000000}],
                                 interrupted=True)
        self.assertEqual(result, ('done', 'new_turn_observed'))
        self.assertEqual(self.pipe.request.call_count, 2)

    def test_interrupted_fallback_rejects_running_task(self):
        self.snapshot['turns'][0]['status'] = 'inProgress'
        self.record = {'turn_id': self.item['turn_id'], 'status': 'interrupted', 'error': None}
        self.assertEqual(self.run_resume(interrupted=True), ('failed', 'desktop_task_not_idle'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_runtime_thread_id_maps_to_canonical_bridge_target(self):
        self.item['thread_id'] = '22222222-2222-4222-8222-222222222222'
        result = self.run_resume(records=[self.record, {'turn_id': '55555555-5555-4555-8555-555555555555', 'status': 'inProgress', 'started_at': 1900000000}])
        self.assertEqual(result, ('done', 'new_turn_observed'))
        read_call, send_call = self.pipe.request.call_args_list
        self.assertEqual(read_call.args[1]['arguments']['threadId'], '11111111-1111-4111-8111-111111111111')
        self.assertEqual(send_call.args[1]['arguments']['threadId'], '11111111-1111-4111-8111-111111111111')

    def test_ack_timeout_is_not_retryable(self):
        result = self.run_resume([self.result(self.snapshot), BridgeUncertain()])
        self.assertEqual(result, ('failed', 'action_outcome_unknown'))
        self.assertEqual(self.pipe.request.call_count, 2)

    def test_negative_ack_is_also_not_automatically_retried(self):
        self.assertEqual(self.run_resume([self.result(self.snapshot), {'success': False}]),
                         ('failed', 'action_outcome_unknown'))

    def test_read_failure_is_terminal_without_sending(self):
        self.assertEqual(self.run_resume([BridgeUnavailable()]), ('failed', 'desktop_bridge_unavailable'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_bridge_startup_waits_before_any_write(self):
        with patch('nx.app_bridge.discover', side_effect=[
                BridgeUnavailable('desktop_bridge_unavailable'),
                BridgeUnavailable('desktop_bridge_unavailable'), self.pipe]) as discover:
            found = discover_when_ready(self.stop, self.home/'auth.json',
                                        __import__('nx.storage', fromlist=['fingerprint']).fingerprint(self.home/'auth.json'))
        self.assertIs(found, self.pipe)
        self.assertEqual(discover.call_count, 3)
        self.pipe.request.assert_not_called()

    def test_newer_turn_is_not_sent_again(self):
        self.snapshot['turns'][0]['id'] = '55555555-5555-4555-8555-555555555555'
        self.assertEqual(self.run_resume(), ('skipped', 'newer_turn'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_live_task_is_not_steered(self):
        self.snapshot['thread']['status']['type'] = 'running'
        self.assertEqual(self.run_resume(), ('failed', 'desktop_task_not_idle'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_unloaded_failed_task_can_resume_after_restart(self):
        self.snapshot['thread']['status']['type'] = 'notLoaded'
        self.assertEqual(self.run_resume(records=[self.record, {'turn_id': '55555555-5555-4555-8555-555555555555', 'status': 'inProgress', 'started_at': 1900000000}]),
                         ('done', 'new_turn_observed'))

    def test_unloaded_active_turn_is_not_sent(self):
        self.snapshot['thread']['status']['type'] = 'notLoaded'
        self.snapshot['turns'][0]['status'] = 'inProgress'
        self.assertEqual(self.run_resume(), ('failed', 'desktop_task_not_idle'))
        self.assertEqual(self.pipe.request.call_count, 1)

    def test_wrong_target_is_rejected(self):
        self.snapshot['thread']['id'] = 'other'
        self.assertEqual(self.run_resume(), ('failed', 'bridge_target_mismatch'))

    def test_disabled_automation_is_respected(self):
        self.settings.write_text(json.dumps({'settings': {'resume_source_thread_id': self.SOURCE, 'task_continuation': False}}))
        self.assertEqual(self.run_resume(), ('failed', 'continuation_disabled'))
        self.assertEqual(self.pipe.request.call_count, 0)

    def test_unrelated_failure_is_not_resumed(self):
        self.record['error']['codexErrorInfo'] = 'other'
        self.assertEqual(self.run_resume(), ('failed', 'unrelated_failure'))

    def test_invalid_message_is_not_sent(self):
        self.settings.write_text(json.dumps({'settings': {'resume_source_thread_id': self.SOURCE, 'task_continuation': True, 'resume_message': ''}}))
        self.assertEqual(self.run_resume(), ('failed', 'invalid_resume_message'))

    def test_account_change_prevents_dispatch(self):
        with patch('nx.storage.fingerprint', side_effect=['before', 'after']):
            self.assertEqual(self.run_resume(), ('failed', 'account_changed'))
        self.pipe.request.assert_not_called()

    def test_ack_without_observed_turn_is_not_replayed(self):
        self.assertEqual(self.run_resume(), ('failed', 'start_not_observed'))

    def test_invalid_result_is_rejected(self):
        for value in [{}, {'success': True}, {'success': True, 'contentItems': []}]:
            with self.assertRaises(BridgeUnavailable):
                text_result(value)

    def test_source_must_be_configured(self):
        self.settings.write_text('{"settings":{}}')
        self.assertEqual(self.run_resume(), ('failed', 'resume_source_unconfigured'))
        self.pipe.request.assert_not_called()

    def test_source_cannot_impersonate_target(self):
        self.canonical = self.SOURCE
        self.assertEqual(self.run_resume(), ('failed', 'resume_source_is_target'))
        self.pipe.request.assert_not_called()

    def test_missing_canonical_target_is_not_sent(self):
        self.canonical = None
        self.assertEqual(self.run_resume(), ('failed', 'task_identity_unavailable'))
        self.pipe.request.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Windows named pipe transport')
class PipeTransportTests(unittest.TestCase):
    def exchange(self, response, *, timeout=.5, delay=0, write=False):
        import win32pipe
        import win32file
        name = '\\\\.\\pipe\\nx-test-' + str(uuid.uuid4())
        server = win32pipe.CreateNamedPipe(name, win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
            1, 65536, 65536, 0, None)
        failures = []
        def serve():
            try:
                try:
                    win32pipe.ConnectNamedPipe(server, None)
                except Exception as error:
                    if error.winerror != 535:
                        raise
                def read(n):
                    data = b''
                    while len(data) < n:
                        data += win32file.ReadFile(server, n-len(data))[1]
                    return data
                n, = struct.unpack('<I', read(4))
                request = json.loads(read(n))
                self.assertEqual(request['method'], 'tools/list')
                time.sleep(delay)
                if response is not None:
                    payload = json.dumps(response).encode()
                    packet = struct.pack('<I', len(payload)) + payload
                    # Exercise fragmented headers and bodies, not only one write.
                    for i in range(0, len(packet), 3):
                        win32file.WriteFile(server, packet[i:i+3])
                    win32file.FlushFileBuffers(server)
            except Exception as error:
                failures.append(error)
            finally:
                server.Close()
        worker = threading.Thread(target=serve)
        worker.start()
        pipe = Pipe(name, timeout=timeout)
        try:
            return pipe.request('tools/list', {}, side_effect=write)
        finally:
            pipe.close()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            if response is not None:
                self.assertFalse(failures, str(failures))

    def test_fragmented_frame(self):
        self.assertEqual(self.exchange({'id': 1, 'jsonrpc': '2.0', 'result': {'tools': []}}),
                         {'tools': []})

    def test_read_timeout(self):
        with self.assertRaises(BridgeUnavailable):
            self.exchange(None, delay=.15, timeout=.05)

    def test_write_timeout_is_uncertain(self):
        with self.assertRaises(BridgeUncertain):
            self.exchange(None, delay=.15, timeout=.05, write=True)


if __name__ == '__main__':
    unittest.main()
