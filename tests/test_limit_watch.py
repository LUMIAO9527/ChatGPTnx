"""Read-only usage limit detection tests."""
from pathlib import Path
from contextlib import closing, contextmanager
import json
import sqlite3
import sys
import tempfile
import unittest

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
