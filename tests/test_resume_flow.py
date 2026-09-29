"""Durable continuation queue checks with synthetic task identifiers only."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.resume_flow import ResumeCoordinator
from nx.storage import Paths


class ResumeFlowTests(unittest.TestCase):
    THREAD = '67cc833f-6330-5bae-a638-9232b5ddfa21'
    OTHER = 'ea10a953-d3a4-53b9-b010-6361794c2a22'
    TURN = '42d1e863-8084-556e-a03c-d7c800c7055b'

    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '_wip' / 'temp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.paths = Paths(Path(self.temp.name), Path(self.temp.name) / 'codex')
        self.current = 'a@example.com'
        self.stop = threading.Event()
        self.coordinator = self.make_coordinator()

    def tearDown(self):
        self.stop.set()
        self.coordinator.wake.set()
        if self.coordinator.worker:
            self.coordinator.worker.join(timeout=3)
        self.temp.cleanup()

    def test_followup_auth_failure_is_recorded_without_resending(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'items': [
            {'thread_id': self.THREAD, 'turn_id': self.TURN,
             'observed_turn_id': self.OTHER, 'state': 'done',
             'reason': 'new_turn_observed', 'attempts': 1}]}]
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed',
                'error': {'message': 'workspace routing discovery unauthorized (401)'}}):
            self.assertIsNone(c._ready())
        item = c.sessions[0]['items'][0]
        self.assertEqual(item['reason'], 'resume_auth_failed')
        self.assertEqual(item['state'], 'failed')
        self.assertEqual(item['attempts'], 1)
        self.assertFalse(c.retry_task('observed', self.THREAD)['ok'])

    def test_followup_model_overload_requeues_from_the_failed_turn(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'target': self.current, 'items': [
            {'thread_id': self.THREAD, 'turn_id': self.TURN,
             'observed_turn_id': self.OTHER, 'state': 'done',
             'reason': 'new_turn_observed', 'attempts': 1}]}]
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed',
                'error': {'codexErrorInfo': 'serverOverloaded',
                          'message': 'Selected model is at capacity.'}}):
            self.assertIsNone(c._ready())
        item = c.sessions[0]['items'][0]
        self.assertEqual(item['reason'], 'resumed_turn_overloaded')
        self.assertEqual(item['state'], 'waiting')
        self.assertEqual(item['turn_id'], self.OTHER)
        self.assertNotIn('observed_turn_id', item)
        self.assertEqual(item['attempts'], 1)
        self.assertFalse(c.retry_task('observed', self.THREAD)['ok'])

    def test_immediate_network_failure_retries_from_the_new_turn_after_restart(self):
        c = self.coordinator
        ident = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        self.current = 'b@example.com'
        c.switched(ident)
        _, dispatched = c._ready()
        dispatched['observed_turn_id'] = self.OTHER
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'other', 'message': 'network error'}}
        with patch('nx.resume_flow.latest_turn', return_value=failed):
            c._persist_outcome(ident, dispatched, 'failed', 'resumed_turn_network')
        item = c.sessions[0]['items'][0]
        self.assertEqual((item['state'], item['turn_id'], item['attempts']),
                         ('waiting', self.OTHER, 1))
        self.assertIsNone(c._ready())
        replacement = self.make_coordinator()
        self.assertEqual(replacement.sessions[0]['items'][0]['turn_id'], self.OTHER)
        self.assertEqual(replacement.sessions[0]['items'][0]['state'], 'waiting')
        replacement.sessions[0]['items'][0]['next_try'] = 0
        self.assertEqual(replacement._ready()[1]['turn_id'], self.OTHER)

    def test_retry_stops_after_five_retries(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'done',
                                  'reason': 'new_turn_observed', 'attempts': 6}]}]
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        with patch('nx.resume_flow.latest_turn', return_value=failed):
            self.assertIsNone(c._ready())
        item = c.sessions[0]['items'][0]
        self.assertEqual((item['state'], item['reason']),
                         ('failed', 'resumed_turn_overloaded'))
        self.assertEqual(c.sessions[0]['phase'], 'failed')

    def test_new_quota_failure_does_not_repeat_on_the_same_account(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'done',
                                  'reason': 'new_turn_observed', 'attempts': 1}]}]
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'usageLimitExceeded'}}
        with patch('nx.resume_flow.latest_turn', return_value=failed):
            self.assertIsNone(c._ready())
        item = c.sessions[0]['items'][0]
        self.assertEqual((item['state'], item['reason']), ('failed', 'resumed_turn_limit'))

    def test_retry_does_not_follow_a_turn_the_user_has_already_superseded(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'done',
                                  'reason': 'new_turn_observed', 'attempts': 1}]}]
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        newer = {'turn_id': self.TURN, 'status': 'inProgress'}
        with patch('nx.resume_flow.latest_turn', side_effect=[failed, newer]):
            self.assertIsNone(c._ready())
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'failed')
        self.assertEqual(c.sessions[0]['items'][0]['turn_id'], self.TURN)

    def test_manual_retry_after_budget_checks_exact_latest_failed_turn(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'failed', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'failed',
                                  'reason': 'resumed_turn_overloaded', 'attempts': 6}]}]
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        with patch('nx.resume_flow.latest_turn', return_value=failed):
            self.assertTrue(c.retry_task('observed', self.THREAD)['ok'])
        item = c.sessions[0]['items'][0]
        self.assertEqual((item['state'], item['turn_id'], item['attempts']),
                         ('waiting', self.OTHER, 0))
        self.assertNotIn('observed_turn_id', item)
        self.assertEqual(c._ready()[1]['turn_id'], self.OTHER)

    def test_manual_retry_rejects_a_newer_user_turn(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'failed', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'failed',
                                  'reason': 'resumed_turn_overloaded', 'attempts': 6}]}]
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        newer = {'turn_id': self.TURN, 'status': 'inProgress'}
        with patch('nx.resume_flow.latest_turn', side_effect=[failed, newer]):
            self.assertFalse(c.retry_task('observed', self.THREAD)['ok'])
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'failed')

    def test_existing_generic_failure_is_explained_from_exact_observed_turn(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'failed', 'updated_at': time.time(),
                       'created_at': time.time(), 'items': [
            {'thread_id': self.THREAD, 'turn_id': self.TURN,
             'observed_turn_id': self.OTHER, 'state': 'failed',
             'reason': 'resumed_turn_failed', 'attempts': 1}]}]
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed',
                'error': {'codexErrorInfo': 'serverOverloaded'}}) as read, \
             patch('nx.resume_flow.title_prefixes', return_value={}):
            shown = c.details()
        read.assert_called_once_with(self.paths.home, self.THREAD, self.OTHER)
        self.assertEqual(shown[0]['items'][0]['reason'], 'resumed_turn_overloaded')
        self.assertEqual(c.sessions[0]['items'][0]['reason'], 'resumed_turn_failed')

    def test_existing_confirmed_overload_requeues_on_restart(self):
        c = self.coordinator
        c.sessions = [{'id': 'legacy', 'phase': 'failed', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'failed',
                                  'reason': 'resumed_turn_failed', 'attempts': 1}]}]
        c._save()
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        with patch('nx.resume_flow.latest_turn', return_value=failed):
            replacement = self.make_coordinator()
        item = replacement.sessions[0]['items'][0]
        self.assertEqual((replacement.sessions[0]['phase'], item['state'], item['turn_id']),
                         ('resuming', 'waiting', self.OTHER))
        self.assertGreater(item['next_try'], time.time())

    def test_existing_generic_failure_does_not_retry_when_newer_turn_exists(self):
        c = self.coordinator
        c.sessions = [{'id': 'legacy', 'phase': 'failed', 'target': self.current,
                       'updated_at': time.time(), 'created_at': time.time(),
                       'items': [{'thread_id': self.THREAD, 'turn_id': self.TURN,
                                  'observed_turn_id': self.OTHER, 'state': 'failed',
                                  'reason': 'resumed_turn_failed', 'attempts': 1}]}]
        c._save()
        failed = {'turn_id': self.OTHER, 'status': 'failed',
                  'error': {'codexErrorInfo': 'serverOverloaded'}}
        newer = {'turn_id': self.TURN, 'status': 'inProgress'}
        with patch('nx.resume_flow.latest_turn', side_effect=[failed, newer]):
            replacement = self.make_coordinator()
        self.assertEqual(replacement.sessions[0]['phase'], 'failed')
        self.assertEqual(replacement.sessions[0]['items'][0]['state'], 'failed')

    def test_followup_does_not_attribute_another_turn_failure(self):
        c = self.coordinator
        c.sessions = [{'id': 'observed', 'phase': 'done', 'items': [
            {'thread_id': self.THREAD, 'turn_id': self.TURN,
             'observed_turn_id': self.OTHER, 'state': 'done',
             'reason': 'new_turn_observed', 'attempts': 1}]}]
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.TURN, 'status': 'failed'}):
            self.assertIsNone(c._ready())
        self.assertEqual(c.sessions[0]['items'][0]['state'], 'done')

    def make_coordinator(self):
        return ResumeCoordinator(self.paths, lambda: self.current, self.stop,
                                 Mock(), Mock(), threading.Lock())

    def test_followup_failure_does_not_abandon_remaining_queue(self):
        c = self.coordinator
        ident = c.prepare('a@example.com', 'b@example.com', 'manual',
                          [self.event(was_active=True), self.event(self.OTHER, was_active=True)])
        self.current = 'b@example.com'
        c.switched(ident)
        session = c.sessions[-1]
        session['items'][0].update(state='done', reason='new_turn_observed',
                                   observed_turn_id=self.OTHER)
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed',
                'error': {'message': 'workspace routing discovery unauthorized (401)'}}):
            ready = c._ready()
        self.assertIsNotNone(ready)
        self.assertEqual(ready[1]['thread_id'], self.OTHER)
        self.assertEqual(session['phase'], 'resuming')
        self.assertEqual(session['items'][0]['state'], 'failed')
        self.assertEqual(session['items'][1]['state'], 'acting')

    def test_later_switch_does_not_duplicate_queued_pre_dispatch_retry(self):
        c = self.coordinator
        first = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        self.current = 'b@example.com'
        c.switched(first)
        _, item = c._ready()
        c._persist_outcome(first, item, 'failed', 'desktop_bridge_unavailable')
        second = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        c.switched(second)
        self.assertIsNone(c._ready())
        c.sessions[0]['items'][0]['next_try'] = 0
        ready = c._ready()
        self.assertIsNotNone(ready)
        self.assertEqual(ready[0], first)

    def test_later_switch_never_replays_uncertain_send(self):
        c = self.coordinator
        first = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        self.current = 'b@example.com'
        c.switched(first)
        _, item = c._ready()
        c._persist_outcome(first, item, 'failed', 'action_outcome_unknown')
        second = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        c.switched(second)
        self.assertIsNone(c._ready())
        self.assertEqual(c.sessions[-1]['items'][0]['reason'], 'duplicate_attempt')


    def test_observed_turn_is_saved_without_rereading_latest(self):
        c = self.coordinator
        ident = c.prepare('a@example.com', 'b@example.com', 'manual', [self.event()])
        self.current = 'b@example.com'
        c.switched(ident)
        _, item = c._ready()
        item['observed_turn_id'] = self.OTHER
        with patch('nx.resume_flow.latest_turn') as read:
            c._persist_outcome(ident, item, 'done', 'new_turn_observed')
        read.assert_not_called()
        replacement = self.make_coordinator()
        self.assertEqual(replacement.sessions[-1]['items'][0]['observed_turn_id'], self.OTHER)
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'completed'}) as read:
            self.assertIsNone(replacement._ready())
        read.assert_called_once_with(self.paths.home, self.THREAD, self.OTHER)
        self.assertEqual(replacement.sessions[-1]['items'][0]['reason'], 'resumed_turn_completed')

    def test_waiting_task_survives_restart_after_other_turn_fails(self):
        c = self.coordinator
        ident = c.prepare('a@example.com', 'b@example.com', 'manual',
                          [self.event(), self.event(self.OTHER)])
        self.current = 'b@example.com'
        c.switched(ident)
        session = c.sessions[-1]
        session['items'][0].update(state='done', reason='new_turn_observed',
                                   observed_turn_id=self.OTHER)
        session['items'][1]['next_try'] = time.time() + 60
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed', 'error': {}}):
            self.assertIsNone(c._ready())
        replacement = self.make_coordinator()
        self.assertEqual(replacement.sessions[-1]['phase'], 'resuming')
        replacement.sessions[-1]['items'][1]['next_try'] = 0
        ready = replacement._ready()
        self.assertEqual(ready[1]['thread_id'], self.OTHER)

    def test_followup_does_not_reopen_cancelled_session(self):
        c = self.coordinator
        ident = c.prepare('a@example.com', 'b@example.com', 'manual',
                          [self.event(), self.event(self.OTHER)])
        self.current = 'b@example.com'
        c.switched(ident)
        session = c.sessions[-1]
        session['items'][0].update(state='done', reason='new_turn_observed',
                                   observed_turn_id=self.OTHER)
        c.cancel_active()
        with patch('nx.resume_flow.latest_turn', return_value={
                'turn_id': self.OTHER, 'status': 'failed', 'error': {}}):
            self.assertIsNone(c._ready())
        self.assertEqual(session['phase'], 'cancelled')
        self.assertEqual(session['items'][1]['state'], 'skipped')

    def event(self, thread=None, **extra):
        return {'thread_id': thread or self.THREAD, 'turn_id': self.TURN, **extra}

    def test_legacy_composer_reason_cannot_queue_editor_recovery(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',[self.event()])
        self.current='b@example.com'; self.coordinator.switched(ident)
        session=self.coordinator.sessions[-1]; session['phase']='failed'; session['items'][0].update(state='failed',reason='composer_state_unknown')
        summary=self.coordinator.summary(); self.assertEqual(summary['attention'],0)
        self.assertFalse(self.coordinator.retry_task(ident,self.THREAD)['ok'])
        self.assertEqual(session['items'][0]['state'],'failed')

    def test_uncertain_effect_is_not_explicitly_retryable(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',[self.event()])
        self.current='b@example.com'; self.coordinator.switched(ident)
        session=self.coordinator.sessions[-1]; session['phase']='failed'; session['items'][0].update(state='failed',reason='action_outcome_unknown')
        self.assertFalse(self.coordinator.retry_task(ident,self.THREAD)['ok'])
        self.assertEqual(self.coordinator.summary()['attention'],0)

    def test_one_worker_processes_multiple_tasks_and_persists_result(self):
        first = self.event(was_active=True)
        second = self.event(self.OTHER, was_active=True, turn_id='66666666-6666-4666-8666-666666666666')
        ident = self.coordinator.prepare('a@example.com', 'b@example.com', 'manual',
                                         [first, second])
        self.current = 'b@example.com'
        self.coordinator.switched(ident)
        with patch('nx.resume_flow.attempt_continuation', return_value=('done', 'new_turn_observed')) as act:
            self.coordinator.start()
            limit = time.monotonic() + 3
            while self.coordinator.sessions[-1]['phase'] != 'done' and time.monotonic() < limit:
                time.sleep(.02)
        self.assertEqual(self.coordinator.sessions[-1]['phase'], 'done')
        self.assertEqual(act.call_count, 2)
        self.assertEqual(len([t for t in threading.enumerate() if t.name == 'nx-resume']), 1)
        saved = json.loads((self.paths.data / 'resume.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['sessions'][-1]['phase'], 'done')

    def test_restart_recovers_inflight_queue_without_second_worker(self):
        ident = self.coordinator.prepare('a@example.com', 'b@example.com', 'auto',
                                         [self.event(was_active=True)])
        self.current = 'b@example.com'
        self.coordinator.switched(ident)
        self.coordinator.sessions[-1]['items'][0]['state'] = 'acting'
        self.coordinator._save()
        replacement = self.make_coordinator()
        self.assertEqual(replacement.sessions[-1]['items'][0]['state'], 'failed')
        self.assertEqual(replacement.sessions[-1]['items'][0]['reason'], 'action_outcome_unknown')
        self.assertEqual(replacement.sessions[-1]['phase'], 'failed')

    def test_late_limit_failure_joins_prior_switch_only_if_turn_started_before_it(self):
        ident = self.coordinator.prepare('a@example.com', 'b@example.com', 'auto', [])
        self.current = 'b@example.com'
        self.coordinator.switched(ident)
        switch = self.coordinator.sessions[-1]
        before = self.event(started_at=int(switch['created_at']) - 10,
                            completed_at=int(switch['created_at']))
        self.coordinator.note_limit_events([before], self.current, True)
        self.assertEqual(len(switch['items']), 1)
        self.assertEqual(self.coordinator.pending, [])
        after = self.event(self.OTHER, started_at=int(switch['switched_at']) + 1,
                           completed_at=int(switch['switched_at']) + 2)
        self.coordinator.note_limit_events([after], self.current, True)
        self.assertEqual(len(switch['items']), 1)
        self.assertEqual(len(self.coordinator.pending), 1)

    def test_late_limit_failure_cannot_reopen_failed_native_attempt(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','auto',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        session=self.coordinator.sessions[-1]
        session['phase']='failed';session['items'][0].update(
            state='failed',reason='native_continue_unavailable',attempts=3)
        event=self.event(started_at=int(session['created_at'])-10,
                         completed_at=int(session['switched_at'])+2)
        self.coordinator.note_limit_events([event],self.current,True)
        self.assertEqual(session['phase'],'failed')
        self.assertEqual(session['items'][0]['state'],'failed')
        self.assertEqual(session['items'][0]['attempts'],3)

    def test_failure_crossing_old_switch_is_not_assigned_to_new_account(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','auto',[])
        self.current='b@example.com';self.coordinator.switched(ident)
        switched=int(self.coordinator.sessions[-1]['switched_at'])
        late=self.event(started_at=switched-20,completed_at=switched+301)
        self.coordinator.note_limit_events([late],self.current,True)
        self.assertEqual(self.coordinator.pending,[])
        self.assertEqual(self.coordinator.sessions[-1]['items'][0]['reason'],
                         'switch_boundary_ambiguous')

    def test_account_change_fails_unfinished_work_without_desktop_action(self):
        ident = self.coordinator.prepare('a@example.com', 'b@example.com', 'manual',
                                         [self.event(was_active=True)])
        self.current = 'b@example.com'
        self.coordinator.switched(ident)
        self.current = 'c@example.com'
        with patch('nx.resume_flow.attempt_continuation') as act:
            self.assertIsNone(self.coordinator._ready())
        act.assert_not_called()
        self.assertEqual(self.coordinator.sessions[-1]['phase'], 'failed')
        self.assertEqual(self.coordinator.sessions[-1]['items'][0]['reason'], 'account_changed')

    def test_failure_banner_expires_or_closes_when_viewed(self):
        ident = self.coordinator.prepare('a@example.com', 'b@example.com', 'manual',
                                         [self.event(was_active=True)])
        self.coordinator.switch_failed(ident)
        self.assertEqual(self.coordinator.summary()['failed'], 1)
        self.coordinator.mark_seen(ident)
        self.assertIsNone(self.coordinator.summary())
        self.coordinator.sessions[-1]['seen_at'] = None
        self.coordinator.sessions[-1]['updated_at'] = time.time() - 86401
        self.assertIsNone(self.coordinator.summary())

    def test_pending_limit_events_are_deduplicated_and_bounded(self):
        event = self.event(started_at=int(time.time()) - 20, completed_at=int(time.time()))
        self.coordinator.note_limit_events([event, event], self.current, True)
        self.assertEqual(len(self.coordinator.pending), 1)
        self.coordinator.pending[0]['expires_at'] = time.time() - 1
        self.coordinator.limit_groups()
        self.assertEqual(self.coordinator.pending, [])
        self.assertEqual(self.coordinator.sessions[-1]['phase'], 'failed')
        self.assertEqual(self.coordinator.sessions[-1]['items'][0]['reason'], 'relay_not_available')

    def test_waiting_for_account_survives_restart_without_timeout(self):
        settings={'auto_relay':True,'task_continuation':True,'resume_message':'继续',
                  'auto_relay_excluded':[]}
        self.coordinator.settings=lambda:settings
        self.coordinator.note_limit_events([self.event()],self.current,True)
        self.assertIsNone(self.coordinator.pending[0]['expires_at'])
        self.coordinator.pending[0]['created_at']=time.time()-9*86400
        self.coordinator._save()
        replacement=ResumeCoordinator(self.paths,lambda:self.current,self.stop,Mock(),Mock(),
                                      threading.Lock(),lambda:settings)
        self.assertEqual(replacement.summary()['phase'],'waiting_account')
        self.assertEqual(replacement.details()[0]['items'][0]['thread_id'],self.THREAD)
        self.assertEqual(len(replacement.limit_groups()[self.current]['events']),1)

    def test_waiting_reset_schedule_is_visible_and_persists(self):
        settings={'auto_relay':True,'task_continuation':True,'resume_message':'继续',
                  'auto_relay_excluded':[]}
        self.coordinator.settings=lambda:settings
        self.coordinator.note_limit_events([self.event()],self.current,True)
        reset_at=time.time()+18000
        self.coordinator.defer_limit(self.current,reset_at-time.time(),
                                     refreshed=False,scheduled_at=reset_at)
        self.assertEqual(self.coordinator.details()[0]['scheduled_at'],reset_at)
        self.assertNotIn(self.current,self.coordinator.limit_groups())
        replacement=ResumeCoordinator(self.paths,lambda:self.current,self.stop,Mock(),Mock(),
                                      threading.Lock(),lambda:settings)
        self.assertEqual(replacement.details()[0]['scheduled_at'],reset_at)
        replacement.defer_limit(self.current,0,refreshed=True)
        self.assertIsNone(replacement.details()[0]['scheduled_at'])

    def test_recent_no_account_failure_is_restored_to_waiting(self):
        now=time.time()
        saved={'sessions':[{'id':'old-no-account','source':'auto-limit',
            'origin':self.current,'target':None,'phase':'failed',
            'created_at':now-3600,'updated_at':now-3600,'items':[
                {'thread_id':self.THREAD,'turn_id':self.TURN,'was_active':False,
                 'state':'failed','reason':'relay_not_available'}]}], 'pending':[]}
        (self.paths.data/'resume.json').write_text(json.dumps(saved),encoding='utf-8')
        settings={'auto_relay':True,'task_continuation':True,'resume_message':'继续',
                  'auto_relay_excluded':[]}
        replacement=ResumeCoordinator(self.paths,lambda:self.current,self.stop,Mock(),Mock(),
                                      threading.Lock(),lambda:settings)
        self.assertEqual(replacement.summary()['phase'],'waiting_account')
        self.assertEqual(len(replacement.pending),1)
        self.assertEqual(replacement.sessions,[])

    def test_auto_relay_toggle_and_exclusion_stop_waiting_immediately(self):
        settings={'auto_relay':True,'task_continuation':True,'resume_message':'继续',
                  'auto_relay_excluded':[]}
        self.coordinator.settings=lambda:settings
        self.coordinator.note_limit_events([self.event()],self.current,True)
        self.assertEqual(self.coordinator.summary()['phase'],'waiting_account')
        settings['auto_relay']=False
        self.coordinator.set_auto_enabled(False)
        self.assertIsNone(self.coordinator.summary())
        settings['auto_relay']=True
        self.coordinator.set_auto_enabled(True,[self.current])
        settings['auto_relay_excluded']=[self.current]
        self.assertIsNone(self.coordinator.summary())
        settings['auto_relay_excluded']=[]
        self.coordinator.set_auto_enabled(True)
        self.assertEqual(self.coordinator.summary()['phase'],'waiting_account')

    def test_old_active_work_expires_and_finished_history_is_bounded(self):
        self.coordinator.prepare('a@example.com','b@example.com','auto',
                                 [self.event(was_active=True)])
        session=self.coordinator.sessions[-1]
        session['created_at']=time.time()-86401
        self.assertEqual(self.coordinator.summary()['phase'],'failed')
        self.assertEqual(session['items'][0]['reason'],'resume_expired')
        for _ in range(25):
            ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                           [self.event(was_active=True)])
            self.coordinator.switch_failed(ident)
        self.assertLessEqual(len(self.coordinator.details()),20)
        self.coordinator.sessions[0]['updated_at']=time.time()-8*86400
        self.coordinator.details()
        self.assertTrue(all(time.time()-s['updated_at']<8*86400
                            for s in self.coordinator.sessions))

    def test_turning_off_continuation_skips_waiting_work(self):
        settings={'task_continuation':True,'resume_message':'请接着完成'}
        self.coordinator.settings=lambda: settings
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        settings['task_continuation']=False
        self.coordinator.cancel_active()
        with patch('nx.resume_flow.attempt_continuation') as act:
            self.assertIsNone(self.coordinator._ready())
        act.assert_not_called()
        self.assertEqual(self.coordinator.sessions[-1]['phase'],'cancelled')
        self.assertEqual(self.coordinator.sessions[-1]['items'][0]['state'],'skipped')
        self.assertIsNone(self.coordinator.summary())

    def test_custom_message_is_not_injected_into_desktop_composer(self):
        settings={'task_continuation':True,'resume_message':'请接着完成'}
        self.coordinator.settings=lambda: settings
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        with patch('nx.resume_flow.attempt_continuation',return_value=('done','new_turn_observed')) as act:
            self.coordinator.start()
            limit=time.monotonic()+3
            while self.coordinator.sessions[-1]['phase']!='done' and time.monotonic()<limit:
                time.sleep(.02)
        self.assertEqual(len(act.call_args.args), 5)
        self.assertEqual(settings['resume_message'], '请接着完成')

    def test_preflight_failure_can_retry_only_in_original_account(self):
        settings={'task_continuation':True,'resume_message':'继续'}
        self.coordinator.settings=lambda: settings
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        session=self.coordinator.sessions[-1]
        session['phase']='failed'
        session['items'][0].update(state='failed',reason='desktop_bridge_unavailable')
        self.current='c@example.com'
        self.assertFalse(self.coordinator.retry_task(ident,self.THREAD)['ok'])
        self.current='b@example.com';settings['task_continuation']=False
        self.assertFalse(self.coordinator.retry_task(ident,self.THREAD)['ok'])
        settings['task_continuation']=True
        self.assertTrue(self.coordinator.retry_task(ident,self.THREAD)['ok'])
        self.assertEqual(session['phase'],'resuming')
        self.assertEqual(session['items'][0]['state'],'waiting')
        self.assertEqual(self.coordinator._ready()[0],ident)

    def test_late_quota_event_does_not_reopen_draft_failure(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        session=self.coordinator.sessions[-1]
        session['phase']='failed'
        session['items'][0].update(state='failed',reason='user_draft_present')
        self.coordinator.note_limit_events([self.event(started_at=int(session['created_at'])-10,
            completed_at=int(session['switched_at'])+1)],self.current,True)
        self.assertEqual(session['phase'],'failed')
        self.assertEqual(session['items'][0]['reason'],'user_draft_present')

    def test_continuation_off_still_allows_new_account_limit_relay(self):
        settings={'task_continuation':True,'resume_message':'继续'}
        self.coordinator.settings=lambda: settings
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        switched=int(self.coordinator.sessions[-1]['switched_at'])
        settings['task_continuation']=False;self.coordinator.cancel_active()
        old=self.event(started_at=switched-10,completed_at=switched+1)
        new=self.event(self.OTHER,started_at=switched+5,completed_at=switched+6)
        self.coordinator.note_limit_events([old,new],self.current,True)
        self.assertEqual(len(self.coordinator.sessions),1)
        self.assertEqual(len(self.coordinator.limit_groups()['b@example.com']['events']),1)
        self.assertEqual(self.coordinator.pending[0]['thread_id'],self.OTHER)
        self.assertFalse(self.coordinator.pending[0]['resume_enabled'])

    def test_restart_with_continuation_off_cancels_saved_queue(self):
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        replacement=ResumeCoordinator(self.paths,lambda:self.current,self.stop,Mock(),Mock(),
            threading.Lock(),lambda:{'task_continuation':False,'resume_message':'继续'})
        self.assertEqual(replacement.sessions[-1]['phase'],'cancelled')
        self.assertEqual(replacement.sessions[-1]['items'][0]['state'],'skipped')
        self.assertIsNone(replacement._ready())

    def test_new_account_switch_pauses_older_continuation(self):
        transition={'active':False}
        self.coordinator.desktop_transitioning=lambda: transition['active']
        ident=self.coordinator.prepare('a@example.com','b@example.com','manual',
                                       [self.event(was_active=True)])
        self.current='b@example.com';self.coordinator.switched(ident)
        transition['active']=True
        self.assertIsNone(self.coordinator._ready())
        self.assertEqual(self.coordinator.sessions[-1]['items'][0]['state'],'waiting')
        transition['active']=False
        self.assertEqual(self.coordinator._ready()[0],ident)


if __name__ == '__main__':
    unittest.main()
