"""Synthetic reset transactions only; no real credits, logins or HTTP calls."""
import json
import unittest
import uuid
from unittest.mock import Mock, patch

import test_core
from test_core import auth
from nx.credentials import read_credential_bytes
from nx.quota import RPCError
from nx.reset_credits import ResetClient, ResetCredits
from nx.storage import atomic_bytes


class ResetTests(unittest.TestCase):
    setUp = test_core.Fixture.setUp
    tearDown = test_core.Fixture.tearDown
    runner = test_core.Fixture.runner
    wait = test_core.Fixture.wait

    def engine(self):
        self.client = Mock()
        self.bank = {'available_count': 1, 'credits': [{
            'id': 'fixture-credit', 'status': 'available', 'reset_type': 'codex',
            'granted_at': 1800000000, 'expires_at': 1900000000}]}
        self.used = 95
        def get(endpoint, token, account_id, timeout):
            if endpoint == '/wham/rate-limit-reset-credits':
                return self.bank
            email = account_id.removeprefix('fixture-')
            return {'account_id': account_id, 'email': email, 'plan_type': 'plus',
                    'rate_limit': {'primary_window': {'used_percent': self.used,
                        'limit_window_seconds': 18000, 'reset_at': 1900000000}}}
        self.client.get.side_effect = get
        def consume(*args):
            self.bank = {'available_count': 0, 'credits': []}
            self.used = 0
            return 'reset'
        self.client.consume.side_effect = consume
        self.engine_instance = ResetCredits(self.paths, self.accounts.current,
            lambda: {'query_timeout': 45}, self.service._record_reset_limits,
            client=self.client)
        return self.engine_instance

    def test_confirmed_reset_uses_target_credential_and_refreshes_server_values(self):
        engine = self.engine()
        original = self.paths.auth.read_bytes()
        request_id = str(uuid.uuid4())
        with patch('subprocess.Popen', side_effect=AssertionError('reset must not restart desktop')):
            self.assertEqual(engine.consume('b@example.com', 'fixture-credit', request_id), 'reset')
        self.client.consume.assert_called_once_with('synthetic-test-only', 'fixture-b@example.com',
                                                     'fixture-credit', request_id, 45.0)
        self.assertEqual(self.paths.auth.read_bytes(), original)
        self.assertIsNone(engine.pending('b@example.com'))
        target = next(r for r in self.service.state.get('cache')['accounts'] if r['email'] == 'b@example.com')
        self.assertEqual(target['windows'][0]['used'], 0)
        self.assertEqual(target['banked_resets']['available_count'], 0)

    def test_repeating_a_completed_confirmation_does_not_consume_again(self):
        engine = self.engine()
        request_id = str(uuid.uuid4())
        engine.consume('a@example.com', 'fixture-credit', request_id)
        self.client.get.reset_mock()
        self.assertEqual(engine.consume('a@example.com', 'fixture-credit', request_id), 'reset')
        self.client.get.assert_not_called()
        self.assertEqual(self.client.consume.call_count, 1)

    def test_uncertain_retry_after_restart_reuses_the_original_request_id(self):
        engine = self.engine()
        request_id = str(uuid.uuid4())
        self.client.consume.side_effect = RPCError('connection lost', 'reset_uncertain')
        with self.assertRaises(RPCError):
            engine.consume('b@example.com', 'fixture-credit', request_id)
        self.assertEqual(engine.pending('b@example.com')['request_id'], request_id)
        self.bank = {'available_count': 0, 'credits': []}
        self.client.consume.side_effect = None
        self.client.consume.return_value = 'already_redeemed'
        restarted = ResetCredits(self.paths, self.accounts.current, lambda: {}, client=self.client)
        self.assertEqual(restarted.consume('b@example.com', 'fixture-credit', str(uuid.uuid4())), 'already_redeemed')
        self.assertEqual(self.client.consume.call_args.args[3], request_id)
        self.assertIsNone(restarted.pending('b@example.com'))

    def test_uncertain_attempt_cannot_be_replaced_with_another_credit(self):
        engine = self.engine()
        self.client.consume.side_effect = RPCError('lost', 'reset_uncertain')
        with self.assertRaises(RPCError):
            engine.consume('a@example.com', 'fixture-credit', str(uuid.uuid4()))
        with self.assertRaisesRegex(RPCError, '上一次'):
            engine.consume('a@example.com', 'another-credit', str(uuid.uuid4()))
        self.assertEqual(self.client.consume.call_count, 1)

    def test_follow_up_read_failure_cannot_turn_a_consumed_reset_into_failure(self):
        engine = self.engine()
        get = self.client.get.side_effect
        reads = []
        def limited(*args):
            reads.append(args)
            if len(reads) > 2:
                raise RPCError('network', 'network')
            return get(*args)
        self.client.get.side_effect = limited
        request_id = str(uuid.uuid4())
        self.assertEqual(engine.consume('a@example.com', 'fixture-credit', request_id), 'reset')
        self.assertIsNone(engine.pending('a@example.com'))
        self.assertEqual(engine.consume('a@example.com', 'fixture-credit', request_id), 'reset')
        self.assertEqual(self.client.consume.call_count, 1)

    def test_stale_or_consumed_credit_is_rejected_before_post(self):
        engine = self.engine()
        self.bank['credits'][0]['status'] = 'redeemed'
        with self.assertRaisesRegex(RPCError, '不可用'):
            engine.consume('a@example.com', 'fixture-credit', str(uuid.uuid4()))
        self.client.consume.assert_not_called()

    def test_local_and_remote_identity_mismatch_never_consume(self):
        engine = self.engine()
        path = self.paths.snapshot('b@example.com')
        before = read_credential_bytes(path)
        atomic_bytes(path, auth('other@example.com'))
        with self.assertRaises(RPCError):
            engine.consume('b@example.com', 'fixture-credit', str(uuid.uuid4()))
        self.client.get.assert_not_called()
        atomic_bytes(path, before)
        self.client.get.side_effect = lambda *args: {'account_id': 'wrong', 'email': 'other@example.com'}
        with self.assertRaises(RPCError):
            engine.consume('b@example.com', 'fixture-credit', str(uuid.uuid4()))
        self.client.consume.assert_not_called()

    def test_invalid_confirmation_and_corrupt_journal_do_not_send_or_overwrite(self):
        engine = self.engine()
        for credit, request_id in ((None, str(uuid.uuid4())), ('fixture-credit', 'bad')):
            with self.assertRaises(RPCError):
                engine.consume('a@example.com', credit, request_id)
        engine.path.write_bytes(b'{broken')
        self.assertIsNone(engine.pending('a@example.com'))
        with self.assertRaises(RPCError):
            engine.consume('a@example.com', 'fixture-credit', str(uuid.uuid4()))
        self.assertEqual(engine.path.read_bytes(), b'{broken')
        self.client.consume.assert_not_called()

    def test_no_credit_and_nothing_to_reset_are_terminal_without_fabricated_quota(self):
        engine = self.engine()
        self.client.consume.side_effect = None
        for outcome in ('no_credit', 'nothing_to_reset'):
            self.client.consume.return_value = outcome
            self.assertEqual(engine.consume('a@example.com', 'fixture-credit', str(uuid.uuid4())), outcome)
            self.assertIsNone(engine.pending('a@example.com'))
            target = self.service.state.get('cache')['accounts'][0]
            self.assertEqual(target['windows'][0]['used'], 95)

    def test_service_serializes_reset_and_keeps_current_login(self):
        self.service.resetter = self.engine()
        self.assertTrue(self.service.consume_reset('b@example.com', 'fixture-credit', str(uuid.uuid4()))['accepted'])
        self.wait()
        self.assertTrue(self.service.last_result['ok'])
        self.assertEqual(self.service.last_result['message'], '额度已重置')
        self.assertEqual(self.accounts.current(), 'a@example.com')


class ResetTransportTests(unittest.TestCase):
    def test_exact_post_endpoint_and_body_no_redirect_or_automatic_retry(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"code":"reset"}'
        opener = Mock()
        opener.open.return_value = response
        with patch('nx.reset_credits.urllib.request.build_opener', return_value=opener) as build:
            self.assertEqual(ResetClient().consume('fixture-token', 'fixture-account',
                                                  'fixture-credit', 'fixture-request', 45), 'reset')
        build.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.full_url, 'https://chatgpt.com/backend-api/wham/rate-limit-reset-credits/consume')
        self.assertEqual(json.loads(request.data), {'credit_id': 'fixture-credit', 'redeem_request_id': 'fixture-request'})

    def test_unknown_or_unreadable_reply_stays_uncertain_without_repeating(self):
        for body in (b'{}', b'{"code":"unknown"}', b'not json'):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = body
            opener = Mock()
            opener.open.return_value = response
            with patch('nx.reset_credits.urllib.request.build_opener', return_value=opener):
                with self.assertRaises(RPCError):
                    ResetClient().consume('fixture-token', 'fixture-account', 'credit', 'request', 45)
            opener.open.assert_called_once()


if __name__ == '__main__':
    unittest.main()
