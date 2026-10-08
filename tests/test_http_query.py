"""Credential ownership, bounded HTTP errors and real wire schema regression."""
import io
import http.client
import json
import sys
import tempfile
import threading
import time
import socket
import ssl
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nx.quota import Query, RPCError
from nx.quota_http import HTTPClient, NoRedirect, MAX_BYTES, reset_payload, credential_fingerprint
from nx.query_policy import account_key
from nx.diagnostics_http import ERROR_BYTES, retry_after, safe_fields
from nx.credentials import encode_credential_bytes
from nx.storage import Paths, atomic_bytes
from test_core import auth


def response():
    return {'account_id':'fixture-a@example.com','email':'a@example.com','plan_type':'plus',
            'rate_limit':{'primary_window':{'used_percent':25,'limit_window_seconds':18000,'reset_at':1900000000},
                          'secondary_window':None},
            'credits':{'has_credits':True,'unlimited':False,'balance':'1.25'},
            'rate_limit_reset_credits':{'available_count':2}}


class HTTPQueryTests(unittest.TestCase):
    def test_quota_timestamp_is_captured_before_optional_reset_query(self):
        before = self.now
        def get(endpoint, *args):
            if endpoint == '/wham/usage':
                return response()
            self.now += 30
            return {'available_count':2, 'credits':[]}
        self.client.get.side_effect = get
        value = self.q.run('a@example.com', True)
        self.assertTrue(value['ok'])
        self.assertEqual(value['fetched_at'], before)
        self.assertEqual(self.now, before+30)

    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'_wip';scratch.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(self.temp.cleanup)
        self.paths=Paths(Path(self.temp.name),Path(self.temp.name)/'home')
        self.saved=json.loads(auth('a@example.com'));self.saved['tokens']['access_token']='fixture-access'
        self.write()
        self.client=Mock()
        self.client.get.side_effect=lambda endpoint,*args: response() if endpoint=='/wham/usage' else {'available_count':2,'credits':[]}
        self.now=1800000000
        self.q=self.new_query()

    def new_query(self):
        return Query(self.paths,lambda:{'query_timeout':45},client=self.client,clock=lambda:self.now)

    def write(self):
        atomic_bytes(self.paths.auth,json.dumps(self.saved).encode())

    def test_live_and_snapshot_queries_never_spawn_or_write_credentials(self):
        atomic_bytes(self.paths.snapshot('a@example.com'),self.paths.auth.read_bytes())
        before={p:p.read_bytes() for p in (self.paths.auth,self.paths.snapshot('a@example.com'))}
        with patch('subprocess.Popen',side_effect=AssertionError('must not spawn')):
            for current in (True,False):
                result=self.q.run('a@example.com',current)
                self.assertTrue(result['ok']);self.assertEqual(result['windows'][0]['duration_mins'],300)
                self.assertEqual(result['credit_info']['balance'],'1.25')
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertFalse(list(self.paths.data.glob('query-*')))

    def test_401_stops_retries_until_credential_changes(self):
        self.client.get.side_effect=RPCError('登录已失效','reauth_required')
        self.assertEqual(self.q.run('a@example.com',True)['error_code'],'reauth_required')
        self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,1)
        self.saved['tokens']['access_token']='new-fixture-access';self.write()
        self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)

    def test_service_errors_defer_future_queries_without_refreshing_login(self):
        for code in (429,500,'network'):
            with self.subTest(code=code):
                self.q.resume('a@example.com')
                self.client.get.reset_mock();self.client.get.side_effect=RPCError('temporary',code)
                self.assertEqual(self.q.run('a@example.com',True)['error_code'],code)
                self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,1)
                self.assertFalse(self.q.ready('a@example.com',True))
                self.now+=60
                self.assertTrue(self.q.ready('a@example.com',True))
                self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)
                self.now+=120
                self.assertTrue(all(c.args[0]=='/wham/usage' for c in self.client.get.call_args_list))

    def test_403_pause_survives_query_recreation_until_explicit_resume(self):
        self.client.get.side_effect=RPCError('secret a@example.com fixture-access',403)
        result=self.q.run('a@example.com',True)
        self.assertTrue(result['paused']);self.assertIsNone(result['retry_at'])
        self.q=self.new_query();self.q.run('a@example.com',True)
        self.assertEqual(self.client.get.call_count,1)
        self.assertFalse(self.q.ready('a@example.com',True))
        self.assertTrue(self.q.resume('a@example.com'))
        self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)
        self.assertNotIn('secret',result['err'])

    def test_changed_credential_unblocks_persistent_401_and_403(self):
        for code in ('reauth_required',403):
            with self.subTest(code=code):
                self.saved['tokens']['access_token']='fixture-'+str(code);self.write()
                self.client.get.reset_mock();self.client.get.side_effect=RPCError('blocked',code)
                self.q.run('a@example.com',True);self.q=self.new_query()
                self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,1)
                self.saved['tokens']['access_token']+='-changed';self.write()
                self.assertTrue(self.q.ready('a@example.com',True))
                self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)

    def test_pause_survives_current_to_encrypted_snapshot_and_reencryption(self):
        self.client.get.side_effect=RPCError('forbidden',403)
        self.q.run('a@example.com',True)
        snapshot=self.paths.snapshot('a@example.com')
        for index in range(2):
            # Platform DPAPI is verified by credential-store tests; inject a
            # different envelope each time to isolate stable query identity.
            def fixture_crypto(value, decrypt=False):
                return value[1:] if decrypt else bytes([index])+value
            with patch('nx.credentials._dpapi',side_effect=fixture_crypto):
                atomic_bytes(snapshot,encode_credential_bytes(json.dumps(self.saved,indent=4,sort_keys=True).encode()))
                self.q=self.new_query()
                self.assertFalse(self.q.ready('a@example.com',False))
                result=self.q.run('a@example.com',False)
                self.assertTrue(result['paused']);self.assertEqual(result['error_code'],403)
        self.assertEqual(self.client.get.call_count,1)

    def test_missing_or_invalid_credentials_are_not_background_ready(self):
        self.assertFalse(self.q.ready('missing@example.com'))
        self.saved['tokens']['access_token']='';self.write()
        self.assertEqual(self.q.status('a@example.com',True)['error_code'],'reauth_required')
        self.assertFalse(self.q.ready('a@example.com',True))
        atomic_bytes(self.paths.auth,b'{"tokens": []}')
        self.assertFalse(self.q.ready('a@example.com',True))
        atomic_bytes(self.paths.auth,b'not-json')
        self.assertFalse(self.q.ready('a@example.com',True))

    def test_status_cache_keeps_only_digest_and_code_and_invalidates(self):
        self.assertTrue(self.q.ready('a@example.com',True))
        with patch('nx.quota_http.read_credential_bytes',side_effect=AssertionError('cached')):
            self.assertTrue(self.q.ready('a@example.com',True))
        self.saved['tokens']['access_token']='';self.write()
        self.assertFalse(self.q.ready('a@example.com',True))
        self.assertNotIn('fixture-access',repr(self.q._status_cache))

    def test_manual_resume_never_bypasses_401_or_429_retry_after(self):
        self.client.get.side_effect=RPCError('expired','reauth_required')
        self.q.run('a@example.com',True)
        self.assertFalse(self.q.resume('a@example.com'))
        self.saved['tokens']['access_token']='changed-fixture';self.write()
        failure=RPCError('limited',429);failure.diagnostics={'retry_after_at':self.now+7200,'http_status':429}
        self.client.get.side_effect=failure
        result=self.q.run('a@example.com',True)
        self.assertEqual(result['retry_at'],self.now+7200)
        self.assertFalse(self.q.resume('a@example.com'))
        self.q=self.new_query();self.now+=7199
        self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)
        self.now+=1;self.assertTrue(self.q.ready('a@example.com',True))

    def test_network_failures_on_two_accounts_pause_batch_and_allow_one_probe(self):
        for email in ('b@example.com','c@example.com'):
            saved=json.loads(auth(email));saved['tokens']['access_token']='synthetic-test-only'
            atomic_bytes(self.paths.snapshot(email),json.dumps(saved).encode())
        self.client.get.side_effect=RPCError('private-host','network')
        self.q.run('a@example.com',True);self.q.run('b@example.com',False)
        self.q=self.new_query()
        self.assertFalse(self.q.ready('c@example.com'))
        self.q.run('c@example.com',False);self.assertEqual(self.client.get.call_count,2)
        self.assertTrue(self.q.resume('c@example.com'))
        self.assertTrue(self.q.ready('c@example.com'))
        self.q.run('c@example.com',False);self.assertEqual(self.client.get.call_count,3)
        self.q.run('c@example.com',False);self.assertEqual(self.client.get.call_count,3)
        self.assertFalse(self.q.ready('a@example.com',True))

    def test_successful_manual_network_probe_can_finish_optional_endpoint(self):
        for email in ('b@example.com','c@example.com'):
            saved=json.loads(auth(email));saved['tokens']['access_token']='synthetic-test-only'
            atomic_bytes(self.paths.snapshot(email),json.dumps(saved).encode())
        self.client.get.side_effect=RPCError('network','network')
        self.q.run('a@example.com',True);self.q.run('b@example.com',False)
        self.assertTrue(self.q.resume('c@example.com'))
        primary={**response(),'account_id':'fixture-c@example.com','email':'c@example.com'}
        self.client.get.side_effect=lambda endpoint,*args: primary if endpoint=='/wham/usage' else {'available_count':2,'credits':[]}
        result=self.q.run('c@example.com',False)
        self.assertTrue(result['ok']);self.assertNotIn('query_warning',result)
        self.assertEqual(result['banked_resets']['items'],[])
        self.assertTrue(self.q.ready('c@example.com',False))

    def test_query_policy_file_contains_only_hashes_and_safe_metadata(self):
        failure=RPCError('fixture-access a@example.com C:/private/path',403)
        failure.diagnostics={'http_status':403,'request_id':'req_fixture_123','server_error_code':'permission_denied',
                             'response':'fixture-access','path':'C:/private/path'}
        self.client.get.side_effect=failure
        self.q.run('a@example.com',True)
        content=(self.paths.data/'query-policy.json').read_text()
        for secret in ('fixture-access','a@example.com','C:/private/path','response'):
            self.assertNotIn(secret,content)
        self.assertEqual(self.q.status('a@example.com',True)['request_id'],'req_fixture_123')

    def test_corrupt_policy_fails_closed_without_network(self):
        atomic_bytes(self.paths.data/'query-policy.json',b'not-json')
        self.assertFalse(self.q.ready('a@example.com',True))
        result=self.q.run('a@example.com',True)
        self.assertEqual(result['error_code'],'query_policy_unavailable');self.assertTrue(result['paused'])
        self.client.get.assert_not_called()

    def test_oversized_numeric_policy_fields_do_not_crash_status_or_run(self):
        credential=credential_fingerprint(self.paths.auth.read_bytes())
        for value in (10**400,-10**400,float('nan'),float('inf'),[],{}):
            with self.subTest(value_type=type(value).__name__):
                record={'credential':credential,'error_code':403,'paused':True,
                        'attempts':value,'retry_at':value,'updated_at':value,'phase':[]}
                document={'version':1,'accounts':{account_key('a@example.com'):record},
                          'network':{'attempts':value,'retry_at':value,'recent':{account_key('a@example.com'):value}}}
                atomic_bytes(self.paths.data/'query-policy.json',json.dumps(document).encode())
                self.q=self.new_query()
                self.assertFalse(self.q.ready('a@example.com',True))
                self.assertEqual(self.q.run('a@example.com',True)['error_code'],403)
        self.client.get.assert_not_called()

    def test_policy_write_failure_stays_paused_for_running_query(self):
        self.client.get.side_effect=RPCError('network','network')
        with patch('nx.query_policy.atomic_bytes',side_effect=PermissionError('C:/secret')):
            result=self.q.run('a@example.com',True)
        self.assertEqual(result['error_code'],'query_policy_unavailable')
        self.assertFalse(self.q.ready('a@example.com',True))
        self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,1)

    def test_backoff_is_bounded_and_success_resets_it(self):
        self.client.get.side_effect=RPCError('network','network')
        for attempt in range(9):
            result=self.q.run('a@example.com',True)
            expected=min(60*2**attempt,900)
            self.assertEqual(result['retry_at']-self.now,expected)
            self.now+=expected
        self.client.get.side_effect=lambda endpoint,*args: response() if endpoint=='/wham/usage' else {'available_count':2,'credits':[]}
        self.assertTrue(self.q.run('a@example.com',True)['ok'])
        self.client.get.side_effect=RPCError('network','network')
        self.assertEqual(self.q.run('a@example.com',True)['retry_at']-self.now,60)

    def test_identity_mismatch_stops_before_secondary_endpoints(self):
        self.client.get.side_effect=None;self.client.get.return_value={**response(),'account_id':'other'}
        self.assertEqual(self.q.run('a@example.com',True,usage=True)['error_code'],'identity_mismatch')
        self.assertEqual(self.client.get.call_count,1)

    def test_changed_credentials_discard_response(self):
        def change(*args):
            self.saved['tokens']['access_token']='new-fixture-access';self.write();return response()
        self.client.get.side_effect=change
        self.assertEqual(self.q.run('a@example.com',True)['error_code'],'identity_mismatch')

    def test_cancel_before_query_does_no_network(self):
        cancel=threading.Event();cancel.set()
        self.assertEqual(self.q.run('a@example.com',True,cancel=cancel)['error_code'],'cancelled')
        self.client.get.assert_not_called()

    def test_query_wait_uses_configured_budget_and_subtracts_primary_elapsed_time(self):
        with patch('nx.quota_http.time.monotonic',side_effect=[100,100,110]):
            self.assertTrue(self.q.run('a@example.com',True)['ok'])
        self.assertEqual([c.args[3] for c in self.client.get.call_args_list],[45,35])

    def test_optional_reset_failure_preserves_available_count(self):
        self.client.get.side_effect=[response(),RPCError('not available',403)]
        result=self.q.run('a@example.com',True)
        self.assertTrue(result['ok']);self.assertEqual(result['banked_resets']['available_count'],2)
        self.assertIsNone(result['banked_resets']['items'])
        self.assertTrue(result['query_warning']['paused'])
        self.assertEqual(result['query_warning']['phase'],'reset_credits')
        self.assertEqual(result['query_warning']['scope'],'reset_credits')
        self.assertFalse(result['paused'])
        self.assertTrue(self.q.ready('a@example.com',True))

    def test_optional_403_skips_only_reset_endpoint_across_queries_and_restart(self):
        self.client.get.side_effect=[response(),RPCError('not available',403)]
        self.assertTrue(self.q.run('a@example.com',True)['ok'])
        self.client.get.side_effect=lambda endpoint,*args: response() if endpoint=='/wham/usage' else self.fail('optional endpoint retried')
        for recreate in (False,True):
            if recreate:self.q=self.new_query()
            result=self.q.run('a@example.com',True)
            self.assertTrue(result['ok']);self.assertFalse(result['paused'])
            self.assertEqual(result['query_warning']['scope'],'reset_credits')
            self.assertEqual(result['banked_resets']['available_count'],2)
            self.assertTrue(self.q.ready('a@example.com',True))
        self.assertEqual([call.args[0] for call in self.client.get.call_args_list].count('/wham/rate-limit-reset-credits'),1)
        self.assertEqual(self.client.get.call_count,4)
        self.assertTrue(self.q.resume('a@example.com'))
        self.client.get.side_effect=[response(),{'available_count':3,'credits':[]}]
        result=self.q.run('a@example.com',True)
        self.assertEqual(result['banked_resets']['available_count'],3)
        self.assertNotIn('query_warning',result)

    def test_optional_transient_failures_defer_only_the_optional_endpoint(self):
        for code in (429,'network','timeout',503):
            with self.subTest(code=code):
                self.now+=10000
                self.saved['tokens']['access_token']='optional-fixture-'+str(code);self.write()
                self.client.get.reset_mock();self.client.get.side_effect=[response(),RPCError('temporary',code)]
                result=self.q.run('a@example.com',True)
                self.assertTrue(result['ok'])
                self.assertEqual(result['query_warning']['scope'],'reset_credits')
                self.assertFalse(result['paused'])
                self.assertTrue(self.q.ready('a@example.com',True))
                self.assertTrue(self.q.policy.status('unaffected@example.com','f'*64)['ready'])
                self.client.get.side_effect=lambda endpoint,*args: response() if endpoint=='/wham/usage' else self.fail('optional endpoint retried during cooldown')
                self.assertTrue(self.q.run('a@example.com',True)['ok'])
                self.assertEqual(self.client.get.call_count,3)
                self.assertFalse(self.q.policy._read()['network'].get('retry_at'))

    def test_primary_failure_still_blocks_query_and_retains_transport_evidence(self):
        error=RPCError('private host and token','timeout')
        error.diagnostics={'transport_error':'timeout','timeout_ms':45000,'elapsed_ms':45001}
        self.q.log=Mock();self.client.get.side_effect=error
        result=self.q.run('a@example.com',True)
        self.assertFalse(result['ok']);self.assertFalse(self.q.ready('a@example.com',True))
        self.assertEqual(result['transport_error'],'timeout')
        self.assertEqual(self.new_query().status('a@example.com',True)['timeout_ms'],45000)
        self.assertNotIn('private',str(self.q.log.warning.call_args))

    def test_reset_401_is_not_hidden_by_successful_quota(self):
        self.client.get.side_effect=[response(),RPCError('invalid','reauth_required')]
        self.assertEqual(self.q.run('a@example.com',True)['error_code'],'reauth_required')

    def test_real_profile_schema_maps_daily_activity(self):
        self.client.get.side_effect=[response(),{'stats':{'lifetime_tokens':42,'current_streak_days':3,
            'daily_usage_buckets':[{'start_date':'2026-09-27','tokens':42}]},'metadata':{'stats_error':None}}]
        result=self.q.run('a@example.com',True,usage=True)
        self.assertTrue(result['ok']);self.assertEqual(result['summary']['lifetimeTokens'],42)
        self.assertEqual(result['dailyUsageBuckets'],[{'startDate':'2026-09-27','tokens':42}])

    def test_incomplete_window_not_reported_as_zero(self):
        raw=response();del raw['rate_limit']['primary_window']['reset_at']
        self.client.get.side_effect=[raw,{}]
        self.assertEqual(self.q.run('a@example.com',True)['error_code'],'schema')

    def test_reset_iso_dates_preserved(self):
        payload=reset_payload({'available_count':1,'credits':[{'granted_at':'2026-09-27T00:00:00Z','expires_at':None}]})
        self.assertIsInstance(payload['credits'][0]['grantedAt'],int)
        self.assertIsNone(payload['credits'][0]['expiresAt'])


