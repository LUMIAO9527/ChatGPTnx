"""Offline tests of the once-per-window boundary and genuine work-start detection."""
import base64
from contextlib import closing
import http.client
import http.server
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.early_anchor import Backend, EarlyAnchor, WorkWatcher, request_body
from nx.storage import Paths, atomic_bytes
from nx.settings import normalize_settings


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = Paths(Path(self.tmp.name), Path(self.tmp.name) / 'home')
        self.paths.home.mkdir()
        self.now = 1791400000
        self.posts = 0
        self.queries = 0
        self.plan = 'plus'
        self.remaining = 18000
        self.failure = False
        self.values = []
        self.credential('spare@fixture.invalid')
        test = self
        class FakeBackend:
            def __init__(self, token, account_id): self.account_id = account_id
            def quota(self):
                test.queries += 1
                return {'account_id': self.account_id, 'email': 'spare@fixture.invalid', 'plan_type': test.plan,
                    'rate_limit': {'allowed': True, 'primary_window': {'used_percent': 0,
                        'limit_window_seconds': 18000, 'reset_after_seconds': test.remaining,
                        'reset_at': test.now + test.remaining},
                        'secondary_window': {'used_percent': 20, 'limit_window_seconds': 604800,
                                             'reset_at': test.now + 604800}}}
            def send(self):
                test.posts += 1
                records = json.loads((test.paths.data / 'early-anchor.json').read_text())
                assert next(iter(records.values()))['status'] == 'pending'
                if test.failure: raise OSError('synthetic connection ended')
                test.remaining = 17998
                return {'input_tokens': 15, 'output_tokens': 5, 'total_tokens': 20}
            def close(self): pass
        self.backend = FakeBackend

    def credential(self, email, plan='plus'):
        auth = {'chatgpt_plan_type': plan, 'chatgpt_account_id': 'fixture-account'}
        payload = {'email': email, 'sub': 'fixture', 'https://api.openai.com/auth': auth}
        middle = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        atomic_bytes(self.paths.snapshot(email), json.dumps({'tokens': {
            'id_token': 'fixture.' + middle + '.not-signed', 'account_id': 'fixture-account',
            'access_token': 'synthetic-only'}}).encode())

    def engine(self, current='current@fixture.invalid'):
        return EarlyAnchor(self.paths, lambda: current, self.values.append,
                           backend=self.backend, clock=lambda: self.now)

    def test_only_twenty_token_request_no_tools_or_context(self):
        body = request_body(); data = json.loads(body)
        self.assertLess(len(body), 900)
        self.assertNotIn('tools', data)
        self.assertEqual(len(data['input']), 2)
        self.assertFalse(data['store'])
        self.assertEqual(data['model'], 'gpt-6-luna')

    def test_completed_request_starts_zero_percent_window_and_updates_quota(self):
        result = self.engine().run('spare@fixture.invalid')
        self.assertEqual(result['status'], 'started')
        self.assertEqual(result['usage']['total_tokens'], 20)
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.values[-1]['windows'][0]['used'], 0)
        self.assertEqual(self.values[-1]['windows'][0]['resets_at'], self.now + 17998)

    def test_reload_and_new_turn_never_repeat_in_same_window(self):
        self.engine().run('spare@fixture.invalid')
        self.assertEqual(self.engine().run('spare@fixture.invalid')['status'], 'already_started')
        self.assertEqual(self.posts, 1)
        self.now += 18001; self.remaining = 18000
        self.engine().run('spare@fixture.invalid')
        self.assertEqual(self.posts, 2)

    def test_unknown_outcome_persisted_before_request_no_retry_after_restart(self):
        self.failure = True
        self.assertEqual(self.engine().run('spare@fixture.invalid')['status'], 'failed')
        self.assertEqual(self.engine().run('spare@fixture.invalid')['status'], 'already_started')
        self.assertEqual(self.posts, 1)

    def test_zero_percent_already_ticking_is_skipped(self):
        self.remaining = 17995
        self.assertEqual(self.engine().run('spare@fixture.invalid')['status'], 'already_started')
        self.assertEqual(self.posts, 0)

    def test_pro_and_current_account_never_query_or_send(self):
        self.engine('spare@fixture.invalid').run('spare@fixture.invalid')
        self.credential('spare@fixture.invalid', 'pro')
        self.engine().run('spare@fixture.invalid')
        self.assertEqual((self.posts, self.queries), (0, 0))

    def test_disabled_or_no_selection_never_read_work_or_send(self):
        with patch.object(WorkWatcher, 'poll', side_effect=AssertionError('no polling while disabled')):
            self.assertEqual(self.engine().tick({'early_anchor': False, 'early_anchor_accounts': ['spare@fixture.invalid']}), [])
            self.assertEqual(self.engine().tick({'early_anchor': True, 'early_anchor_accounts': []}), [])

    def test_actual_work_tick_only_selected_spare(self):
        with patch.object(WorkWatcher, 'poll', return_value=[{'thread_id': 'fixture', 'turn_id': 'new'}]):
            result = self.engine().tick({'early_anchor': True, 'early_anchor_accounts': ['spare@fixture.invalid']})
        self.assertEqual(result[0]['status'], 'started')
        self.assertEqual(self.posts, 1)

    def test_invalid_settings_do_not_enable_or_select_accounts(self):
        settings = normalize_settings({'early_anchor': 'yes', 'early_anchor_accounts': [False]})
        self.assertFalse(settings['early_anchor'])
        self.assertEqual(settings['early_anchor_accounts'], [])

    def test_started_work_detects_quick_completed_and_live_but_not_old_or_subagent(self):
        path = self.paths.home / 'thread_history_1.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT, turn_id TEXT, started_at INT, completed_at INT, status TEXT)')
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?,?)', [
                ('old', 't0', self.now - 100, self.now - 50, 'completed'),
                ('live', 't1', self.now - 100, None, 'inProgress'),
                ('short', 't2', self.now, self.now, 'completed'),
                ('agent', 't3', self.now, None, 'inProgress')])
            db.commit()
        watcher = WorkWatcher(self.paths.home, lambda: self.now)
        with patch('nx.early_anchor.desktop_task_events', side_effect=lambda h, events: [e for e in events if e['thread_id'] != 'agent']):
            first = watcher.poll()
            self.assertEqual({e['thread_id'] for e in first}, {'live', 'short'})
            self.assertEqual(watcher.poll(), [])


