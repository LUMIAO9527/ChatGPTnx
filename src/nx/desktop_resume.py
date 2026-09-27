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
            rows = db.execute('SELECT id, name, title, archived FROM threads').fetchall()
            columns = {r[1] for r in db.execute('PRAGMA table_info(threads)')}
            aliases = {}
            if 'rollout_path' in columns:
                for thread, rollout in db.execute('SELECT id, rollout_path FROM threads'):
                    # Desktop keeps its visible ID while a replaced runtime gets
                    # a suffix ID in both the rollout filename and turn history.
                    match = re.search(r'_([0-9a-f-]{36})\.jsonl$', str(rollout or ''))
                    if match and THREAD_ID.fullmatch(match[1]):
                        aliases[match[1]] = thread
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
    return {thread: (wanted if wanted and sum(title.startswith(wanted)
             for title in titles.values()) == 1 else None)
            for thread in set(thread_ids) for canonical in [aliases.get(thread, thread)]
            for wanted in [titles.get(canonical) if canonical in active else None]}


def title_prefix(home, thread_id):
    return title_prefixes(home, [thread_id]).get(thread_id)


def _desktop_command(home, script, thread_id, prefix, action, settings_file=None):
    auth_file = Path(home) / 'auth.json'
    auth_hash = fingerprint(auth_file)
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


def attempt_continuation(home, script, item, stop, log):
    """Act once in the existing desktop window; the caller owns serialization."""
    thread_id, turn_id = item['thread_id'], item['turn_id']
    if stop.is_set():
        return 'retry', 'shutting_down'
    if not THREAD_ID.fullmatch(str(thread_id)):
        return 'failed', 'invalid_thread_id'
    record = latest_turn(home, thread_id)
    if not record:
        return 'retry', 'history_unavailable'
    if record['turn_id'] != turn_id:
        return 'done', 'newer_turn'
    status = record['status']
    if status == 'inProgress' and not item.get('was_active'):
        return 'failed', 'unsnapshotted_active_turn'
    if status == 'failed' and (not isinstance(record['error'], dict) or
                               record['error'].get('codexErrorInfo') != 'usageLimitExceeded'):
        return 'failed', 'unrelated_failure'
    if status not in ('failed', 'interrupted', 'inProgress'):
        return 'done', 'task_no_longer_needs_resume'
    if item.get('settings_file'):
        try:
            from .settings import normalize_settings
            settings = normalize_settings(json.loads(Path(item['settings_file']).read_text(
                encoding='utf-8-sig')).get('settings', {}))
        except (OSError, ValueError, AttributeError):
            return 'failed', 'account_guard_unavailable'
        # UI continuation is intentionally the single user-visible route:
        # type the configured continuation message and invoke Send directly.
    prefix = title_prefix(home, thread_id)
    if not prefix:
        return 'failed', 'title_unavailable_or_ambiguous'
    try:
        command = _desktop_command(home, script, thread_id, prefix,
                                   'interrupted' if status == 'inProgress' else status,
                                   item.get('settings_file'))
        if not command:
            return 'failed', 'account_guard_unavailable'
        # Resolve the task through the Codex desktop bridge first. The same
        # task can appear in both a project list and Recents; title-based UIA
        # selection sees those as two windows even when they are one task.
        # Navigation is read-only and carries no continuation message.
        if item.get('settings_file'):
            from .desktop_location import locate_task
            located, location_reason = locate_task(
                home, thread_id, item['settings_file'], expected_turn=turn_id, stop=stop)
            log.info('desktop_location_result state=%s reason=%s', located, location_reason)
            if located != 'located':
                return located, location_reason
            current = latest_turn(home, thread_id)
            if not current:
                return 'retry', 'history_unavailable'
            if current['turn_id'] != turn_id:
                return 'done', 'newer_turn'
            if stop.is_set():
                return 'retry', 'shutting_down'
            result = _invoke(command + ['-WaitForTarget'])
        else:
            result = _invoke(command)
        _log_location_evidence(result, log)
        # Never retry UI after a timeout, unknown result, or possible send.
        outcome = (result.stdout or '').strip().splitlines()[-1:]
        raw_label = outcome[0] if outcome else ''
        label = raw_label if re.fullmatch(r'(?:skip|uncertain|invoked):[a-z_]+', raw_label) else ('unrecognized_response' if outcome else 'no_response')
        for line in (result.stdout or '').splitlines():
            if not line.startswith('evidence:'):
                continue
            try:
                evidence = json.loads(line[len('evidence:'):])
                state = evidence.get('state')
                count = evidence.get('patterns')
                lengths = evidence.get('lengths')
                if state in ('empty', 'present', 'unknown') and type(count) is int and 0 <= count <= 2 and isinstance(lengths, list) and len(lengths) <= 2 and all(type(n) is int and 0 <= n <= 10000000 for n in lengths):
                    log.info('composer_evidence state=%s patterns=%d lengths=%s', state, count, lengths)
            except (ValueError, TypeError, AttributeError):
                pass
        log.info('desktop_resume_result action=%s result=%s code=%d',
                 status, label, result.returncode)
        if label == 'skip:task_already_running':
            return 'done', 'task_already_running'
        if label in ('invoked:native_continue', 'invoked:send_message') and result.returncode == 0:
            for _ in range(75):
                after = latest_turn(home, thread_id)
                if after and after['turn_id'] != turn_id:
                    item['observed_turn_id'] = after['turn_id']
                    return 'done', 'new_turn_observed'
                if stop.wait(.2):
                    return 'failed', 'action_outcome_unknown'
            return 'failed', 'start_not_observed'
        if label.startswith('uncertain:'):
            return 'failed', 'action_outcome_unknown'
        if label in ('skip:user_draft_present', 'skip:user_attachment_present', 'skip:composer_in_use'):
            return 'defer', label[5:]
        if label in ('skip:invalid_resume_message', 'skip:composer_unavailable',
                     'skip:composer_in_use', 'skip:composer_state_unknown', 'skip:account_changed', 'skip:continuation_disabled',
                     'skip:automatic_send_unavailable'):
            return 'failed', label[5:]
        if label.startswith('skip:'):
            return 'retry', label[5:]
        return 'failed', 'action_outcome_unknown'
    except subprocess.TimeoutExpired:
        log.warning('desktop_resume_error type=TimeoutExpired')
        return 'failed', 'action_outcome_unknown'
    except OSError as error:
        log.warning('desktop_resume_error type=%s', type(error).__name__)
        return 'retry', type(error).__name__


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
