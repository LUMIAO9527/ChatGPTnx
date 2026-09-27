"""Read-only access to versioned desktop history databases."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from urllib.parse import quote

def latest_database(home, pattern):
    candidates = []
    for path in Path(home).glob(pattern):
        try:
            candidates.append((path.stat().st_mtime_ns, path.name, path))
        except OSError:
            continue  # A desktop schema migration may remove files mid-scan.
    return max(candidates)[2] if candidates else None

@contextmanager
def read_only(path):
    db = sqlite3.connect('file:' + quote(Path(path).resolve().as_posix(), safe='/:') + '?mode=ro',
                         uri=True, timeout=.25)
    try:
        yield db
    finally:
        db.close()
