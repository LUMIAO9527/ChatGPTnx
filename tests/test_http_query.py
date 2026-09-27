"""Credential ownership, bounded HTTP errors and real wire schema regression."""
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nx.quota import Query, RPCError
from nx.quota_http import HTTPClient, NoRedirect, MAX_BYTES, reset_payload
from nx.storage import Paths, atomic_bytes
from test_core import auth


def response():
    return {'account_id':'fixture-a@example.com','email':'a@example.com','plan_type':'plus',
            'rate_limit':{'primary_window':{'used_percent':25,'limit_window_seconds':18000,'reset_at':1900000000},
                          'secondary_window':None},
            'credits':{'has_credits':True,'unlimited':False,'balance':'1.25'},
            'rate_limit_reset_credits':{'available_count':2}}


class HTTPQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=Paths(Path(self.temp.name),Path(self.temp.name)/'home')
        self.saved=json.loads(auth('a@example.com'));self.saved['tokens']['access_token']='fixture-access'
        self.write()
        self.client=Mock()
        self.client.get.side_effect=lambda endpoint,*args: response() if endpoint=='/wham/usage' else {'available_count':2,'credits':[]}
        self.q=Query(self.paths,lambda:{'query_timeout':45},client=self.client)

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

    def test_service_errors_do_not_block_future_queries_or_refresh_login(self):
        for code in (403,429,500,'network'):
            with self.subTest(code=code):
                self.client.get.reset_mock();self.client.get.side_effect=RPCError('temporary',code)
                self.assertEqual(self.q.run('a@example.com',True)['error_code'],code)
                self.q.run('a@example.com',True);self.assertEqual(self.client.get.call_count,2)
                self.assertTrue(all(c.args[0]=='/wham/usage' for c in self.client.get.call_args_list))

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

    def test_each_network_wait_is_bounded_for_switch_cancellation(self):
        self.q.run('a@example.com',True)
        self.assertTrue(all(0<c.args[3]<=5 for c in self.client.get.call_args_list))

    def test_optional_reset_failure_preserves_available_count(self):
        self.client.get.side_effect=[response(),RPCError('not available',403)]
        result=self.q.run('a@example.com',True)
        self.assertTrue(result['ok']);self.assertEqual(result['banked_resets']['available_count'],2)
        self.assertIsNone(result['banked_resets']['items'])

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
    def test_errors_are_sanitized_and_not_retried(self):
        for status,expected in ((401,'reauth_required'),(403,403),(429,429),(500,500)):
            with self.subTest(status=status),patch('urllib.request.build_opener') as factory:
                factory.return_value.open.side_effect=urllib.error.HTTPError('https://example.invalid',status,'secret',{},io.BytesIO(b'secret'))
                with self.assertRaises(RPCError) as caught:HTTPClient().get('/wham/usage','fixture','account',1)
                self.assertEqual(caught.exception.code,expected);self.assertNotIn('secret',str(caught.exception))
                factory.return_value.open.assert_called_once()

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
