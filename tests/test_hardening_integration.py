"""Isolated service/bridge behavior; no real login, network or desktop actions."""
import json
import time
import unittest
from unittest.mock import Mock, patch
import test_core as fixtures
from nx.desktop import Bridge, Desktop
from nx.quota import Query


class HardeningIntegrationTests(unittest.TestCase):
    setUp = fixtures.Fixture.setUp
    tearDown = fixtures.Fixture.tearDown
    runner = fixtures.Fixture.runner
    wait = fixtures.Fixture.wait
    refresh = fixtures.Fixture.refresh

    def test_paused_queries_are_not_background_operations_or_candidates(self):
        self.refresh()
        real = Query(self.paths, lambda: self.service.state.get('settings'))
        self.service.query = real
        with patch.object(real, 'ready', return_value=False), patch.object(real, 'status',
                return_value={'ready': False, 'paused': True, 'error_code': 403}), \
                patch.object(real, 'run') as network:
            self.assertEqual(self.service.refresh(background=True)['reason'], 'query_paused')
            data = self.service.get_data()
            self.assertIsNone(data['auto_relay_email'])
            self.assertTrue(all(not a['ok'] for a in data['accounts']))
            self.assertFalse(self.service.refresh_stale_relay_accounts(data))
            network.assert_not_called()

    def test_optional_denial_cannot_pass_switch_precheck(self):
        original = self.query.run
        def warned(*args, **kwargs):
            return {**original(*args, **kwargs), 'query_warning': {'paused': True, 'error_code': 403}}
        self.query.run = warned
        with patch.object(self.service, 'runner') as switch:
            self.assertTrue(self.service._switch('b@example.com', 'relay')['accepted'])
            self.wait()
            switch.assert_not_called()
            self.assertFalse(self.service.last_result['ok'])

    def test_diagnostic_bridge_excludes_identifying_state(self):
        self.refresh()
        text = Bridge(self.service, None).get_diagnostics()['text']
        for private in ('example.com', 'synthetic-test-only', str(self.paths.root), 'auth.json'):
            self.assertNotIn(private, text)
        self.assertEqual(len(json.loads(text)['accounts']), 2)

    def test_optional_reset_denial_does_not_block_switch(self):
        original = self.query.run
        def warned(*args, **kwargs):
            return {**original(*args, **kwargs), 'query_warning': {
                'scope': 'reset_credits', 'paused': True, 'error_code': 403}}
        self.query.run = warned
        with patch.object(self.service, 'runner', wraps=self.runner) as switch:
            self.assertTrue(self.service._switch('b@example.com', 'relay')['accepted'])
            self.wait()
            switch.assert_called()
            self.assertTrue(self.service.last_result['ok'])

    def test_permission_pause_arriving_after_read_still_prevents_switch(self):
        self.refresh()
        target = self.query.run('b@example.com', False)
        real = Query(self.paths, lambda: self.service.state.get('settings'))
        self.service.query = real
        with patch.object(real, 'run', return_value=target), patch.object(real, 'ready', return_value=False), \
                patch.object(real, 'status', return_value={'ready':False,'paused':True,'error_code':403}), \
                patch.object(self.service, 'runner') as switch:
            self.service._switch('b@example.com', 'relay'); self.wait()
            switch.assert_not_called()
            self.assertFalse(self.service.last_result['ok'])

    def test_known_quota_survives_shared_rate_limit_without_new_request(self):
        self.refresh()
        real = Query(self.paths, lambda: self.service.state.get('settings'))
        self.service.query = real
        failure = {'email':'b@example.com','ok':False,'error_code':429,'paused':False,'retry_at':time.time()+600}
        with patch.object(real, 'run', return_value=failure), patch.object(real, 'ready', return_value=False), \
                patch.object(real, 'status', return_value={'ready':False,'paused':False,'error_code':429}), \
                patch.object(self.service, 'runner', wraps=self.runner) as switch:
            self.service._switch('b@example.com', 'relay'); self.wait()
            switch.assert_called_once()
            self.assertTrue(self.service.last_result['ok'])

    def test_auth_and_permission_notifications_have_distinct_recovery(self):
        host = Mock(); host.noticed = set()
        base = {'updated': time.time(), 'accounts': [
            {'email': 'a@example.com', 'error_code': 'reauth_required'},
            {'email': 'b@example.com', 'error_code': 403}]}
        Desktop._notify_stale_credentials(host, base)
        messages = [c.args[0] for c in host.icon.notify.call_args_list]
        self.assertIn('重新登录', messages[0])
        self.assertIn('恢复查询', messages[1])
        self.assertNotIn('凭据已失效', messages[1])


if __name__ == '__main__':
    unittest.main()
