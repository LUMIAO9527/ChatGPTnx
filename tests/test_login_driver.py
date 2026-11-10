"""State-machine checks for nx.login_driver with a scripted window reader.

No PowerShell and no ChatGPT window is involved: the helper call is injected, so
these run anywhere. What is under test is the decision - which field gets typed,
and above all when the driver refuses to type anything.
"""
import unittest
from dataclasses import dataclass
from pathlib import Path

from nx import login_driver

KEY = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
SCRIPT = Path('login_fill.ps1')


@dataclass
class Entry:
    email: str = 'a@b.com'
    password: str = 'secret-value'
    secret: str = KEY


class FakeWindow:
    """Reports a fixed page and records every payload that reaches the helper."""

    def __init__(self, step='email', hint='none', ok=True, error=None):
        self.step, self.hint = step, hint
        self.ok, self.error = ok, error
        self.calls = []
        self.on_fill = None

    def __call__(self, script, stage, payload):
        self.calls.append((stage, dict(payload)))
        if stage == 'probe':
            return {'ok': True, 'step': self.step, 'hint': self.hint}
        if self.on_fill:
            self.on_fill(stage)
        if self.ok:
            return {'ok': True, 'step': stage, 'hint': self.hint, 'clicked': True}
        return {'ok': False, 'step': stage, 'hint': self.hint,
                'error': self.error or 'no_input'}

    def typed(self):
        return [stage for stage, _ in self.calls if stage != 'probe']


class AdvanceTests(unittest.TestCase):
    def test_walks_the_three_fields_in_order(self):
        window = FakeWindow(step='email')
        state = {}
        first = login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=window)
        self.assertEqual(first['action'], 'filled')
        self.assertEqual(first['step'], 'email')

        window.step = 'password'
        second = login_driver.advance(SCRIPT, Entry(), state, now=1002, runner=window)
        self.assertEqual(second['action'], 'filled')
        self.assertEqual(second['step'], 'password')

        window.step, window.hint = 'otp', 'authenticator'
        third = login_driver.advance(SCRIPT, Entry(), state, now=1004, runner=window)
        self.assertEqual(third['action'], 'filled')
        self.assertEqual(third['step'], 'otp')
        self.assertEqual(window.typed(), ['email', 'password', 'otp'])

    def test_never_types_the_same_field_twice(self):
        window = FakeWindow(step='email')
        state = {}
        login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=window)
        again = login_driver.advance(SCRIPT, Entry(), state, now=1002, runner=window)
        self.assertEqual(again['action'], 'wait')
        self.assertEqual(again['reason'], 'already_filled')
        self.assertEqual(window.typed(), ['email'])

    def test_only_the_stage_value_reaches_the_helper(self):
        window = FakeWindow(step='password')
        login_driver.advance(SCRIPT, Entry(), {}, now=1000, runner=window)
        stage, payload = window.calls[-1]
        self.assertEqual(stage, 'password')
        self.assertEqual(payload, {'password': 'secret-value'})
        self.assertNotIn('email', payload)