class TransportTests(unittest.TestCase):
    def test_production_transport_never_retries_error_or_interrupted_stream(self):
        mode, counts = ['complete'], {}
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args): pass
            def do_GET(self):
                raw = b'{"synthetic":true}'
                self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert body['model'] == 'gpt-6-luna' and len(body['input']) == 2
                counts[mode[0]] = counts.get(mode[0], 0) + 1
                self.send_response(503 if mode[0] == 'http' else 200)
                self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                if mode[0] == 'complete':
                    event = {'type': 'response.completed', 'response': {'status': 'completed',
                             'usage': {'input_tokens': 15, 'output_tokens': 5, 'total_tokens': 20}}}
                    self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode()); self.wfile.flush()
                self.close_connection = True
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with patch('nx.early_anchor.urllib.request.getproxies', return_value={}), patch(
                'nx.early_anchor.http.client.HTTPSConnection', side_effect=lambda *a, **k:
                    http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)):
                for case in ('http', 'stream', 'complete'):
                    mode[0] = case
                    backend = Backend('synthetic-only', 'fixture')
                    try:
                        self.assertEqual(backend.quota(), {'synthetic': True})
                        if case == 'complete': self.assertEqual(backend.send()['total_tokens'], 20)
                        else:
                            with self.assertRaises(Exception): backend.send()
                    finally: backend.close()
            self.assertEqual(counts, {'http': 1, 'stream': 1, 'complete': 1})
        finally: server.shutdown(); server.server_close()


if __name__ == '__main__': unittest.main()
