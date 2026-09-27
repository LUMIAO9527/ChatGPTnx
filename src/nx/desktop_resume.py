"""Resume relay-affected tasks through the user's existing ChatGPT desktop window."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path


THREAD_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


from .history_store import latest_database, read_only as _read_only
from .storage import fingerprint


def _history(home):
    return latest_database(home, 'thread_history_*.sqlite')


def latest_turn(home, thread_id, turn_id=None):
    """Read the latest turn, or one exact observed turn even after later messages."""
    if not THREAD_ID.fullmatch(str(thread_id)):
        return None
    path = _history(home)
    if not path:
        return None
    try:
        with _read_only(path) as db:
            query = ('SELECT turn_id, status, error_json, started_at, completed_at '
                     'FROM thread_turns WHERE thread_id = ? ')
            args = (thread_id,)
            if turn_id is not None:
                query += 'AND turn_id = ? '
                args += (turn_id,)
            row = db.execute(query + 'ORDER BY rollout_ordinal DESC LIMIT 1', args).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if not row:
        return None
    try:
        error = json.loads(row[2]) if row[2] else None
    except (TypeError, ValueError):
        error = None
    return {'turn_id': row[0], 'status': row[1], 'error': error,
            'started_at': row[3], 'completed_at': row[4]}


def active_turns(home):
    """Snapshot live-looking turns before ChatGPT is restarted for a relay."""
    path = _history(home)
    if not path:
        return []
    try:
        with _read_only(path) as db:
            rows = db.execute('SELECT t.thread_id, t.turn_id FROM thread_turns t '
                              'JOIN (SELECT thread_id, MAX(rollout_ordinal) ordinal '
                              'FROM thread_turns GROUP BY thread_id) latest '
                              'ON latest.thread_id=t.thread_id AND latest.ordinal=t.rollout_ordinal '
                              'WHERE t.status=? AND t.started_at>=? ORDER BY t.started_at DESC',
                              ('inProgress', int(time.time()) - 86400)).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [{'thread_id': thread, 'turn_id': turn, 'was_active': True}
            for thread, turn in rows]


def title_prefixes(home, thread_ids):
    """Resolve visible titles for a batch while rejecting ambiguous prefixes."""
    path = latest_database(home, 'state_*.sqlite')
    if not path:
        return {}
    try:
        with _read_only(path) as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(threads)')}
            name_column = 'name' if 'name' in columns else 'NULL'
            rows = db.execute(f'SELECT id, {name_column}, title, archived FROM threads').fetchall()
            aliases = {}
            if 'rollout_path' in columns:
                for thread, rollout in db.execute('SELECT id, rollout_path FROM threads'):
                    # Desktop keeps its visible ID while a replaced runtime gets
                    # a suffix ID in both the rollout filename and turn history.
                    match = re.search(r'_([0-9a-f-]{36})\.jsonl$', str(rollout or ''))
                    if match and THREAD_ID.fullmatch(match[1]):
                        aliases.setdefault(match[1], set()).add(thread)
    except (OSError, sqlite3.Error):
        return {}
    def prefix(title):
        if '## My request:' in title:
            title = title.split('## My request:', 1)[1].strip()
        return title.replace('\r', ' ').replace('\n', ' ')[:24]
    titles = {thread: prefix(name or title or '') for thread, name, title, archived in rows
              if isinstance(name or title, str) and (name or title)}
    active = {thread for thread, _, _, archived in rows if not archived}
    # UI Automation exposes a shortened title, not the technical thread ID.
    # Archived tasks can still be open in a desktop window. Include them in
    # collision detection, but never enqueue them as active resume targets.
    resolved = {}
    indexed = {row[0] for row in rows}
    for thread in set(thread_ids):
        matches = aliases.get(thread, set()) | ({thread} if thread in indexed else set())
        if len(matches) != 1:
            resolved[thread] = None
            continue
        canonical = next(iter(matches))
        wanted = titles.get(canonical) if canonical in active else None
        resolved[thread] = wanted if wanted and sum(t.startswith(wanted) for t in titles.values()) == 1 else None
    return resolved



def title_prefix(home, thread_id):
    return title_prefixes(home, [thread_id]).get(thread_id)


def _desktop_command(home, script, thread_id, prefix, action, settings_file=None, *, expected_auth_hash=None):
    auth_file = Path(home) / 'auth.json'
    auth_hash = expected_auth_hash or fingerprint(auth_file)
    if not auth_hash:
        return None
    command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
               '-ExecutionPolicy', 'Bypass', '-File', str(script),
               '-ThreadId', thread_id, '-TitlePrefix', prefix, '-Action', action,
               '-AuthFile', str(auth_file), '-ExpectedAuthHash', auth_hash]
    if settings_file:
        command.extend(['-SettingsFile', str(settings_file)])
    return command


def _invoke(command):
    return subprocess.run(command, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=28,
                          creationflags=0x08000000 if os.name == 'nt' else 0)


def navigate_existing_task(home, script, thread_id, settings_file=None):
    """An explicit user request may navigate, but never launch another client."""
    if not THREAD_ID.fullmatch(str(thread_id)):
        return {'ok': False, 'error': '任务编号不合法'}
    if settings_file:
        from .desktop_location import locate_task
        state, reason = locate_task(home, thread_id, settings_file)
        if state == 'located':
            return {'ok': True}
        if reason in ('account_changed', 'bridge_target_mismatch', 'task_navigation_unconfirmed'):
            return {'ok': False, 'error': '未确认原任务已打开，请在桌面端检查'}
    prefix = title_prefix(home, thread_id)
    if not prefix:
        return {'ok': False, 'error': '无法唯一定位原任务，请在桌面端打开'}
    command = _desktop_command(home, script, thread_id, prefix, 'failed')
    if not command:
        return {'ok': False, 'error': '无法核对当前桌面账号'}
    try:
        result = _invoke(command + ['-NavigateOnly'])
        label = (result.stdout or '').strip().splitlines()[-1:]
        if result.returncode == 0 and label == ['opened:existing_task']:
            return {'ok': True}
        errors = {'skip:desktop_not_running': '请先打开 ChatGPT 桌面端',
                  'skip:desktop_window_ambiguous': '无法确定接续目标窗口',
                  'skip:account_changed': '桌面账号已变化，请重试'}
        return {'ok': False, 'error': errors.get(label[0] if label else '',
                                                 '未定位到原任务，请在当前桌面端打开')}
    except (OSError, subprocess.TimeoutExpired):
        return {'ok': False, 'error': '当前桌面窗口暂不可操作，请在桌面端打开原任务'}


def continuation_guard(home, item):
    """Bind an action to the queued account identity, not just a stable file."""
    from .storage import identity, account_identity_key, fingerprint, claims
    auth = Path(home) / 'auth.json'
    before = fingerprint(auth)
    expected = item.get('expected_account_key')
    email, workspace = identity(auth)
    subject = claims(auth).get('sub')
    if (not isinstance(subject, str) or not subject or not before or not email or not workspace or not isinstance(expected, str)
            or not re.fullmatch(r'[0-9a-f]{64}', expected)):
        return None, 'account_guard_unavailable'
    if account_identity_key(auth, email) != expected:
        return None, 'account_changed'
    return before, ''


def observe_start(home, item, stop, *, expected_auth, expected_turn=None,
                  allow_same_turn=False):
    """Observe a started turn; an ACK or a changed ID alone is not success."""
    from .storage import fingerprint
    from .quota_policy import number
    auth = Path(home) / 'auth.json'
    for _ in range(75):
        if fingerprint(auth) != expected_auth:
            return 'failed', 'action_outcome_unknown'
        after = latest_turn(home, item['thread_id'])
        if after and THREAD_ID.fullmatch(str(after.get('turn_id', ''))):
            new_id = after['turn_id']
            is_new = new_id != item['turn_id']
            matches_ack = expected_turn is None or new_id == expected_turn
            if is_new and not matches_ack:
                return 'failed', 'action_outcome_unknown'
            if matches_ack and (is_new or allow_same_turn):
                status = after.get('status')
                if is_new and status == 'failed':
                    item['observed_turn_id'] = new_id
                    error = after.get('error')
                    message = str(error.get('message', '')) if isinstance(error, dict) else ''
                    reason = ('resume_auth_failed' if '401' in message or
                              'unauthorized' in message.lower() else 'resumed_turn_failed')
                    return 'failed', reason
                if (status in ('inProgress', 'completed') and
                        number(after.get('started_at')) and after['started_at'] > 0):
                    item['observed_turn_id'] = new_id
                    return 'done', 'new_turn_observed' if is_new else 'native_turn_resumed'
        if stop.wait(.2):
            return 'failed', 'action_outcome_unknown'
    return 'failed', 'start_not_observed'


def attempt_continuation(home, script, item, stop, log):
    """Exactly two routes: native Continue OR one bridge message, never both."""
    thread_id, turn_id = item.get('thread_id'), item.get('turn_id')
    if stop.is_set():
        return 'failed', 'shutting_down'
    if not all(THREAD_ID.fullmatch(str(v)) for v in (thread_id, turn_id)):
        return 'failed', 'invalid_task_id'
    record = latest_turn(home, thread_id)
    if not record:
        return 'failed', 'history_unavailable'
    if record['turn_id'] != turn_id:
        return 'skipped', 'newer_turn'
    status = record['status']
    if status == 'failed':
        error = record.get('error')
        if not isinstance(error, dict) or error.get('codexErrorInfo') != 'usageLimitExceeded':
            return 'failed', 'unrelated_failure'
        if not item.get('settings_file'):
            return 'failed', 'account_guard_unavailable'
        from .app_bridge import resume_existing
        return resume_existing(home, item, stop, log)
    if status == 'inProgress':
        # A pre-switch snapshot does not prove that a live-looking turn stopped.
        return 'failed', 'desktop_task_not_idle'
    if status != 'interrupted':
        return 'skipped', 'task_no_longer_needs_resume'
    before, reason = continuation_guard(home, item)
    if not before:
        return 'failed', reason
    prefix = title_prefix(home, thread_id)
    if not prefix:
        return 'failed', 'title_unavailable_or_ambiguous'
    try:
        command = _desktop_command(home, script, thread_id, prefix, 'interrupted',
                                   item.get('settings_file'), expected_auth_hash=before)
        if not command:
            return 'failed', 'account_guard_unavailable'
        current = latest_turn(home, thread_id)
        if not current:
            return 'failed', 'history_unavailable'
        if current['turn_id'] != turn_id:
            return 'skipped', 'newer_turn'
        if current['status'] != 'interrupted':
            return 'failed', 'task_state_changed'
        if stop.is_set():
            return 'failed', 'shutting_down'
        # UIA locates only the unique task title resolved from the exact ID.
        # It never launches a client, probes an editor, or submits text.
        result = _invoke(command + ['-WaitForTarget'])
        _log_location_evidence(result, log)
        outcome = (result.stdout or '').strip().splitlines()[-1:]
        raw_label = outcome[0] if outcome else ''
        allowed = {'invoked:native_continue', 'uncertain:native_continue', 'uncertain:desktop_error'}
        allowed.update('skip:' + r for r in (
            'native_continue_unavailable', 'native_continue_not_ready', 'native_continue_ambiguous',
            'account_changed', 'account_guard_unavailable', 'continuation_disabled', 'bridge_required',
            'task_already_running', 'target_not_visible', 'target_changed', 'desktop_not_running',
            'desktop_window_ambiguous', 'desktop_location_unreadable', 'desktop_error'))
        label = raw_label if raw_label in allowed else 'unrecognized_response'
        log.info('desktop_resume_result action=interrupted result=%s code=%d',
                 label, result.returncode)
        if label == 'invoked:native_continue' and result.returncode == 0:
            return observe_start(home, item, stop, expected_auth=before, allow_same_turn=True)
        if label == 'skip:task_already_running':
            return 'skipped', 'task_already_running'
        if label.startswith('skip:') and result.returncode == 2:
            return 'failed', label[5:]
        return 'failed', 'action_outcome_unknown'
    except subprocess.TimeoutExpired:
        log.warning('desktop_resume_error type=TimeoutExpired')
        return 'failed', 'action_outcome_unknown'
    except OSError:
        # Process creation failed before UIA ran. Do not schedule a retry.
        log.warning('desktop_resume_error type=OSError')
        return 'failed', 'desktop_not_running'


def _log_location_evidence(result, log):
    """Persist counts only: no titles, composer contents, or account data."""
    for line in (result.stdout or '').splitlines():
        if not line.startswith('location:'):
            continue
        try:
            evidence = json.loads(line[len('location:'):])
            values = [evidence.get(k) for k in ('windows', 'document_windows',
                      'entry_windows', 'read_errors')]
            if all(type(v) is int and 0 <= v <= 10000 for v in values):
                log.info('desktop_location windows=%d document_windows=%d entry_windows=%d read_errors=%d', *values)
        except (ValueError, TypeError, AttributeError):
            pass