class HTTPTransportTests(unittest.TestCase):
    def test_cancellation_returns_promptly_and_discards_inflight_readonly_response(self):
        client=HTTPClient();cancel=threading.Event();entered=threading.Event();release=threading.Event();ended=threading.Event();result={}
        def blocked(*args):
            entered.set();release.wait(2);ended.set();return {'ok':True}
        def call():
            try:result['value']=client.get('/wham/usage','fixture','account',45,cancel)
            except RPCError as e:result['error']=e.code
        with patch.object(client,'_get',side_effect=blocked):
            caller=threading.Thread(target=call);caller.start()
            self.assertTrue(entered.wait(1));start=time.monotonic();cancel.set();caller.join(1)
            try:
                self.assertFalse(caller.is_alive());self.assertLess(time.monotonic()-start,1)
                self.assertEqual(result,{'error':'cancelled'})
            finally:release.set();ended.wait(1);caller.join(2)

    def test_cancelled_waiting_query_does_not_start_a_third_network_request(self):
        client=HTTPClient();release=threading.Event();both=threading.Event();lock=threading.Lock();calls=[];results=[]
        def blocked(*args):
            with lock:
                calls.append(args)
                if len(calls)==2:both.set()
            release.wait(2);return {}
        def call(cancel=None):
            try:client.get('/wham/usage','fixture','account',5,cancel)
            except RPCError as error:results.append(error.code)
        with patch.object(client,'_get',side_effect=blocked):
            threads=[threading.Thread(target=call) for _ in range(2)]
            for thread in threads:thread.start()
            self.assertTrue(both.wait(1))
            cancel=threading.Event();third=threading.Thread(target=call,args=(cancel,));third.start();cancel.set();third.join(1)
            try:
                self.assertFalse(third.is_alive());self.assertEqual(len(calls),2)
                self.assertEqual(results,['cancelled'])
            finally:
                release.set()
                for thread in threads:thread.join(2)

    def test_deadline_returns_timeout_without_waiting_for_blocked_response(self):
        client=HTTPClient();release=threading.Event()
        with patch.object(client,'_get',side_effect=lambda *a:(release.wait(1),{})[1]):
            try:
                with self.assertRaises(RPCError) as caught:client.get('/wham/usage','fixture','account',.05)
                self.assertEqual(caught.exception.code,'timeout')
                self.assertEqual(caught.exception.diagnostics['transport_error'],'timeout')
            finally:release.set()

    def test_transport_diagnostics_distinguish_timeout_dns_and_certificate_without_private_text(self):
        cases=((TimeoutError('fixture secret'),'timeout','timeout'),
               (socket.gaierror('fixture secret'),'network','dns'),
               (ssl.SSLCertVerificationError('fixture secret'),'network','tls_certificate'))
        for reason,code,category in cases:
            with self.subTest(category=category),patch('urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect=urllib.error.URLError(reason)
                with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
                self.assertEqual(caught.exception.code,code)
                self.assertEqual(caught.exception.diagnostics['transport_error'],category)
                self.assertNotIn('secret',json.dumps(caught.exception.diagnostics))

    def test_errors_are_sanitized_and_not_retried(self):
        for status,expected in ((401,'reauth_required'),(403,403),(429,429),(500,500)):
            with self.subTest(status=status),patch('urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',status,'secret',{},io.BytesIO(b'secret'))
                with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
                self.assertEqual(caught.exception.code,expected);self.assertNotIn('secret',str(caught.exception))
                factory.return_value.open.assert_called_once()

    def test_http_error_retains_only_bounded_allowlisted_diagnostics(self):
        stream=io.BytesIO(json.dumps({'error':{'code':'account_deactivated','message':'private@email.com fixture-token'}}).encode())
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',403,'secret',
                {'x-request-id':'req_fixture_123','Retry-After':'120'},stream)
            with self.assertRaises(RPCError) as caught:
                HTTPClient(clock=lambda:1800000000).get('/wham/usage','fixture','account',1)
        self.assertTrue(stream.closed)
        details=caught.exception.diagnostics
        self.assertEqual(details['http_status'],403)
        self.assertEqual(details['request_id'],'req_fixture_123')
        self.assertEqual(details['server_error_code'],'account_deactivated')
        self.assertEqual(details['retry_after_at'],1800000120)
        self.assertNotIn('fixture-token',json.dumps(details))

    def test_http_error_drops_unknown_codes_and_unsafe_request_ids(self):
        for request in ('private@email.com','req_a\r\nAuthorization: secret','req_'+'x'*120,'token.value'):
            with self.subTest(request=request),patch('urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',429,'secret',
                    {'x-request-id':request},io.BytesIO(b'{"error":{"code":"private@email.com"}}'))
                with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
                self.assertIsNone(caught.exception.diagnostics['request_id'])
                self.assertIsNone(caught.exception.diagnostics['server_error_code'])

    def test_error_response_read_is_bounded(self):
        stream=Mock();stream.read.return_value=b'x'*(ERROR_BYTES+1)
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',500,'secret',{},stream)
            with self.assertRaises(RPCError):HTTPClient().get('/wham/usage','fixture','account',1)
        stream.read.assert_called_once_with(ERROR_BYTES+1)
        stream.close.assert_called_once()

    def test_retry_after_accepts_http_date_and_rejects_bad_values(self):
        self.assertEqual(retry_after('Wed, 21 Oct 2015 07:28:00 GMT',1445412420),1445412480)
        for value in ('-1','nan','inf','private@email.com','9'*129,None):
            self.assertIsNone(retry_after(value,1800000000))

    def test_diagnostics_accept_malformed_nested_values_without_throwing(self):
        for value in ([],{},None,42,True):
            with self.subTest(value=value):
                result=safe_fields({'phase':value,'request_id':value,'server_error_code':value,'http_status':value})
                self.assertEqual(result['phase'],'policy')
                self.assertIsNone(result['request_id']);self.assertIsNone(result['server_error_code'])

    def test_redirect_refused(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid'))

    def test_unlisted_endpoint_refused_before_network(self):
        with patch('urllib.request.build_opener') as factory:
            with self.assertRaises(RPCError):HTTPClient().get('/oauth/token','fixture','account',1)
            factory.assert_not_called()

    def test_oversized_response_rejected(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.return_value=b' '*(MAX_BYTES+1)
            with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
            self.assertEqual(caught.exception.code,'response_too_large')

    def test_network_error_does_not_expose_request(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=urllib.error.URLError('secret')
            with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
            self.assertEqual(caught.exception.code,'network');self.assertNotIn('secret',str(caught.exception))

    def test_incomplete_http_response_is_a_network_failure(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value.__enter__.return_value.read.side_effect=\
                http.client.IncompleteRead(b'secret-partial-body')
            with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
            self.assertEqual(caught.exception.code,'network');self.assertNotIn('secret',str(caught.exception))
