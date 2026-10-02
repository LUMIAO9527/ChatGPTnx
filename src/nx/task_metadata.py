"""Read indexed task identities and explicit subagent metadata, never turn text."""
from __future__ import annotations

import json
import re
import sqlite3

from .history_store import latest_database, read_only

_ID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
_THREAD_ID = re.compile(_ID + r'\Z')
_ROLLOUT_ID = re.compile(r'(?:^|[_-])(' + _ID + r')\.jsonl\Z')
_AGENT_PATH = re.compile(r'/root(?:/[A-Za-z0-9_.-]+)*\Z')


def _valid_id(value):
    return isinstance(value, str) and bool(_THREAD_ID.fullmatch(value))


def _unknown():
    return {'kind': 'unknown', 'title': None, 'parent_id': None,
            'agent_path': None, 'canonical_id': None}


def _title(name, title):
    value = next((item for item in (name, title) if isinstance(item, str) and item.strip()), None)
    return ' '.join(value.split())[:120] if value else None


def _agent_path(value):
    return value if isinstance(value, str) and len(value) <= 200 and _AGENT_PATH.fullmatch(value) else None


def _source(raw, thread_source):
    """Source is untrusted data. Inspect only known metadata keys."""
    explicit = thread_source == 'subagent'
    parsed, malformed = None, False
    if isinstance(raw, str) and raw.strip():
        if len(raw) > 65536:
            malformed = True
        else:
            try:
                parsed = json.loads(raw)
                malformed = not isinstance(parsed, (str, dict))
            except ValueError:
                # cli/vscode/appServer and similar plain source labels are
                # indexed ordinary tasks; a damaged JSON object is unknown.
                malformed = raw.lstrip().startswith(('{', '['))
    elif raw is not None and raw != '':
        malformed = True
    if isinstance(parsed, dict) and 'subagent' in parsed:
        explicit = True
    kind = 'subagent' if explicit else ('unknown' if malformed else 'task')
    subagent = parsed.get('subagent') if isinstance(parsed, dict) else None
    spawn = subagent.get('thread_spawn') if isinstance(subagent, dict) else None
    spawn = spawn if isinstance(spawn, dict) else {}
    parent = spawn.get('parent_thread_id')
    return kind, parent if _valid_id(parent) else None, _agent_path(spawn.get('agent_path'))


def task_metadata(home, ids):
    """Map requested IDs to metadata; exact IDs and aliases must jointly be unique.

    Archived rows participate in both display and ambiguity checks. No title
    prefix, cwd, nickname, or agent path is used to invent an identity/parent.
    A missing or unreadable index yields unknown records without a fallback
    scan of rollouts, conversation bodies, or credentials.
    """
    requested = list(dict.fromkeys(item for item in ids if isinstance(item, str)))
    result = {item: _unknown() for item in requested}
    valid = [item for item in requested if _valid_id(item)]
    if not valid:
        return result
    try:
        path = latest_database(home, 'state_*.sqlite')
        if not path:
            return result
        with read_only(path) as db:
            db.execute('PRAGMA query_only=ON')
            columns = {row[1] for row in db.execute('PRAGMA table_info(threads)')}
            if 'id' not in columns:
                return result
            # Fetch only display/relationship metadata; never first_user_message,
            # preview, tool definitions, history item_json, or rollout contents.
            fields = ['id']
            for field in ('name', 'title', 'source', 'thread_source', 'agent_path', 'rollout_path'):
                fields.append(field if field in columns else 'NULL')
            rows = db.execute('SELECT ' + ','.join(fields) + ' FROM threads').fetchall()
            edge_columns = {row[1] for row in db.execute('PRAGMA table_info(thread_spawn_edges)')}
            edges = db.execute('SELECT child_thread_id,parent_thread_id FROM thread_spawn_edges').fetchall() \
                if {'child_thread_id', 'parent_thread_id'} <= edge_columns else []
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return result
    parents = {}
    for child, parent in edges:
        if _valid_id(child) and _valid_id(parent):
            parents.setdefault(child, set()).add(parent)
    for requested_id in valid:
        matches = []
        for row in rows:
            canonical, _, _, _, _, _, rollout = row
            alias = _ROLLOUT_ID.search(rollout) if isinstance(rollout, str) else None
            if canonical == requested_id or (alias and alias[1] == requested_id):
                matches.append(row)
        if len(matches) != 1 or not _valid_id(matches[0][0]):
            continue
        canonical, name, title, source, thread_source, agent_path, _ = matches[0]
        kind, parent, source_path = _source(source, thread_source)
        candidates = parents.get(canonical, set()).copy()
        if parent:
            candidates.add(parent)
        parent = next(iter(candidates)) if len(candidates) == 1 and canonical not in candidates else None
        result[requested_id] = {'kind': kind, 'title': _title(name, title), 'parent_id': parent,
            'agent_path': _agent_path(agent_path) or source_path, 'canonical_id': canonical}
    return result
