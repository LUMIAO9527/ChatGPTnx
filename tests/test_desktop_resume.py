"""Regression checks for exact-task continuation after a desktop relay."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.desktop_resume import active_turns, attempt_continuation as _attempt, latest_turn, title_prefix
from nx.storage import account_identity_key
from test_refactor import credential

def attempt_continuation(home, script, item, stop, log):
    item = {**item, 'expected_account_key': account_identity_key(Path(home)/'auth.json', 'native@example.com')}
    return _attempt(home, script, item, stop, log)


class DesktopResumeTests(unittest.TestCase):
    THREAD = '67cc833f-6330-5bae-a638-9232b5ddfa21'
    FAILED = '33f2513a-16ea-55a8-87a7-c004d4db56a1'
    NEW = '972a9183-fdd0-5c84-9083-afa1ef7d4bc0'

    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '_wip' / 'temp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.home = Path(self.temp.name)
        (self.home / 'auth.json').write_bytes(credential('native@example.com'))
        history = sqlite3.connect(self.home / 'thread_history_1.sqlite')
        history.execute('CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT, '
                        'error_json TEXT, started_at INTEGER, completed_at INTEGER, rollout_ordinal INTEGER)')
        history.commit()
        history.close()
        state = sqlite3.connect(self.home / 'state_5.sqlite')
        state.execute('CREATE TABLE threads (id TEXT, title TEXT, archived INTEGER, name TEXT)')
        state.execute('INSERT INTO threads VALUES (?,?,0,NULL)',
                      (self.THREAD, '测试任务：在原来的 ChatGPT 窗口继续'))
        state.commit()
        state.close()

    def tearDown(self):
        self.temp.cleanup()

    def add_turn(self, turn, status, ordinal):
        db = sqlite3.connect(self.home / 'thread_history_1.sqlite')
        error = json.dumps({'codexErrorInfo': 'usageLimitExceeded'}) if status == 'failed' else None
        db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                   (self.THREAD, turn, status, error, 1900000000 + ordinal,
                    1900000010 + ordinal if status != 'inProgress' else None, ordinal))
        db.commit()
        db.close()

    def test_newer_turn_prevents_duplicate_desktop_action(self):
        self.add_turn(self.FAILED, 'failed', 1)
        self.add_turn(self.NEW, 'inProgress', 2)
        self.assertEqual(latest_turn(self.home, self.THREAD)['turn_id'], self.NEW)
        with patch('nx.desktop_resume.subprocess.run') as run:
            result=attempt_continuation(self.home, self.home / 'helper.ps1',
                                        {'thread_id': self.THREAD, 'turn_id': self.FAILED},
                                        threading.Event(), Mock())
        run.assert_not_called()
        self.assertEqual(result,('skipped','newer_turn'))

    def test_runtime_id_uses_visible_thread_title(self):
        with sqlite3.connect(self.home / 'state_5.sqlite') as db:
            db.execute('ALTER TABLE threads ADD COLUMN rollout_path TEXT')
            db.execute('UPDATE threads SET rollout_path=? WHERE id=?',
                       (f'rollout-date-{self.THREAD}_{self.NEW}.jsonl', self.THREAD))
        db.close()
        self.assertEqual(title_prefix(self.home, self.NEW), title_prefix(self.home, self.THREAD))
        with sqlite3.connect(self.home / 'state_5.sqlite') as db:
            db.execute('UPDATE threads SET archived=1 WHERE id=?', (self.THREAD,))
        db.close()
        self.assertIsNone(title_prefix(self.home, self.NEW))

    def test_exact_turn_remains_readable_after_later_messages(self):
        self.add_turn(self.FAILED, 'failed', 1)
        self.add_turn(self.NEW, 'completed', 2)
        record = latest_turn(self.home, self.THREAD, self.FAILED)
        self.assertEqual(record['turn_id'], self.FAILED)
        self.assertEqual(record['status'], 'failed')
        self.assertIsNone(latest_turn(self.home, self.THREAD, 'not-present'))

    def test_only_latest_active_turn_is_snapshotted(self):
        self.add_turn(self.FAILED, 'failed', 1)
        self.add_turn(self.NEW, 'inProgress', 2)
        with patch('nx.desktop_resume.time.time', return_value=1900000020):
            self.assertEqual(active_turns(self.home),
                             [{'thread_id': self.THREAD, 'turn_id': self.NEW,
                               'was_active': True}])
        self.assertEqual(title_prefix(self.home, self.THREAD),
                         '测试任务：在原来的 ChatGPT 窗口继续')

    def test_quota_failure_uses_bridge_without_desktop_input(self):
        self.add_turn(self.FAILED, 'failed', 1)
        log = Mock()
        item = {'thread_id': self.THREAD, 'turn_id': self.FAILED,
                'settings_file': str(self.home / 'settings.json')}
        with patch('nx.app_bridge.resume_existing', return_value=('done', 'new_turn_observed')) as bridge, \
             patch('nx.desktop_resume.subprocess.run') as run:
            result = attempt_continuation(self.home, self.home / 'helper.ps1', item,
                                          threading.Event(), log)
        bridge.assert_called_once()
        run.assert_not_called()
        self.assertEqual(result,('done','new_turn_observed'))

    def test_interruption_uses_the_native_desktop_action(self):
        self.add_turn(self.FAILED, 'interrupted', 1)

        def desktop_invocation(command, **kwargs):
            self.assertEqual(command[command.index('-Action') + 1], 'interrupted')
            self.add_turn(self.NEW, 'inProgress', 2)
            return Mock(stdout='invoked:native_continue\n', returncode=0)

        with patch('nx.desktop_resume.subprocess.run', side_effect=desktop_invocation) as run:
            result=attempt_continuation(self.home, self.home / 'helper.ps1',
                                        {'thread_id': self.THREAD, 'turn_id': self.FAILED},
                                        threading.Event(), Mock())
        run.assert_called_once()
        self.assertEqual(result,('done','new_turn_observed'))

    def test_missing_native_continue_uses_guarded_bridge_fallback(self):
        self.add_turn(self.FAILED, 'interrupted', 1)
        (self.home / 'settings.json').write_text('{}')
        item = {'thread_id': self.THREAD, 'turn_id': self.FAILED,
                'settings_file': str(self.home / 'settings.json')}
        with patch('nx.desktop_location.locate_task', return_value=('located', 'task_opened_by_id')), \
             patch('nx.desktop_resume._invoke', return_value=Mock(
                stdout='skip:native_continue_unavailable\n', returncode=2)), \
             patch('nx.app_bridge.resume_existing', return_value=('done', 'new_turn_observed')) as bridge:
            result = attempt_continuation(self.home, self.home / 'helper.ps1', item,
                                          threading.Event(), Mock())
        self.assertEqual(result, ('done', 'new_turn_observed'))
        self.assertTrue(bridge.call_args.kwargs['interrupted'])

    def test_uncertain_native_action_never_uses_bridge_fallback(self):
        self.add_turn(self.FAILED, 'interrupted', 1)
        (self.home / 'settings.json').write_text('{}')
        item = {'thread_id': self.THREAD, 'turn_id': self.FAILED,
                'settings_file': str(self.home / 'settings.json')}
        with patch('nx.desktop_location.locate_task', return_value=('located', 'task_opened_by_id')), \
             patch('nx.desktop_resume._invoke', return_value=Mock(
                stdout='uncertain:native_continue\n', returncode=2)), \
             patch('nx.app_bridge.resume_existing') as bridge:
            result = attempt_continuation(self.home, self.home / 'helper.ps1', item,
                                          threading.Event(), Mock())
        self.assertEqual(result, ('failed', 'action_outcome_unknown'))
        bridge.assert_not_called()

    def test_pre_switch_active_snapshot_does_not_prove_interruption(self):
        self.add_turn(self.FAILED, 'inProgress', 1)
        event = {'thread_id': self.THREAD, 'turn_id': self.FAILED, 'was_active': True}
        with patch('nx.desktop_resume._invoke') as run, patch('nx.app_bridge.resume_existing') as bridge:
            result = attempt_continuation(self.home, self.home/'helper.ps1', event,
                                          threading.Event(), Mock())
        run.assert_not_called()
        bridge.assert_not_called()
        self.assertEqual(result, ('failed', 'desktop_task_not_idle'))

    def test_archived_title_collision_blocks_wrong_window_target(self):
        self.add_turn(self.FAILED, 'interrupted', 1)
        db = sqlite3.connect(self.home / 'state_5.sqlite')
        try:
            db.execute('INSERT INTO threads VALUES (?,?,1,NULL)',
                       (self.NEW, '测试任务：在原来的 ChatGPT 窗口继续'))
            db.commit()
        finally:
            db.close()
        with patch('nx.desktop_resume.subprocess.run') as run:
            result = attempt_continuation(self.home, self.home/'helper.ps1',
                                          {'thread_id': self.THREAD, 'turn_id': self.FAILED},
                                          threading.Event(), Mock())
        run.assert_not_called()
        self.assertEqual(result, ('failed', 'title_unavailable_or_ambiguous'))
        self.assertIsNone(title_prefix(self.home, self.NEW))

    def test_ambiguous_title_does_not_act_in_desktop(self):
        self.add_turn(self.FAILED,'interrupted',1)
        db=sqlite3.connect(self.home / 'state_5.sqlite')
        db.execute('INSERT INTO threads VALUES (?,?,0,NULL)',
                   (self.NEW,'测试任务：在原来的 ChatGPT 窗口继续，其他内容'))
        db.commit();db.close()
        with patch('nx.desktop_resume.subprocess.run') as run:
            result=attempt_continuation(self.home,self.home/'helper.ps1',
                                        {'thread_id':self.THREAD,'turn_id':self.FAILED},
                                        threading.Event(),Mock())
        self.assertEqual(result,('failed','title_unavailable_or_ambiguous'))
        run.assert_not_called()

    def test_display_name_overrides_stale_initial_title(self):
        db=sqlite3.connect(self.home / 'state_5.sqlite')
        db.execute('UPDATE threads SET name=? WHERE id=?',
                   ('修复 Codex 内置浏览器控制连接超时',self.THREAD))
        db.commit();db.close()
        self.assertEqual(title_prefix(self.home,self.THREAD),'修复 Codex 内置浏览器控制连接超时')

    def test_unsnapshotted_running_turn_is_left_alone(self):
        self.add_turn(self.FAILED,'inProgress',1)
        with patch('nx.desktop_resume.subprocess.run') as run:
            result=attempt_continuation(self.home,self.home/'helper.ps1',
                                        {'thread_id':self.THREAD,'turn_id':self.FAILED},
                                        threading.Event(),Mock())
        self.assertEqual(result,('failed','desktop_task_not_idle'))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
