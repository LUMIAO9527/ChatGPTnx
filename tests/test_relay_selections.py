"""Independent relay choices, verified switches and cancellations; offline only."""
import threading
import unittest
from unittest.mock import patch

import test_core
from nx.storage import atomic_bytes


class SelectionTests(unittest.TestCase):
    tearDown = test_core.Fixture.tearDown
    runner = test_core.Fixture.runner
    wait = test_core.Fixture.wait
    refresh = test_core.Fixture.refresh

    def setUp(self):
        test_core.Fixture.setUp(self)
        self.accounts.append('c@example.com')
        atomic_bytes(self.paths.snapshot('c@example.com'), test_core.auth('c@example.com'))
        self.refresh()

    def exhaust(self, email='c@example.com'):
        cache = self.service.state.get('cache')
        next(a for a in cache['accounts'] if a['email'] == email)['windows'][0]['used'] = 100
        self.service.state.update(cache=cache)

    def choices(self):
        data = self.service.get_data()
        return data['settings']['relay_pick'], (data['relay_wait'] or {}).get('email')

    def select_both(self):
        self.exhaust()
        self.service.set_relay_pick('b@example.com')
        self.service.set_relay_pick('c@example.com')
        self.assertEqual(self.choices(), ('b@example.com', 'c@example.com'))

    def test_setting_either_choice_preserves_the_other(self):
        self.select_both()
        self.service.set_relay_pick('b@example.com')
        self.assertEqual(self.choices(), ('b@example.com', 'c@example.com'))

    def test_targeted_cancellation_leaves_the_other_choice(self):
        self.select_both()
        self.service.cancel_relay_pick('b@example.com')
        self.assertEqual(self.choices(), (None, 'c@example.com'))
        self.service.set_relay_pick('b@example.com')
        self.service.cancel_relay_pick('c@example.com')
        self.assertEqual(self.choices(), ('b@example.com', None))

    def test_failed_manual_switch_preserves_both_choices(self):
        self.select_both()
        with patch.object(self.service, 'runner', side_effect=RuntimeError('fixture failure')):
            self.assertTrue(self.service.switch('b@example.com')['accepted'])
            self.wait()
        self.assertFalse(self.service.last_result['ok'])
        self.assertEqual(self.choices(), ('b@example.com', 'c@example.com'))
        self.assertEqual(self.accounts.current(), 'a@example.com')

    def test_choice_is_consumed_only_after_verified_switch(self):
        self.select_both()
        entered, release = threading.Event(), threading.Event()
        def delayed(*args):
            entered.set()
            release.wait(3)
            self.runner(*args)
        with patch.object(self.service, 'runner', side_effect=delayed):
            self.assertTrue(self.service.switch('b@example.com')['accepted'])
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.choices(), ('b@example.com', 'c@example.com'))
            finally:
                release.set()
            self.wait()
        self.assertEqual(self.choices(), (None, 'c@example.com'))
        self.assertEqual(self.service.state.get('relay_wait')['origin'], 'b@example.com')

    def test_recovery_consumes_its_choice_and_keeps_the_next_choice(self):
        self.select_both()
        self.refresh()
        with patch('nx.desktop.chatgpt_running', return_value=True):
            self.assertTrue(self.service.relay_when_recovered()['accepted'])
            self.wait()
        self.assertEqual(self.accounts.current(), 'c@example.com')
        self.assertEqual(self.choices(), ('b@example.com', None))

    def test_failed_recovery_keeps_both_choices(self):
        self.select_both()
        self.refresh()
        with patch('nx.desktop.chatgpt_running', return_value=True), \
             patch.object(self.service, 'runner', side_effect=RuntimeError('fixture failure')):
            self.assertTrue(self.service.relay_when_recovered()['accepted'])
            self.wait()
        self.assertFalse(self.service.last_result['ok'])
        self.assertEqual(self.choices(), ('b@example.com', 'c@example.com'))

    def test_external_change_to_another_current_account_keeps_recovery(self):
        self.exhaust()
        self.service.set_relay_pick('c@example.com')
        self.runner('-To', 'b@example.com')
        with patch('nx.desktop.chatgpt_running', return_value=True):
            self.assertEqual(self.service.relay_when_recovered()['reason'], 'waiting')
        self.assertEqual(self.choices(), (None, 'c@example.com'))
        self.assertEqual(self.service.state.get('relay_wait')['origin'], 'b@example.com')

    def test_archiving_one_selected_account_only_cancels_its_selection(self):
        self.select_both()
        self.assertTrue(self.service.remove('b@example.com')['accepted'])
        self.wait()
        self.assertEqual(self.choices(), (None, 'c@example.com'))


if __name__ == '__main__':
    unittest.main()
