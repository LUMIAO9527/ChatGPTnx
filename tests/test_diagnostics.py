"""Behavioral checks for private diagnostics and bounded monitor recovery."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.diagnostics import Diagnostics, query_summary


class DiagnosticsTests(unittest.TestCase):
    def test_error_messages_and_frame_locals_never_enter_diagnostic(self):
        log = Mock()
        diagnostics = Diagnostics(log, clock=lambda: 1000)
        secret = 'private@example.com Bearer fixture-secret D:\\private\\auth.json'
        try:
            raise RuntimeError(secret)
        except RuntimeError as error:
            diagnostics.operation_failed('switch', error)
            self.assertEqual(diagnostics.monitor_failed(error), 5)
        encoded = json.dumps(diagnostics.snapshot()) + str(log.mock_calls)
        for value in ('private@example.com', 'fixture-secret', 'auth.json'):
            self.assertNotIn(value, encoded)

    def test_monitor_backoff_is_bounded_and_recovers(self):
        d = Diagnostics(Mock(), clock=lambda: 1000)
        delays = [d.monitor_failed(TypeError('sensitive')) for _ in range(6)]
        self.assertEqual(delays, [5, 15, 60, 300, 300, 300])
        self.assertEqual(d.snapshot()['monitor']['retry_at'], 1300)
        d.monitor_ok()
        self.assertEqual(d.snapshot()['monitor']['state'], 'ok')
        self.assertEqual(d.monitor_failed(TypeError()), 5)

    def test_query_summary_is_allowlist_not_raw_object_export(self):
        account = {'email': 'secret@example.com', 'err': 'Bearer fixture',
                   'alias': 'private name', 'error_code': {'secret': 1},
                   'phase': ['private'], 'request_id': 'secret@example.com',
                   'tokens': {'access_token': 'fixture-secret'},
                   'ok': False, 'http_status': 403, 'retry_at': 2000}
        result = query_summary(account, 1)
        self.assertEqual(result['http_status'], 403)
        self.assertIsNone(result['error_code'])
        encoded = json.dumps(result)
        for value in ('secret', 'Bearer', 'private', 'tokens'):
            self.assertNotIn(value, encoded)

    def test_optional_query_diagnostic_preserves_only_safe_fields(self):
        result = query_summary({'ok': True, 'query_warning': {
            'scope': 'reset_credits', 'paused': True, 'error_code': 403,
            'http_status': 403, 'request_id': 'req_fixture123',
            'server_error_code': 'permission_denied', 'phase': 'reset_credits',
            'err': 'secret@example.com Bearer fixture-secret'}}, 1)
        self.assertEqual(result['optional_query']['request_id'], 'req_fixture123')
        self.assertEqual(result['optional_query']['error_code'], 403)
        self.assertTrue(result['ok'])
        self.assertNotIn('secret', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
