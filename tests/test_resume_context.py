"""Recover stale caller identities using indexed main-task metadata only."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.app_bridge import BridgeUnavailable, call_params, text_result
from nx.desktop_location import resume_source

TARGET = '11111111-1111-4111-8111-111111111111'
SOURCE = '22222222-2222-4222-8222-222222222222'
STALE = '33333333-3333-4333-8333-333333333333'
CHILD = '44444444-4444-4444-8444-444444444444'
ALIAS = '55555555-5555-4555-8555-555555555555'


class ResumeContextTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '_wip' / 'temp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.db = self.home / 'state_1.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE threads (id TEXT, archived INTEGER, rollout_path TEXT, '
                       'source TEXT, thread_source TEXT, agent_path TEXT, '
                       'has_user_event INTEGER, updated_at INTEGER)')
        self.add(TARGET, updated=200)
        self.add(SOURCE, updated=100)

    def add(self, ident, *, updated=300, archived=0, source='cli', user=1,
            agent=None, rollout=None, kind=None):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)',
                       (ident, archived, rollout, source, kind, agent, user, updated))

    def test_deleted_configured_source_uses_verified_main_identity(self):
        self.assertEqual(resume_source(self.home, STALE, TARGET), SOURCE)

    def test_first_run_can_resolve_without_hidden_configuration(self):
        self.assertEqual(resume_source(self.home, '', TARGET), SOURCE)

    def test_existing_configured_source_keeps_priority(self):
        self.add(CHILD, updated=500)
        self.assertEqual(resume_source(self.home, SOURCE, TARGET), SOURCE)

    def test_alias_is_normalized_to_real_source_identity(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE threads SET rollout_path=? WHERE id=?',
                       (f'rollout_{ALIAS}.jsonl', SOURCE))
        self.assertEqual(resume_source(self.home, ALIAS, TARGET), SOURCE)

    def test_queued_targets_are_excluded_even_through_aliases(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE threads SET rollout_path=? WHERE id=?',
                       (f'rollout_{ALIAS}.jsonl', SOURCE))
        with self.assertRaisesRegex(BridgeUnavailable, 'resume_source_unavailable'):
            resume_source(self.home, STALE, TARGET, excluded=[ALIAS])

    def test_subagents_and_untrusted_metadata_never_become_callers(self):
        self.add(CHILD, source=json.dumps({'subagent': {'thread_spawn': {}}}))
        self.add(ALIAS, source='{malformed')
        self.add(STALE, kind='subagent')
        self.assertEqual(resume_source(self.home, '', TARGET), SOURCE)

    def test_non_root_agents_and_empty_system_tasks_are_excluded(self):
        self.add(CHILD, agent='/root/child')
        self.add(ALIAS, user=0)
        self.assertEqual(resume_source(self.home, '', TARGET), SOURCE)

    def test_desktop_user_source_is_supported_when_event_flag_is_unset(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE threads SET has_user_event=0, thread_source=? WHERE id=?',
                       ('user', SOURCE))
        self.assertEqual(resume_source(self.home, '', TARGET), SOURCE)

    def test_archived_sources_remain_usable_without_unarchiving(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE threads SET archived=1 WHERE id=?', (SOURCE,))
        self.assertEqual(resume_source(self.home, STALE, TARGET), SOURCE)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT archived FROM threads WHERE id=?', (SOURCE,)).fetchone()[0], 1)

    def test_target_is_never_impersonated(self):
        with self.assertRaisesRegex(BridgeUnavailable, 'resume_source_is_target'):
            resume_source(self.home, TARGET, TARGET)

    def test_resolution_does_not_write_the_index(self):
        before = self.db.read_bytes()
        resume_source(self.home, STALE, TARGET)
        self.assertEqual(before, self.db.read_bytes())

    def test_caller_host_is_explicitly_local(self):
        self.assertEqual(call_params(SOURCE, 'read', 'read_thread', {})['hostId'], 'local')

    def test_desktop_rejection_is_distinct_from_transport_failure(self):
        with self.assertRaisesRegex(BridgeUnavailable, 'desktop_request_rejected'):
            text_result({'success': False, 'contentItems': []})


if __name__ == '__main__':
    unittest.main()