class StopTests(unittest.TestCase):
    def test_email_code_stops_instead_of_spending_a_totp(self):
        window = FakeWindow(step='otp', hint='email_code')
        result = login_driver.advance(SCRIPT, Entry(), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'email_code')
        self.assertEqual(window.typed(), [], 'an e-mail code page must never be filled')

    def test_phone_challenge_stops_before_any_typing(self):
        # The phone page can carry an edit field; it must still not be typed into.
        window = FakeWindow(step='email', hint='phone')
        result = login_driver.advance(SCRIPT, Entry(), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'phone')

    def test_human_check_stops_on_an_unknown_page(self):
        window = FakeWindow(step='unknown', hint='human_check')
        result = login_driver.advance(SCRIPT, Entry(), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'human_check')

    def test_unclassifiable_page_times_out(self):
        window = FakeWindow(step='unknown', hint='none')
        state = {}
        first = login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=window)
        self.assertEqual(first['action'], 'wait')
        later = login_driver.advance(SCRIPT, Entry(), state, now=1029, runner=window)
        self.assertEqual(later['action'], 'wait')
        expired = login_driver.advance(SCRIPT, Entry(), state, now=1031, runner=window)
        self.assertEqual(expired['action'], 'stop')
        self.assertEqual(expired['reason'], 'timeout')
        self.assertEqual(window.typed(), [])

    def test_unknown_otp_page_is_not_guessed(self):
        window = FakeWindow(step='otp', hint='none')
        result = login_driver.advance(SCRIPT, Entry(), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'otp_unrecognized')

    def test_missing_password(self):
        window = FakeWindow(step='password')
        result = login_driver.advance(SCRIPT, Entry(password=''), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'no_password')
        self.assertEqual(window.typed(), [])

    def test_missing_secret(self):
        window = FakeWindow(step='otp', hint='authenticator')
        result = login_driver.advance(SCRIPT, Entry(secret=''), {}, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(result['reason'], 'no_secret')

    def test_stop_is_sticky(self):
        window = FakeWindow(step='email', hint='phone')
        state = {}
        login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=window)
        calls = len(window.calls)
        again = login_driver.advance(SCRIPT, Entry(), state, now=1002, runner=window)
        self.assertEqual(again['action'], 'stop')
        self.assertEqual(len(window.calls), calls, 'a stopped login must not keep probing')

    def test_retryable_error_is_retried_then_stops(self):
        window = FakeWindow(step='email', ok=False, error='no_input')
        state = {}
        outcomes = [login_driver.advance(SCRIPT, Entry(), state, now=moment, runner=window)
                    for moment in (1000, 1002, 1004)]
        self.assertEqual([item['action'] for item in outcomes],
                         ['wait', 'wait', 'stop'])
        self.assertEqual(state['attempts']['email'], login_driver.STAGE_ATTEMPTS)
        self.assertEqual(state['stop'], 'no_input')

    def test_decisive_error_stops_immediately(self):
        window = FakeWindow(step='password', ok=False, error='no_password')
        state = {}
        result = login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=window)
        self.assertEqual(result['action'], 'stop')
        self.assertEqual(window.typed(), ['password'], 'one attempt, no retry loop')


class CodeWindowTests(unittest.TestCase):
    def test_waits_instead_of_submitting_an_expiring_code(self):
        window = FakeWindow(step='otp', hint='authenticator')
        # 29 seconds past the window boundary leaves one second of validity.
        result = login_driver.advance(SCRIPT, Entry(), {}, now=29, runner=window)
        self.assertEqual(result['action'], 'wait')
        self.assertEqual(result['reason'], 'code_expiring')
        self.assertEqual(window.typed(), [])

    def test_fills_at_the_start_of_a_window(self):
        window = FakeWindow(step='otp', hint='authenticator')
        result = login_driver.advance(SCRIPT, Entry(), {}, now=30, runner=window)
        self.assertEqual(result['action'], 'filled')
        stage, payload = window.calls[-1]
        self.assertEqual(len(payload['code']), 6)
        self.assertTrue(payload['code'].isdigit())


class MappingTests(unittest.TestCase):
    def test_every_stop_reason_maps_to_a_vault_result(self):
        from nx.account_vault import RESULTS
        for reason in login_driver.STOP_REASONS:
            code, message = login_driver.describe(reason)
            self.assertIn(code, RESULTS, reason)
            self.assertTrue(message, reason)

    def test_unparsable_helper_output_is_retried_then_stops(self):
        def broken(script, stage, payload):
            raise login_driver.FillError('login_fill_unparsable')
        state = {}
        first = login_driver.advance(SCRIPT, Entry(), state, now=1000, runner=broken)
        self.assertEqual(first['action'], 'wait')
        self.assertTrue(first.get('retry'))
        login_driver.advance(SCRIPT, Entry(), state, now=1002, runner=broken)
        last = login_driver.advance(SCRIPT, Entry(), state, now=1004, runner=broken)
        self.assertEqual(last['action'], 'stop')
        self.assertEqual(last['reason'], 'login_fill_unparsable')
        self.assertEqual(last['result'], 'stopped')


if __name__ == '__main__':
    unittest.main()