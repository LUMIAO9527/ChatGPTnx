"""Read-only usage limit detection tests."""
from pathlib import Path
from contextlib import closing, contextmanager
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.limit_watch import UsageLimitWatcher


@contextmanager
def database(path: Path):
    connection = sqlite3.connect(path)
    try:
        connection.execute('''CREATE TABLE thread_turns (
            thread_id TEXT NOT NULL, turn_id TEXT NOT NULL,
            rollout_ordinal INTEGER NOT NULL, status TEXT NOT NULL,
            error_json TEXT, started_at INTEGER, completed_at INTEGER,
            PRIMARY KEY (thread_id, turn_id))''')
        yield connection
        connection.commit()
    finally:
        connection.close()


def error(code):
    return json.dumps({'message': 'redacted fixture', 'codexErrorInfo': code})


class LimitWatcherTests(unittest.TestCase):
    def test_missing_schema_exposes_only_safe_failure_location(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            sqlite3.connect(home/'thread_history_1.sqlite').close()
            watcher = UsageLimitWatcher(home)
            self.assertFalse(watcher.prime())
            self.assertFalse(watcher.available)
            self.assertEqual(watcher.failure['error_type'], 'OperationalError')
            self.assertNotIn(raw, json.dumps(watcher.failure))

    def test_concurrent_insert_between_queries_is_emitted_on_next_poll_once(self):
        from nx.history_store import read_only
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); path = home/'thread_history_1.sqlite'
            with database(path) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                           ('base','base',1,'completed',None,1,10))
            watcher = UsageLimitWatcher(home); self.assertTrue(watcher.prime())
            @contextmanager
            def concurrent_read(target):
                with read_only(target) as db:
                    class Connection:
                        def execute(self, sql, *args):
                            result = db.execute(sql, *args)
                            if 'MAX(completed_at)' in sql:
                                with closing(sqlite3.connect(path)) as writer:
                                    writer.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                                        ('new','new',1,'failed',error('usageLimitExceeded'),2,11))
                                    writer.commit()
                            return result
                    yield Connection()
            with patch('nx.limit_watch.read_only', concurrent_read):
                self.assertEqual(watcher.poll(), [])
            self.assertEqual([e['turn_id'] for e in watcher.poll()], ['new'])
            self.assertEqual(watcher.poll(), [])

    def test_history_is_ignored_and_new_same_second_limit_is_emitted_once(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); path = home / 'thread_history_1.sqlite'
            with database(path) as db:
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                           ('old','turn-old',1,'failed',error('usageLimitExceeded'),1,100))
            watcher = UsageLimitWatcher(home)
            self.assertTrue(watcher.prime());self.assertEqual(watcher.poll(),[])
            with closing(sqlite3.connect(path)) as db:
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                           ('new','turn-new',1,'failed',error('usageLimitExceeded'),2,100))
                db.commit()
            events = watcher.poll()
            self.assertEqual([(e['thread_id'],e['turn_id']) for e in events],[('new','turn-new')])
            self.assertEqual(watcher.poll(),[])

    def test_non_limit_failure_is_never_emitted(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw); path = home / 'thread_history_1.sqlite'
            with database(path) as db:
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                           ('base','base-turn',1,'completed',None,1,10))
            watcher = UsageLimitWatcher(home);self.assertTrue(watcher.prime())
            with closing(sqlite3.connect(path)) as db:
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                           ('other','other-turn',1,'failed',error('serverOverloaded'),2,11))
                db.commit()
            self.assertEqual(watcher.poll(),[])


if __name__ == '__main__':
    unittest.main()
