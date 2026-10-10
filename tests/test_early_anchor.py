"""Offline window lifecycle and work/dispatch races; synthetic accounts only."""
import base64
from contextlib import closing, nullcontext
import http.client
import http.server
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.early_anchor import Backend, EarlyAnchor, WorkWatcher, request_body
from nx.storage import Paths, atomic_bytes
from nx.settings import normalize_settings
from nx.quota import RPCError
from nx.quota_http import Query

EMAIL = 'spare@fixture.invalid'
SETTINGS = {'early_anchor': True, 'early_anchor_accounts': [EMAIL]}


class AnchorTests(unittest.TestCase):
    def policy_query(self):
        return Query(self.paths, lambda: {'query_timeout':45}, client=Mock(), clock=lambda:self.now)

    def test_unconfirmed_database_work_does_not_query_or_send(self):
        self.live = False
        engine = self.engine()
        for _ in range(7):
            engine.tick(SETTINGS); self.now += 6
        self.assertEqual((self.queries, self.posts), (0, 0))

    def test_preheat_obeys_existing_rate_limit_and_login_pause(self):
        query = self.policy_query()
        credential, _ = query._credential_hint(self.paths.snapshot(EMAIL), EMAIL)
        for code in (429, 403, 'reauth_required', 'network'):
            with self.subTest(code=code):
                query.policy.failed(EMAIL, credential, code, {'retry_after_at':self.now+600})
                self.engine(query=query).tick(SETTINGS)
                self.assertEqual((self.queries, self.posts), (0, 0))

    def test_preheat_network_failure_uses_shared_cooldown(self):
        query = self.policy_query()
        engine = self.engine(query=query)
        self.failure = 'query'
        for _ in range(7):
            engine.tick(SETTINGS); self.now += 6
        self.assertEqual((self.queries, self.posts), (1, 0))
        self.assertFalse(query.status(EMAIL)['ready'])
        self.now += 60; self.failure = None
        self.assertEqual(engine.tick(SETTINGS)[0]['status'], 'sent')
        self.assertTrue(query.status(EMAIL)['ready'])

    def test_one_live_confirmation_serves_selected_batch(self):
        other = 'second@fixture.invalid'
        self.credential(email=other)
        self.engine().tick({**SETTINGS, 'early_anchor_accounts':[EMAIL, other]})
        self.assertEqual(self.watcher.confirm.call_count, 1)
        self.assertEqual(self.posts, 2)

    def test_credentials_changed_during_query_do_not_update_quota(self):
        self.query_hook = lambda: self.credential('pro')
        self.assertEqual(self.engine().run(EMAIL)['error_code'], 'identity_mismatch')
        self.assertEqual((self.posts, len(self.values)), (0, 0))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = Paths(Path(self.tmp.name), Path(self.tmp.name) / 'home')
        self.paths.home.mkdir()
        self.now = 1791400000
        self.posts = self.queries = 0
        self.plan, self.used, self.week_used = 'plus', 0, 20
        self.reset = None
        self.other_resets = {}
        self.active = self.live = self.enabled = True
        self.current = 'current@fixture.invalid'
        self.failure = self.query_hook = None
        self.moving = False
        self.values = []
        self.watcher = Mock()
        self.watcher.poll.side_effect = lambda: [{'thread_id': 'fixture', 'turn_id': 'same-turn'}] if self.active else []
        self.watcher.confirm.side_effect = lambda: self.active and self.live
        self.watcher.still_working.side_effect = lambda proof: self.active
        self.credential()
        test = self
        class FakeBackend:
            def __init__(self, token, account_id):
                self.account_id, self.may_have_run = account_id, False
                self.email = account_id.removeprefix('fixture-')
            def quota(self):
                test.queries += 1
                if test.query_hook: test.query_hook()
                if test.failure == 'query': raise RPCError('synthetic read failed', 'network')
                if test.reset is not None and test.now >= test.reset:
                    test.reset, test.used = None, 0
                account_reset = test.reset if self.email == EMAIL else test.other_resets.get(self.email)
                remaining = 18000 if account_reset is None else int(account_reset - test.now)
                reset = test.now + remaining if account_reset is None else account_reset
                if test.moving: remaining, reset = 17999, test.now + 17999
                return {'account_id': self.account_id, 'email': self.email, 'plan_type': test.plan,
                    'rate_limit': {'allowed': test.used < 100 and test.week_used < 100,
                        'primary_window': {'used_percent': test.used, 'limit_window_seconds': 18000,
                            'reset_after_seconds': remaining, 'reset_at': reset},
                        'secondary_window': {'used_percent': test.week_used,
                            'limit_window_seconds': 604800, 'reset_at': test.now + 604800}}}
            def send(self, before_send=lambda: True, dispatch=lambda: nullcontext(True)):
                if test.failure == 'not_sent': raise RPCError('synthetic closed connection', 'network')
                with dispatch() as ready:
                    if not ready or not before_send(): raise RPCError('synthetic state changed', 'cancelled')
                    records = json.loads((test.paths.data / 'early-anchor.json').read_text())
                    assert any(record['status'] == 'pending' for record in records.values())
                    self.may_have_run = True
                    test.posts += 1
                if test.failure == 'unknown': raise OSError('synthetic lost response')
                if test.failure == 'rejected':
                    self.may_have_run = False
                    raise RPCError('synthetic rejection', 'anchor_request')
                if self.email == EMAIL: test.reset = test.now + 17998
                else: test.other_resets[self.email] = test.now + 17998
                return {'input_tokens': 15, 'output_tokens': 5, 'total_tokens': 20}
            def close(self): pass
        self.backend = FakeBackend

    def credential(self, plan='plus', email=EMAIL):
        payload = {'email': email, 'sub': 'fixture', 'https://api.openai.com/auth':
                   {'chatgpt_plan_type': plan, 'chatgpt_account_id': 'fixture-'+email}}
        middle = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        atomic_bytes(self.paths.snapshot(email), json.dumps({'tokens': {
            'id_token': 'fixture.' + middle + '.not-signed', 'account_id': 'fixture-'+email,
            'access_token': 'synthetic-only'}}).encode())

    def engine(self, **kwargs):
        return EarlyAnchor(self.paths, lambda: self.current, self.values.append,
            allowed=lambda email: self.enabled, backend=self.backend,
            clock=lambda: self.now, watcher=self.watcher, **kwargs)

    def record(self):
        return next(iter(json.loads((self.paths.data / 'early-anchor.json').read_text()).values()))

    def confirmed(self, engine):
        self.assertEqual(engine.run(EMAIL)['status'], 'sent')
        self.now += 4
        self.assertEqual(engine.run(EMAIL)['status'], 'started')

    def test_minimal_request_and_invalid_settings(self):
        data = json.loads(request_body())
        self.assertLess(len(request_body()), 900)
        self.assertNotIn('tools', data)
        self.assertEqual(len(data['input']), 2)
        self.assertFalse(data['store'])
        self.assertEqual(data['model'], 'gpt-6-luna')
        settings = normalize_settings({'early_anchor': 'yes', 'early_anchor_accounts': [False]})
        self.assertFalse(settings['early_anchor'])
        self.assertEqual(settings['early_anchor_accounts'], [])

    def test_twenty_tokens_and_stable_reads_confirm_start(self):
        self.confirmed(self.engine())
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.record()['usage']['total_tokens'], 20)
        self.assertEqual(self.values[-1]['windows'][0]['used'], 0)
        self.assertEqual(self.record()['reset_at'], self.reset)

    def test_single_or_moving_countdown_never_confirms_or_repeats(self):
        engine = self.engine()
        self.assertEqual(engine.run(EMAIL)['status'], 'sent')
        self.assertEqual(self.record()['status'], 'sent')
        self.moving = True
        for _ in range(4):
            self.now += 4
            self.assertEqual(engine.run(EMAIL)['status'], 'checking')
        self.assertEqual(self.posts, 1)
        self.assertNotEqual(self.record()['status'], 'started')

    def test_restart_reads_server_without_repeating(self):
        self.engine().run(EMAIL)
        self.now += 4
        self.assertEqual(self.engine().run(EMAIL)['status'], 'started')
        self.assertEqual(self.posts, 1)
        self.assertEqual(self.queries, 3)

    def test_same_long_turn_prepares_next_window_without_extra_polling(self):
        engine = self.engine()
        engine.tick(SETTINGS)
        self.now += 4
        engine.tick(SETTINGS)
        count = self.queries
        for _ in range(30):
            self.now += 2
            self.assertEqual(engine.tick(SETTINGS), [])
        self.assertEqual(self.queries, count)
        self.now = self.reset + 1
        engine.tick(SETTINGS)
        self.assertEqual(self.posts, 2)

    def test_idle_work_stops_next_round_and_restarts_when_work_returns(self):
        engine = self.engine()
        self.confirmed(engine)
        self.now = self.reset + 1
        self.active = False
        self.assertEqual(engine.tick(SETTINGS), [])
        self.assertEqual(self.posts, 1)
        self.active = True
        engine.tick(SETTINGS)
        self.assertEqual(self.posts, 2)

    def test_selected_exhausted_account_preheats_after_recovery_while_work_continues(self):
        self.used, self.reset = 100, self.now + 90
        engine = self.engine()
        engine.tick(SETTINGS)
        self.assertEqual(self.posts, 0)
        reads = self.queries
        self.now += 30
        engine.tick(SETTINGS)
        self.assertEqual((self.queries, self.posts), (reads, 0))
        self.now += 61
        engine.tick(SETTINGS)
        self.assertEqual(self.posts, 1)
        self.now += 4
        engine.tick(SETTINGS)
        self.assertEqual(self.record()['status'], 'started')
        self.assertEqual(self.posts, 1)

    def test_actual_server_recovery_overrides_old_local_lock(self):
        engine = self.engine()
        self.confirmed(engine)
        path = self.paths.data / 'early-anchor.json'
        records = json.loads(path.read_text())
        next(iter(records.values())).update(until=self.now+18000, reset_at=self.now+10)
        path.write_text(json.dumps(records))
        self.now += 11
        self.reset = None
        self.engine().run(EMAIL)
        self.assertEqual(self.posts, 2)

    def test_pre_send_failure_retries_safely_without_five_hour_lock(self):
        engine = self.engine()
        self.failure = 'not_sent'
        engine.tick(SETTINGS)
        self.assertEqual(self.posts, 0)
        count = self.queries
        self.now += 2
        engine.tick(SETTINGS)
        self.assertEqual(self.queries, count)
        self.failure = None
        self.engine().run(EMAIL)
        self.assertEqual(self.posts, 1)

    def test_lost_ack_only_reads_after_restart_then_confirms_timer(self):
        self.failure = 'unknown'
        self.assertEqual(self.engine().run(EMAIL)['status'], 'failed')
        self.assertEqual(self.record()['status'], 'uncertain')
        self.failure = None
        self.now += 4
        self.assertEqual(self.engine().run(EMAIL)['status'], 'checking')
        self.assertEqual(self.posts, 1)
        self.reset = self.now + 17990
        self.assertEqual(self.engine().run(EMAIL)['status'], 'checking')
        self.now += 4
        self.assertEqual(self.engine().run(EMAIL)['status'], 'started')
        self.assertEqual(self.posts, 1)

    def test_explicit_rejection_is_not_a_five_hour_lock(self):
        self.failure = 'rejected'
        self.engine().run(EMAIL)
        self.assertEqual(self.record()['status'], 'not_sent')
        self.failure = None
        self.engine().run(EMAIL)
        self.assertEqual(self.posts, 2)

    def test_query_failure_preserves_quota_and_does_not_reserve(self):
        self.values.append({'windows': [{'used': 100, 'resets_at': self.now+100}]})
        self.failure = 'query'
        self.engine().run(EMAIL)
        self.assertEqual(self.values, [{'windows': [{'used': 100, 'resets_at': self.now+100}]}])
        self.assertFalse((self.paths.data / 'early-anchor.json').exists())
        self.assertEqual(self.posts, 0)

    def test_current_pro_and_exhausted_or_ticking_accounts_skip(self):
        engine = self.engine()
        self.current = EMAIL
        engine.run(EMAIL)
        self.assertEqual(self.queries, 0)
        self.current = 'current@fixture.invalid'
        self.credential('pro')
        engine.run(EMAIL)
        self.assertEqual(self.queries, 0)
        self.credential()
        for used, week, reset, plan in ((100,20,None,'plus'),(0,100,None,'plus'),
                                      (0,20,self.now+17995,'plus'),(0,20,None,'pro')):
            self.used,self.week_used,self.reset,self.plan = used,week,reset,plan
            engine.run(EMAIL)
        self.assertEqual(self.posts, 0)

    def test_disabled_empty_selection_busy_and_idle_do_not_poll(self):
        engine = self.engine()
        self.watcher.poll.side_effect = AssertionError('must not poll')
        self.assertEqual(engine.tick({**SETTINGS,'early_anchor':False}), [])
        self.assertEqual(engine.tick({**SETTINGS,'early_anchor_accounts':[]}), [])
        self.assertEqual(engine.tick(SETTINGS,busy=True), [])

    def test_duplicate_selection_with_pro_current_sends_once(self):
        self.current = 'current-pro@fixture.invalid'
        self.engine().tick({**SETTINGS,'early_anchor_accounts':[EMAIL,EMAIL]})
        self.assertEqual(self.posts, 1)

    def test_two_selected_accounts_prepare_their_own_windows(self):
        other = 'second@fixture.invalid'
        self.credential(email=other)
        engine = self.engine()
        engine.tick({**SETTINGS, 'early_anchor_accounts': [EMAIL, other]})
        self.assertEqual(self.posts, 2)
        self.now += 4
        engine.tick({**SETTINGS, 'early_anchor_accounts': [EMAIL, other]})
        self.assertEqual(self.posts, 2)
        records = json.loads((self.paths.data/'early-anchor.json').read_text())
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r['status'] == 'started' for r in records.values()))

    def test_idle_live_runtime_or_task_ending_during_query_cannot_send(self):
        self.live = False
        self.engine().tick(SETTINGS)
        self.live = True
        self.query_hook = lambda: setattr(self,'active',False)
        self.engine().tick(SETTINGS)
        self.assertEqual(self.posts, 0)

    def test_settings_or_credentials_changed_before_dispatch_cannot_send(self):
        self.watcher.confirm.side_effect = lambda: (setattr(self,'enabled',False) or True)
        self.engine().run(EMAIL)
        self.enabled = True
        self.watcher.confirm.side_effect = lambda: True
        self.query_hook = lambda: self.credential('pro')
        self.engine().run(EMAIL)
        self.assertEqual(self.posts, 0)

    def test_switch_or_task_end_after_reservation_cannot_send(self):
        for field,value in (('current',EMAIL),('active',False)):
            engine = self.engine()
            save = engine._save
            def change(records):
                save(records)
                if next(iter(records.values()))['status']=='pending': setattr(self,field,value)
            with patch.object(engine,'_save',side_effect=change): engine.run(EMAIL)
            self.assertEqual(self.posts, 0)
            self.assertEqual(self.record()['status'],'not_sent')
            self.current,self.active = 'current@fixture.invalid',True

    def test_switch_or_resume_gate_has_priority(self):
        self.engine(dispatch=lambda email: nullcontext(False)).run(EMAIL)
        self.assertEqual(self.posts, 0)
        self.assertFalse((self.paths.data/'early-anchor.json').exists())

    def test_two_workers_racing_one_account_dispatch_only_once(self):
        engine = self.engine()
        barrier = threading.Barrier(2)
        self.watcher.confirm.side_effect = lambda: (barrier.wait(timeout=3) is not None)
        threads = [threading.Thread(target=engine.run,args=(EMAIL,)) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(self.posts, 1)

    def test_normal_refresh_wakes_changed_window(self):
        engine = self.engine()
        self.confirmed(engine)
        engine.observe_limits({'email':EMAIL,'ok':True,'windows':[
            {'duration_mins':300,'used':0,'resets_at':self.now+18000}]})
        self.assertEqual(engine.due[EMAIL], 0)

    def test_corrupt_journal_is_preserved_without_dispatch(self):
        path = self.paths.data/'early-anchor.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'{broken')
        self.engine().run(EMAIL)
        self.assertEqual(path.read_bytes(),b'{broken')
        self.assertEqual(self.posts,0)


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.path = self.home/'thread_history_1.sqlite'
        self.now = 1791400000
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,started_at INT,completed_at INT,status TEXT,rollout_ordinal INT)')
            db.commit()
        self.watcher = WorkWatcher(self.home,lambda:self.now,running=lambda:True)
        self.metadata = patch('nx.early_anchor.task_metadata',side_effect=lambda home,ids:
            {key:{'kind':'subagent' if key=='agent' else 'task','canonical_id':key} for key in ids})
        self.metadata.start()
        self.addCleanup(self.metadata.stop)

    def rows(self,rows):
        with closing(sqlite3.connect(self.path)) as db:
            db.executemany('INSERT INTO thread_turns VALUES(?,?,?,?,?,?)',rows)
            db.commit()

    def test_latest_turn_excludes_completed_history_and_subagents(self):
        self.rows([('old','t0',self.now-100,None,'inProgress',1),
            ('old','t1',self.now-50,self.now-49,'completed',2),
            ('live','t2',self.now-100,None,'inProgress',1),
            ('short','t3',self.now,self.now,'completed',1),
            ('agent','t4',self.now,None,'inProgress',1)])
        self.assertEqual([e['thread_id'] for e in self.watcher.poll()],['live'])

    def test_same_turn_stays_working_after_five_hours_and_a_day(self):
        self.rows([('live','t0',self.now-100,None,'inProgress',1)])
        self.assertEqual(len(self.watcher.poll()),1)
        self.now += 90000
        self.assertEqual(len(self.watcher.poll()),1)

    def test_closed_desktop_does_not_read_history(self):
        self.watcher.running = lambda:False
        with patch('nx.early_anchor.latest_database',side_effect=AssertionError('must not read')):
            self.assertEqual(self.watcher.poll(),[])

    def test_live_confirmation_reads_only_exact_active_turn(self):
        self.rows([('live','t0',self.now,None,'inProgress',1)])
        pipe = Mock()
        def result(turn='t0',status='inProgress',thread_status='active'):
            return {'success':True,'contentItems':[{'type':'inputText','text':json.dumps({
                'thread':{'id':'live','kind':'codex','status':{'type':thread_status}},
                'turns':[{'id':turn,'status':status}]})}]}
        with patch('nx.early_anchor.app_bridge.discover',return_value=pipe):
            for reply,expected in ((result(),True),(result('old-turn'),False),
                                  (result(status='completed'),False),(result(thread_status='notLoaded'),False)):
                pipe.request.return_value = reply
                self.assertEqual(bool(self.watcher.confirm()),expected)
        for call in pipe.request.call_args_list:
            self.assertEqual(call.args[1]['tool'],'read_thread')
            self.assertFalse(call.args[1]['arguments']['includeOutputs'])
            self.assertNotIn('side_effect',call.kwargs)

    def test_completed_latest_turn_invalidates_final_confirmation(self):
        self.rows([('live','t0',self.now,None,'inProgress',1)])
        proof = ('live','t0')
        self.assertTrue(self.watcher.still_working(proof))
        self.rows([('live','t1',self.now+1,self.now+2,'completed',2)])
        self.assertFalse(self.watcher.still_working(proof))


class TransportTests(unittest.TestCase):
    def test_quota_http_errors_keep_status_and_server_retry_after(self):
        for status in (401, 403, 429, 503):
            with self.subTest(status=status):
                response = Mock(status=status, headers={'Retry-After':'120'})
                response.read.return_value = b'{"error":{"code":"too_many_requests"}}'
                backend = Backend.__new__(Backend)
                backend.headers = {}; backend.conn = Mock()
                backend.conn.getresponse.return_value = response
                with self.assertRaises(RPCError) as caught:
                    backend.quota()
                self.assertEqual(caught.exception.code, 'reauth_required' if status==401 else status)
                self.assertEqual(caught.exception.diagnostics['http_status'], status)
                self.assertIsNotNone(caught.exception.diagnostics['retry_after_at'])
                response.close.assert_called()

    def test_no_retries_and_no_post_after_denied_guard(self):
        mode,counts = ['complete'],{}
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self,*args):pass
            def do_GET(self):
                raw = b'{"synthetic":true}'
                self.send_response(200);self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert body['model']=='gpt-6-luna' and len(body['input'])==2
                counts[mode[0]] = counts.get(mode[0],0)+1
                self.send_response(503 if mode[0]=='http' else 401 if mode[0]=='rejected' else 200)
                self.send_header('Content-Type','text/event-stream');self.end_headers()
                if mode[0]=='complete':
                    event = {'type':'response.completed','response':{'status':'completed',
                        'usage':{'input_tokens':15,'output_tokens':5,'total_tokens':20}}}
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
                self.close_connection = True
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with patch('nx.early_anchor.urllib.request.getproxies',return_value={}),patch(
                'nx.early_anchor.http.client.HTTPSConnection',side_effect=lambda *a,**k:
                    http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)):
                for case in ('http','stream','rejected','denied','complete'):
                    mode[0] = case
                    backend = Backend('synthetic-only','fixture')
                    try:
                        backend.quota()
                        if case=='complete':self.assertEqual(backend.send()['total_tokens'],20)
                        else:
                            with self.assertRaises(Exception):backend.send(lambda:case!='denied')
                            self.assertEqual(backend.may_have_run,case in ('http','stream'))
                    finally:backend.close()
            self.assertEqual(counts,{'http':1,'stream':1,'rejected':1,'complete':1})
        finally:server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
