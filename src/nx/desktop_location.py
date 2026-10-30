"""Locate an existing task by its persisted identity, without sending a message."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from .app_bridge import BridgeUnavailable, BridgeUncertain, call_params, discover_when_ready, text_result
from .history_store import latest_database, read_only
from .settings import valid_setting
from .storage import fingerprint


def canonical_task(home, runtime_id, *, allow_archived=False):
    """Require one explicit index relationship, including archived collisions."""
    if not valid_setting('resume_source_thread_id', runtime_id) or not runtime_id:
        return None
    path = latest_database(home, 'state_*.sqlite')
    if not path:
        return None
    try:
        with read_only(path) as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(threads)')}
            rollout = 'rollout_path' if 'rollout_path' in columns else 'NULL'
            rows = db.execute(f'SELECT id, archived, {rollout} FROM threads').fetchall()
        matches = [r for r in rows if r[0] == runtime_id or re.search(
            r'_' + re.escape(runtime_id) + r'\.jsonl$', str(r[2] or ''))]
        if (len(matches) == 1 and (allow_archived or not matches[0][1])
                and valid_setting('resume_source_thread_id', matches[0][0])):
            return matches[0][0]
    except Exception:
        pass
    return None


def resume_source(home, configured, target, *, excluded=()):
    """Resolve a real local caller afresh; never use a queued target as caller.

    An existing configured caller stays authoritative. A missing caller is
    replaced only by an indexed, user-owned main task. No task is created and
    no setting is rewritten. The subsequent desktop read verifies that caller
    before navigation or dispatch can occur.
    """
    from .task_metadata import task_metadata

    if not valid_setting('resume_source_thread_id', configured):
        raise BridgeUnavailable('resume_source_unconfigured')
    blocked = {target}
    for ident in excluded:
        blocked.add(canonical_task(home, ident, allow_archived=True) or ident)
    source = canonical_task(home, configured, allow_archived=True) if configured else None
    if source in blocked:
        raise BridgeUnavailable('resume_source_is_target')
    if source:
        return source
    path = latest_database(home, 'state_*.sqlite')
    if not path:
        raise BridgeUnavailable('resume_source_unavailable')
    try:
        with read_only(path) as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(threads)')}
            if not {'id', 'archived'} <= columns:
                raise ValueError('caller_metadata_unavailable')
            user_flags = []
            if 'has_user_event' in columns:
                user_flags.append('has_user_event=1')
            if 'thread_source' in columns:
                user_flags.append("thread_source='user'")
            if not user_flags:
                raise ValueError('caller_metadata_unavailable')
            updated = next((key for key in ('updated_at_ms', 'updated_at', 'created_at')
                            if key in columns), 'id')
            rows = db.execute('SELECT id FROM threads WHERE (' + ' OR '.join(user_flags) + ') '
                              f'ORDER BY archived ASC, {updated} DESC, id ASC LIMIT 64').fetchall()
        ids = [row[0] for row in rows if row[0] not in blocked]
        metadata = task_metadata(home, ids)
        for ident in ids:
            entry = metadata.get(ident, {})
            if (entry.get('kind') == 'task' and entry.get('canonical_id') == ident
                    and not entry.get('parent_id')
                    and entry.get('agent_path') in (None, '/root')):
                return ident
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    raise BridgeUnavailable('resume_source_unavailable')


def locate_task(home, runtime_id, settings_file, *, expected_turn=None, stop=None,
                required_status=None, excluded=()):
    """Read and navigate only. A navigation acknowledgement is never resume success.

    Automatic callers supply the interrupted turn. A newer or running turn is
    left alone. Resolve a real local caller and never impersonate the target.
    """
    from .desktop_resume import latest_turn

    def settings():
        return json.loads(Path(settings_file).read_text(encoding='utf-8-sig')).get('settings', {})

    try:
        initial = settings()
        configured = initial.get('resume_source_thread_id', '')
        target = canonical_task(home, runtime_id)
        if not target:
            return 'failed', 'task_identity_unavailable'
        source = resume_source(home, configured, target, excluded=excluded)
        auth = Path(home) / 'auth.json'
        before = fingerprint(auth)
        if not before:
            return 'failed', 'account_guard_unavailable'
    except BridgeUnavailable as error:
        return 'failed', str(error)
    except (OSError, ValueError, TypeError, AttributeError):
        return 'failed', 'account_guard_unavailable'

    pipe = None
    try:
        pipe = discover_when_ready(stop or threading.Event(), auth, before,
                                   required={'read_thread': {'threadId'},
                                             'navigate_to_codex_page': {'threadId'}})
        snapshot = text_result(pipe.request('tools/call', call_params(
            source, 'nx-locate-' + str(uuid.uuid4()), 'read_thread',
            {'threadId': target, 'hostId': 'local', 'turnLimit': 1,
             'includeOutputs': False, 'maxOutputCharsPerItem': 0})))
        thread = snapshot.get('thread', {})
        if thread.get('id') != target or thread.get('kind') != 'codex':
            return 'failed', 'bridge_target_mismatch'
        if expected_turn:
            turns = snapshot.get('turns', [])
            if not turns:
                return 'failed', 'history_unavailable'
            if turns[0].get('id') != expected_turn:
                return 'skipped', 'newer_turn'
            if required_status and turns[0].get('status') != required_status:
                return ('failed', 'desktop_task_not_idle' if turns[0].get('status') == 'inProgress'
                        else 'task_state_changed')
            if turns[0].get('status') == 'inProgress':
                return 'failed', 'desktop_task_not_idle'
            if turns[0].get('status') not in ('failed', 'interrupted'):
                return 'skipped', 'task_no_longer_needs_resume'
            record = latest_turn(home, runtime_id)
            if not record:
                return 'failed', 'history_unavailable'
            if record['turn_id'] != expected_turn:
                return 'skipped', 'newer_turn'
        current = settings()
        if current.get('resume_source_thread_id', '') != configured:
            return 'failed', 'resume_source_unconfigured'
        if expected_turn and current.get('task_continuation') is not True:
            return 'failed', 'continuation_disabled'
        if stop and stop.is_set():
            return 'failed', 'shutting_down'
        if fingerprint(auth) != before:
            return 'failed', 'account_changed'
        if canonical_task(home, source, allow_archived=True) != source:
            return 'failed', 'resume_source_unavailable'
        reply = text_result(pipe.request('tools/call', call_params(
            source, 'nx-locate-' + str(uuid.uuid4()), 'navigate_to_codex_page',
            {'threadId': target}), side_effect=True))
        # The read establishes identity; require a positive navigation response.
        if reply.get('navigated') is not True:
            return 'failed', 'task_navigation_unconfirmed'
        return 'located', 'task_opened_by_id'
    except BridgeUncertain:
        # Navigation cannot submit or start a turn. A future navigation is safe,
        # but this attempt must not type anything after an unconfirmed response.
        return 'failed', 'task_navigation_unconfirmed'
    except BridgeUnavailable as error:
        reason = str(error)
        return 'failed', reason if reason in (
            'desktop_bridge_ambiguous', 'desktop_request_rejected',
            'account_changed', 'shutting_down') else 'desktop_bridge_unavailable'
    except (OSError, ValueError, TypeError, AttributeError):
        return 'failed', 'desktop_bridge_unavailable'
    finally:
        if pipe:
            pipe.close()
