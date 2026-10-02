"""Synthetic index metadata only: no live Codex database, history or credentials."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nx.task_metadata import task_metadata

PARENT = '11111111-1111-4111-8111-111111111111'
CHILD = '22222222-2222-4222-8222-222222222222'
ALIAS = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'


class TaskMetadataTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '_wip' / 'metadata-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / 'state_5.sqlite'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE threads (id TEXT, name TEXT, title TEXT, source TEXT, '
                       'thread_source TEXT, agent_path TEXT, rollout_path TEXT, archived INTEGER)')
            db.execute('CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)')

    def insert(self, ident, *, name=None, title=None, source='vscode', thread_source='user',
               agent_path=None, rollout_path=None, archived=0):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?)',
                       (ident, name, title, source, thread_source, agent_path, rollout_path, archived))

    def edge(self, parent, child):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO thread_spawn_edges VALUES (?,?,?)', (parent, child, 'open'))

    def get(self, ident=CHILD):
        return task_metadata(self.home, [ident])[ident]

    def test_explicit_spawn_metadata_identifies_child_and_parent(self):
        source = json.dumps({'subagent': {'thread_spawn': {
            'parent_thread_id': PARENT, 'agent_path': '/root/audit', 'agent_nickname': 'Fixture'}}})
        self.insert(CHILD, title='', source=source)
        self.edge(PARENT, CHILD)
        self.assertEqual(self.get(), {'kind': 'subagent', 'title': None, 'parent_id': PARENT,
                                     'agent_path': '/root/audit', 'canonical_id': CHILD})

    def test_column_marker_and_other_subagent_source_types_are_explicit(self):
        self.insert(CHILD, thread_source='subagent', source='vscode', agent_path='/root/child')
        self.insert(OTHER, source=json.dumps({'subagent': {'review': {}}}))
        self.assertEqual(self.get()['kind'], 'subagent')
        self.assertEqual(self.get(OTHER)['kind'], 'subagent')
        self.assertIsNone(self.get(OTHER)['parent_id'])

    def test_agent_path_or_edge_alone_does_not_invent_subagent_kind(self):
        self.insert(CHILD, source='cli', agent_path='/root/looks_like_child')
        self.edge(PARENT, CHILD)
        self.assertEqual(self.get()['kind'], 'task')
        self.assertEqual(self.get()['parent_id'], PARENT)

    def test_name_preferred_and_shared_title_prefix_does_not_hide_display_title(self):
        self.insert(CHILD, name='共同前缀的任务，第一项', title='old title')
        self.insert(OTHER, name='共同前缀的任务，第二项', archived=1)
        values = task_metadata(self.home, [CHILD, OTHER])
        self.assertEqual(values[CHILD]['title'], '共同前缀的任务，第一项')
        self.assertEqual(values[OTHER]['title'], '共同前缀的任务，第二项')

    def test_title_is_normalized_and_bounded_to_120_characters(self):
        self.insert(CHILD, title='  标题\n' + '长' * 130)
        title = self.get()['title']
        self.assertEqual(len(title), 120); self.assertNotIn('\n', title)
        self.assertTrue(title.startswith('标题 '))

    def test_unique_rollout_suffix_alias_resolves_even_if_archived(self):
        self.insert(CHILD, name='archived fixture', rollout_path='rollout-date_' + ALIAS + '.jsonl', archived=1)
        result = self.get(ALIAS)
        self.assertEqual(result['canonical_id'], CHILD)
        self.assertEqual(result['title'], 'archived fixture')
        self.assertEqual(result['kind'], 'task')

    def test_hyphen_rollout_suffix_is_supported_and_prefix_ids_are_unknown(self):
        self.insert(CHILD, rollout_path='C:/fixture/rollout-2026-10-02T20-29-17-' + ALIAS + '.jsonl')
        self.assertEqual(self.get(ALIAS)['canonical_id'], CHILD)
        self.assertEqual(self.get(ALIAS[:8])['kind'], 'unknown')

    def test_duplicate_alias_and_exact_id_alias_collision_are_unknown(self):
        self.insert(CHILD, rollout_path='rollout_' + ALIAS + '.jsonl')
        self.insert(OTHER, rollout_path='rollout_' + ALIAS + '.jsonl', archived=1)
        self.assertEqual(self.get(ALIAS)['kind'], 'unknown')
        self.insert(ALIAS, name='exact row')
        self.assertIsNone(self.get(ALIAS)['canonical_id'])

    def test_duplicate_exact_rows_are_unknown(self):
        self.insert(CHILD); self.insert(CHILD)
        self.assertEqual(self.get()['kind'], 'unknown')

    def test_conflicting_explicit_parents_and_self_parent_are_not_guessed(self):
        self.insert(CHILD, source=json.dumps({'subagent': {'thread_spawn': {'parent_thread_id': PARENT}}}))
        self.edge(OTHER, CHILD)
        self.assertEqual(self.get()['kind'], 'subagent'); self.assertIsNone(self.get()['parent_id'])
        self.insert(OTHER, thread_source='subagent')
        self.edge(OTHER, OTHER)
        self.assertIsNone(self.get(OTHER)['parent_id'])

    def test_edge_only_parent_for_explicit_subagent(self):
        self.insert(CHILD, thread_source='subagent', source=None)
        self.edge(PARENT, CHILD)
        self.assertEqual(self.get()['parent_id'], PARENT)

    def test_legacy_index_without_source_is_an_ordinary_indexed_task(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE threads')
            db.execute('DROP TABLE thread_spawn_edges')
            db.execute('CREATE TABLE threads (id TEXT,title TEXT)')
            db.execute('INSERT INTO threads VALUES (?,?)', (CHILD, 'legacy fixture'))
        self.assertEqual(self.get()['kind'], 'task')
        self.assertEqual(self.get(OTHER)['kind'], 'unknown')

    def test_malformed_source_cannot_execute_or_invent_parent(self):
        self.insert(CHILD, source='{"subagent": invalid()', agent_path='/root/audit')
        self.assertEqual(self.get()['kind'], 'unknown')
        self.assertIsNone(self.get()['parent_id'])

    def test_source_is_not_executed_and_no_rollout_body_is_read(self):
        self.insert(CHILD, source='vscode', rollout_path='C:/private/no-access_' + ALIAS + '.jsonl')
        with patch('pathlib.Path.read_bytes', side_effect=AssertionError('must not read files')), \
             patch('pathlib.Path.read_text', side_effect=AssertionError('must not read files')):
            self.assertEqual(self.get(ALIAS)['canonical_id'], CHILD)

    def test_unreadable_database_and_missing_database_return_unknown(self):
        with patch('nx.task_metadata.read_only', side_effect=sqlite3.OperationalError('locked')):
            self.assertEqual(self.get()['kind'], 'unknown')
        self.assertEqual(task_metadata(self.home/'missing', [CHILD])[CHILD]['kind'], 'unknown')

    def test_invalid_ids_are_not_interpreted_as_queries(self):
        self.insert(CHILD)
        result = task_metadata(self.home, ["' OR 1=1 --", '../auth.json', CHILD])
        self.assertEqual(result["' OR 1=1 --"]['kind'], 'unknown')
        self.assertEqual(result['../auth.json']['kind'], 'unknown')
        self.assertEqual(result[CHILD]['kind'], 'task')


if __name__ == '__main__':
    unittest.main()
