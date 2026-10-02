"""Read-only, transactional detection of newly quota-rejected desktop turns."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from .history_store import latest_database, read_only
from .diagnostics import exception_location

class UsageLimitWatcher:
    def __init__(self, codex_home: Path):
        self.codex_home = Path(codex_home)
        self.path = None
        self.completed_at = 0
        self.seen = set()
        self.available = False
        self.failure = None

    def _database(self):
        return latest_database(self.codex_home, 'thread_history_*.sqlite')

    def prime(self):
        """Startup and schema migrations never replay old failures."""
        self.available = False
        self.failure = None
        path = self._database()
        if not path:
            return False
        try:
            with read_only(path) as db:
                db.execute('BEGIN')
                newest = int(db.execute('SELECT COALESCE(MAX(completed_at),0) FROM thread_turns').fetchone()[0] or 0)
                rows = db.execute('SELECT thread_id,turn_id FROM thread_turns WHERE completed_at>=?', (newest,)).fetchall()
        except (OSError, sqlite3.Error, ValueError, TypeError) as error:
            self.failure = exception_location(error)
            return False
        self.path, self.completed_at = path, newest
        self.seen = {(str(thread),str(turn)) for thread,turn in rows}
        self.available = True
        return True

    def poll(self, consume=None):
        """Emit once. With a consumer, advance only after it returns successfully."""
        self.available = False
        self.failure = None
        path = self._database()
        if not path:
            return []
        if self.path is None or path != self.path:
            self.prime()
            return []
        try:
            with read_only(path) as db:
                db.execute('BEGIN')
                newest = int(db.execute('SELECT COALESCE(MAX(completed_at),0) FROM thread_turns').fetchone()[0] or 0)
                rows = db.execute('SELECT thread_id,turn_id,started_at,completed_at,error_json '
                    'FROM thread_turns WHERE status=? AND error_json IS NOT NULL '
                    'AND completed_at>=? ORDER BY completed_at,thread_id,turn_id',
                    ('failed',self.completed_at)).fetchall()
        except (OSError, sqlite3.Error, ValueError, TypeError) as error:
            self.failure = exception_location(error)
            return []
        self.available = True
        events, next_seen = [], set(self.seen)
        for thread,turn,started,completed,raw in rows:
            key = str(thread),str(turn)
            if key in next_seen:
                continue
            next_seen.add(key)
            try:
                error = json.loads(raw)
                if isinstance(error,dict) and error.get('codexErrorInfo') == 'usageLimitExceeded':
                    events.append({'thread_id':key[0],'turn_id':key[1],
                                   'started_at':int(started or 0),'completed_at':int(completed or 0)})
            except (TypeError, ValueError, OverflowError):
                continue
        from .desktop_resume import desktop_task_events
        events = desktop_task_events(self.codex_home, events)
        if events and consume is not None:
            consume(events)  # A failed journal write leaves the cursor untouched.
        boundary = max(newest,self.completed_at)
        keys_at_boundary = {(str(row[0]),str(row[1])) for row in rows if row[3] == boundary}
        self.seen = (next_seen if boundary == self.completed_at else keys_at_boundary)
        self.completed_at = boundary
        return events
