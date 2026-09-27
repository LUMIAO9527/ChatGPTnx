"""Locate an existing task by its persisted identity, without sending a message."""
from __future__ import annotations

import json
import re
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


def locate_task(home, runtime_id, settings_file, *, expected_turn=None, stop=None,
                required_status=None):
    """Read and navigate only. A navigation acknowledgement is never resume success.

    Automatic callers supply the interrupted turn. A newer or running turn is
    left alone. Keep the configured real source; never impersonate the target.
    """
    from .desktop_resume import latest_turn

    def settings():
        return json.loads(Path(settings_file).read_text(encoding='utf-8-sig')).get('settings', {})

    try:
        initial = settings()
        source = initial.get('resume_source_thread_id')
        if not source or not valid_setting('resume_source_thread_id', source):
            return 'failed', 'resume_source_unconfigured'
        target = canonical_task(home, runtime_id)
        if not target:
            return 'failed', 'task_identity_unavailable'
        if source == target:
            return 'failed', 'resume_source_is_target'
        auth = Path(home) / 'auth.json'
        before = fingerprint(auth)
        if not before:
            return 'failed', 'account_guard_unavailable'
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
        if current.get('resume_source_thread_id') != source:
            return 'failed', 'resume_source_unconfigured'
        if expected_turn and current.get('task_continuation') is not True:
            return 'failed', 'continuation_disabled'
        if stop and stop.is_set():
            return 'failed', 'shutting_down'
        if fingerprint(auth) != before:
            return 'failed', 'account_changed'
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
    except (BridgeUnavailable, OSError, ValueError, TypeError, AttributeError):
        return 'failed', 'desktop_bridge_unavailable'
    finally:
        if pipe:
            pipe.close()
