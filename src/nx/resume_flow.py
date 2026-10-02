"""Bounded, durable coordination for turns affected by an account switch."""
from __future__ import annotations

import copy
import hashlib
import re
import json
import threading
import time
import uuid

from .desktop_resume import attempt_continuation, title_prefixes, latest_turn, THREAD_ID, desktop_task_events
from .task_metadata import task_metadata
from .quota_policy import number
from .storage import atomic_bytes, load_owned_document, account_identity_key


TERMINAL = {'done', 'failed', 'skipped'}
HISTORY_SECONDS = 7 * 86400
ACTIVE_SECONDS = 86400
FAILURE_BANNER_SECONDS = 86400
PENDING_SECONDS = 300
from .resume_policy import (ATTENTION_REASONS, RETRYABLE_REASONS,
                            AUTO_RETRY_PRE_DISPATCH, AUTO_RETRY_TURN_FAILURES,
                            auto_retry_delay, turn_failure_reason)

class ResumeCoordinator:
    """One NX worker acts in the existing desktop window, never an app-server."""

    def __init__(self, paths, current_email, stop, log, notify, desktop_gate,
                 settings=None, desktop_transitioning=None):
        self.paths = paths
        self.current_email = current_email
        self.stop = stop
        self.log = log
        self.notify = notify
        self.desktop_gate = desktop_gate
        self.settings = settings or (lambda: {'task_continuation': True,
                                               'resume_message': '继续'})
        self.desktop_transitioning = desktop_transitioning or (lambda: False)
        self.path = paths.data / 'resume.json'
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.worker = None
        saved, self.recovery_path = load_owned_document(self.path)
        self.sessions = saved.get('sessions', []) if isinstance(saved, dict) else []
        self.pending = saved.get('pending', []) if isinstance(saved, dict) else []
        claims = saved.get('claims', []) if isinstance(saved, dict) else []
        self.blocked = (bool(self.recovery_path) or saved.get('blocked') is True
                        or not isinstance(claims, list)
                        or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in claims))
        self.claims = {v for v in claims if isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v)} if isinstance(claims, list) else set()
        if not isinstance(self.sessions, list):
            self.sessions = []
        if not isinstance(self.pending, list):
            self.pending = []
        self._sanitize_saved()
        # Migrate prior attempts before retention/clear can remove their history.
        self.claims.update(self._claim_key(i) for session in self.sessions
                           for i in session['items']
                           if i.get('state') == 'acting' or
                           (i.get('state') in TERMINAL and i.get('attempts', 0) > 0)
                           or i.get('reason') in ('action_outcome_unknown', 'start_not_observed',
                                                  'new_turn_observed', 'native_turn_resumed'))
        self._committed = copy.deepcopy((self.sessions, self.pending, self.claims))
        if self.blocked:
            self._save()
        self._restore_recent_unavailable()
        self._recover()
        with self.lock:
            if not self.settings().get('task_continuation'):
                self.cancel_active()
            if self._prune():
                self._save()

    def _sanitize_saved(self):
        """Treat malformed persisted records as data, not executable state."""
        now = time.time()
        sessions = []
        known_ids = set()
        for raw in self.sessions:
            if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not isinstance(raw.get('items'), list):
                continue
            if raw['id'] in known_ids:
                continue
            known_ids.add(raw['id'])
            s = copy.deepcopy(raw)
            if s.get('phase') not in ('switching', 'resuming', 'done', 'failed', 'skipped', 'cancelled'):
                s['phase'] = 'failed'
            for key in ('created_at', 'updated_at'):
                if not number(s.get(key)) or s[key] <= 0 or s[key] > now + 86400:
                    s[key] = now
            for key in ('switched_at', 'seen_at'):
                if not number(s.get(key)):
                    s[key] = None
            for key in ('origin', 'target', 'source'):
                if not isinstance(s.get(key), str):
                    s[key] = None
            unique = {}
            for raw_item in s['items']:
                if not isinstance(raw_item, dict) or not all(THREAD_ID.fullmatch(str(raw_item.get(k, ''))) for k in ('thread_id', 'turn_id')):
                    continue
                item = {**self._item(raw_item), **raw_item}
                item['was_active'] = raw_item.get('was_active') is True
                if item.get('state') not in TERMINAL | {'waiting', 'acting'}:
                    item.update(state='failed', reason='invalid_saved_state')
                for key in ('attempts', 'next_try'):
                    if not number(item.get(key)) or item[key] < 0:
                        item[key] = 0
                item.pop('deferred_since', None)
                item['retry_authorized'] = raw_item.get('retry_authorized') is True
                if not isinstance(item.get('reason'), str):
                    item['reason'] = ''
                if item.get('reason') in {
                        'manual_message_required', 'automatic_send_unavailable',
                        'user_draft_present', 'composer_in_use', 'composer_state_unknown',
                        'composer_unavailable', 'user_attachment_present',
                        'input_guard_unavailable', 'input_focus_changed',
                        'composer_selection_unavailable', 'selection_not_collapsed'}:
                    # Only a migration label, never an editor check or wait path.
                    item.update(state='failed', reason='legacy_route_removed',
                                retry_authorized=False)

                unique[self._key(item)] = item
            s['items'] = list(unique.values())[:100]
            if not s['items'] and s['phase'] == 'resuming':
                s['phase'] = 'done'
            sessions.append(s)
        self.sessions = sessions
        pending = {}
        for item in self.pending:
            if not isinstance(item, dict) or not all(THREAD_ID.fullmatch(str(item.get(k, ''))) for k in ('thread_id', 'turn_id')):
                continue
            if not isinstance(item.get('origin'), str):
                continue
            item = dict(item)
            for key in ('created_at', 'next_try'):
                if not number(item.get(key)) or item[key] < 0:
                    item[key] = now if key == 'created_at' else 0
            for key in ('expires_at', 'scheduled_at', 'account_reset_at'):
                if not number(item.get(key)):
                    item[key] = None
            for key in ('auto_enabled', 'resume_enabled', 'refreshed'):
                item[key] = item.get(key) is True
            pending[self._key(item)] = item
        self.pending = list(pending.values())[-100:]

    @staticmethod
    def _key(item):
        return item.get('thread_id'), item.get('turn_id')

    @staticmethod
    def _claim_key(item):
        # A turn UUID remains the same when the task is addressed by an alias.
        return hashlib.sha256(str(item.get('turn_id', '')).encode('utf-8')).hexdigest()

    def _claim_has_only_safe_failures(self, item):
        """Permit a later switch after prior attempts provably sent nothing."""
        previous = [old for session in self.sessions for old in session['items']
                    if self._claim_key(old) == self._claim_key(item)
                    and old.get('attempts', 0) > 0]
        return bool(previous) and all(old.get('state') == 'failed' and
                                      old.get('reason') in AUTO_RETRY_PRE_DISPATCH
                                      for old in previous)

    def _target_identity(self, target):
        try:
            return account_identity_key(self.paths.snapshot(target), target) if target else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _item(event):
        return {'thread_id': event['thread_id'], 'turn_id': event['turn_id'],
                'was_active': bool(event.get('was_active')), 'state': 'waiting',
                'attempts': 0, 'next_try': 0, 'reason': ''}

    def _restore_recent_unavailable(self):
        """Keep a recent pre-upgrade no-account failure eligible for recovery."""
        settings = self.settings()
        if not settings.get('auto_relay') or not settings.get('task_continuation'):
            return
        now = time.time()
        excluded = set(settings.get('auto_relay_excluded') or [])
        keys = {self._key(item) for item in self.pending}
        kept = []
        restored = False
        for session in self.sessions:
            items = session.get('items', [])
            origin = session.get('origin')
            eligible = (session.get('source') == 'auto-limit' and
                        session.get('phase') == 'failed' and not session.get('target') and
                        origin and origin not in excluded and items and
                        0 <= now - session.get('created_at', 0) <= 86400 and
                        all(i.get('reason') == 'relay_not_available' for i in items))
            if not eligible:
                kept.append(session)
                continue
            for item in items:
                key = self._key(item)
                if key in keys:
                    continue
                keys.add(key)
                created = session.get('created_at', now)
                self.pending.append({'thread_id': key[0], 'turn_id': key[1],
                                     'was_active': bool(item.get('was_active')),
                                     'origin': origin, 'created_at': created,
                                     'expires_at': None,
                                     'auto_enabled': True, 'resume_enabled': True,
                                     'refreshed': False, 'next_try': 0,
                                     'scheduled_at': None})
            restored = True
        if restored:
            self.sessions = kept
            self._save()

    def _prune(self):
        now = time.time()
        old_sessions, old_pending = len(self.sessions), len(self.pending)
        changed = False
        for session in self.sessions:
            if (session.get('phase') in ('switching', 'resuming') and
                    now - session.get('created_at', now) >= ACTIVE_SECONDS):
                self._fail_remaining(session, 'resume_expired')
                changed = True
        eligible = [s for s in self.sessions
                    if s.get('phase') in ('switching', 'resuming')
                    or now - s.get('updated_at', now) <
                    (HISTORY_SECONDS if s.get('items') else PENDING_SECONDS)]
        active = [s for s in eligible if s.get('phase') in ('switching', 'resuming')]
        recent = sorted((s for s in eligible if s.get('phase') not in ('switching', 'resuming')),
                        key=lambda s: s.get('updated_at', 0))
        keep = {s['id'] for s in active + recent[-20:]}
        self.sessions = [s for s in eligible if s['id'] in keep]
        def expired(item):
            limit = item.get('expires_at')
            return isinstance(limit, (int, float)) and limit <= now
        expired_pending = [p for p in self.pending if expired(p)]
        self.pending = [p for p in self.pending if not expired(p)][-100:]
        enabled_by_origin = {}
        for item in expired_pending:
            if item.get('auto_enabled') and item.get('resume_enabled', True):
                enabled_by_origin.setdefault(item.get('origin'), []).append(item)
        for origin, enabled in enabled_by_origin.items():
            self.sessions.append({
                'id': uuid.uuid4().hex, 'source': 'auto-limit', 'origin': origin,
                'target': None, 'phase': 'failed',
                'created_at': min(p.get('created_at', now) for p in enabled),
                'updated_at': now,
                'switched_at': None, 'seen_at': None,
                'items': [{**self._item(p), 'state': 'failed', 'reason': 'relay_not_available'}
                          for p in enabled],
            })
        return changed or len(self.sessions) != old_sessions or len(self.pending) != old_pending

    def _save(self):
        self._prune()
        try:
            atomic_bytes(self.path, json.dumps({'sessions': self.sessions, 'pending': self.pending, 'claims': sorted(self.claims), 'blocked': self.blocked},
                                               ensure_ascii=False, separators=(',', ':'),
                                               allow_nan=False).encode('utf-8'))
        except (OSError, ValueError):
            self.sessions, self.pending, self.claims = copy.deepcopy(self._committed)
            raise
        self._committed = copy.deepcopy((self.sessions, self.pending, self.claims))
        self.notify()

    def _recover(self):
        changed = False
        current = self.current_email()
        with self.lock:
            for session in self.sessions:
                if not isinstance(session, dict):
                    continue
                session_changed = False
                phase = session.get('phase')
                if phase == 'switching':
                    if session.get('target') == current:
                        session['phase'] = 'resuming'
                    else:
                        self._fail_remaining(session, 'switch_not_completed')
                    session_changed = True
                if session.get('phase') == 'resuming':
                    for item in session.get('items', []):
                        if item.get('state') == 'acting':
                            item.update(state='failed', reason='action_outcome_unknown')
                            session_changed = True
                    if current != session.get('target'):
                        self._fail_remaining(session, 'account_changed')
                        session_changed = True
                if session.get('phase') == 'failed' and current == session.get('target'):
                    for item in session.get('items', []):
                        if (item.get('state') != 'failed' or
                                item.get('reason') != 'resumed_turn_failed'):
                            continue
                        observed = item.get('observed_turn_id')
                        if not THREAD_ID.fullmatch(str(observed)):
                            continue
                        record = latest_turn(self.paths.home, item['thread_id'], observed)
                        if record and self._queue_automatic_retry(
                                session, item, turn_failure_reason(record.get('error')),
                                time.time(), record):
                            session_changed = True
                if session.get('phase') == 'resuming' and session.get('items') and all(i['state'] in TERMINAL for i in session['items']):
                    session['phase'] = 'failed' if any(i['state'] == 'failed' for i in session['items']) else 'done'
                    session_changed = True
                if session_changed:
                    session['updated_at'] = time.time()
                    changed = True
            if changed:
                self._save()

    @staticmethod
    def _fail_remaining(session, reason):
        for item in session.get('items', []):
            if item.get('state') not in TERMINAL:
                item['state'] = 'failed'
                item['reason'] = reason
        session['phase'] = 'failed'
        session['updated_at'] = time.time()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, name='nx-resume', daemon=True)
        self.worker.start()
        self.wake.set()

    def prepare(self, origin, target, source, active, failures=()):
        now = time.time()
        with self.lock:
            self._prune()
            all_events = list(active) + list(failures)
            all_events += [p for p in self.pending if p.get('origin') == origin]
            all_events = desktop_task_events(self.paths.home, all_events)
            unique = {}
            for event in all_events:
                key = self._key(event)
                if key not in unique:
                    unique[key] = self._item(event)
                else:
                    unique[key]['was_active'] |= bool(event.get('was_active'))
            session = {'id': uuid.uuid4().hex, 'source': source, 'origin': origin,
                       'target': target, 'target_identity_key': self._target_identity(target),
                       'phase': 'switching', 'created_at': now,
                       'updated_at': now, 'switched_at': None, 'seen_at': None,
                       'items': list(unique.values())}
            self.sessions.append(session)
            self._save()
            return session['id']

    def switched(self, session_id):
        with self.lock:
            session = self._session(session_id)
            session['phase'] = 'resuming' if session['items'] else 'done'
            session['switched_at'] = session['updated_at'] = time.time()
            keys = {self._key(item) for item in session['items']}
            self.pending = [p for p in self.pending if self._key(p) not in keys]
            self._save()
        self.wake.set()

    def switch_failed(self, session_id):
        with self.lock:
            session = self._session(session_id)
            self._fail_remaining(session, 'switch_failed')
            self._save()

    def _session(self, session_id):
        return next(s for s in self.sessions if s['id'] == session_id)

    def _matching_session(self, event):
        key = self._key(event)
        exact = [s for s in self.sessions if s.get('target')
                 and s.get('phase') != 'cancelled'
                 and (s.get('switched_at') or s.get('phase') == 'switching'
                      or s.get('source') == 'auto-recovered') and
                 any(self._key(i) == key for i in s['items'])]
        if exact:
            return exact[-1]
        started = int(event.get('started_at') or 0)
        completed = int(event.get('completed_at') or 0)
        matches = [s for s in self.sessions if s.get('target')
                   and s.get('source') != 'auto-recovered'
                   and s.get('phase') not in ('failed', 'cancelled')
                   and started and started <= s['created_at']
                   and s['created_at'] - 30 <= completed <=
                   (s.get('switched_at') or time.time()) + PENDING_SECONDS]
        return matches[0] if len(matches) == 1 else None

    def note_limit_events(self, events, origin, auto_enabled):
        events = desktop_task_events(self.paths.home, events)
        if not events:
            return
        now = time.time()
        with self.lock:
            for event in events:
                key = self._key(event)
                session = self._matching_session(event)
                if session:
                    if session.get('phase') == 'cancelled':
                        continue
                    existing = next((i for i in session['items'] if self._key(i) == key), None)
                    if not existing and self._claim_key(event) not in self.claims:
                        session['items'].append(self._item(event))
                    if session['phase'] in TERMINAL and any(
                            i['state'] not in TERMINAL for i in session['items']):
                        session['phase'] = 'resuming'
                    session['updated_at'] = now
                    continue
                started = int(event.get('started_at') or 0)
                completed = int(event.get('completed_at') or 0)
                crossed_switch = any(s.get('switched_at') and s.get('origin') != s.get('target')
                                     and started <= s['switched_at'] <= completed
                                     for s in self.sessions) if started and completed else False
                if crossed_switch:
                    if self.settings().get('task_continuation'):
                        self.sessions.append({'id': uuid.uuid4().hex, 'source': 'auto-limit',
                            'origin': None, 'target': None, 'phase': 'failed',
                            'created_at': now, 'updated_at': now, 'switched_at': None,
                            'seen_at': None, 'items': [{**self._item(event), 'state': 'failed',
                                                        'reason': 'switch_boundary_ambiguous'}]})
                    continue
                if self._claim_key(event) in self.claims or any(self._key(p) == key for p in self.pending):
                    continue
                self.pending.append({**event, 'origin': origin, 'created_at': now,
                                     'expires_at': None if auto_enabled else now + PENDING_SECONDS,
                                     'auto_enabled': bool(auto_enabled),
                                     'resume_enabled': bool(self.settings().get('task_continuation')),
                                     'refreshed': False, 'next_try': 0,
                                     'scheduled_at': None})
            self._save()
        self.wake.set()

    def _skip_subagent_work(self):
        """Retire queued background-agent work without changing old outcomes."""
        waiting = [(session, item) for session in self.sessions
                   if session.get('phase') in ('switching', 'resuming')
                   for item in session.get('items', []) if item.get('state') == 'waiting']
        ids = [item['thread_id'] for _, item in waiting] + [p['thread_id'] for p in self.pending]
        if not ids:
            return
        metadata = task_metadata(self.paths.home, ids)
        hidden = {key for key, value in metadata.items() if value.get('kind') == 'subagent'}
        if not hidden:
            return
        self.pending = [p for p in self.pending if p['thread_id'] not in hidden]
        for session, item in waiting:
            if item['thread_id'] in hidden:
                item.update(state='skipped', reason='subagent_task', next_try=0,
                            retry_authorized=False)
                session['updated_at'] = time.time()
                if all(i['state'] in TERMINAL for i in session['items']):
                    session['phase'] = 'failed' if any(i['state'] == 'failed' for i in session['items']) else 'done'
        self._save()

    def limit_groups(self):
        now = time.time()
        with self.lock:
            self._skip_subagent_work()
            if self._prune():
                self._save()
            groups = {}
            for item in self.pending:
                if not item.get('auto_enabled'):
                    continue
                group = groups.setdefault(item['origin'], {'events': [], 'refreshed': True,
                                                           'next_try': float('inf')})
                group['events'].append(copy.deepcopy(item))
                group['refreshed'] &= bool(item.get('refreshed'))
                group['next_try'] = min(group['next_try'], item.get('next_try', 0))
            return {origin: group for origin, group in groups.items()
                    if group['next_try'] <= now}

    def has_limit_origin(self, origin):
        with self.lock:
            return any(item.get('origin') == origin and item.get('auto_enabled')
                       for item in self.pending)

    def defer_limit(self, origin, delay, refreshed=None, scheduled_at=None):
        with self.lock:
            for item in self.pending:
                if item.get('origin') == origin:
                    item['next_try'] = time.time() + delay
                    item['scheduled_at'] = scheduled_at
                    if refreshed is not None:
                        item['refreshed'] = refreshed
            self._save()

    def disable_limit(self, origin):
        self.set_limit_enabled(origin, False)

    def set_limit_enabled(self, origin, enabled):
        with self.lock:
            for item in self.pending:
                if item.get('origin') == origin:
                    item['auto_enabled'] = bool(enabled)
                    if enabled:
                        item['next_try'] = 0
                        item['refreshed'] = False
                        item['expires_at'] = None
                        item['scheduled_at'] = None
                    else:
                        item['expires_at'] = time.time() + PENDING_SECONDS
                        item['scheduled_at'] = None
            self._save()

    def set_auto_enabled(self, enabled, excluded=()):
        excluded = set(excluded)
        with self.lock:
            now = time.time()
            for item in self.pending:
                active = bool(enabled and item.get('origin') not in excluded)
                item['auto_enabled'] = active
                item['expires_at'] = None if active else now + PENDING_SECONDS
                item['scheduled_at'] = None
                if active:
                    item['next_try'] = 0
                    item['refreshed'] = False
            self._save()

    def recover_current(self, origin):
        """Continue failed turns after this same account regains quota."""
        if self.current_email() != origin or not self.settings().get('task_continuation'):
            return False
        with self.lock:
            events = [p for p in self.pending if p.get('origin') == origin
                      and p.get('auto_enabled') and p.get('resume_enabled')]
            if not events:
                return False
            unique = {self._key(event): self._item(event) for event in events}
            now = time.time()
            self.sessions.append({'id': uuid.uuid4().hex, 'source': 'auto-recovered',
                                  'origin': origin, 'target': origin,
                                  'target_identity_key': self._target_identity(origin), 'phase': 'resuming',
                                  'created_at': now, 'updated_at': now,
                                  'switched_at': None, 'seen_at': None,
                                  'items': list(unique.values())})
            self.pending = [p for p in self.pending if p.get('origin') != origin]
            self._save()
        self.wake.set()
        return True

    def discard_origin(self, origin):
        """An account switched with continuation off; old limit events are obsolete."""
        with self.lock:
            self.pending = [p for p in self.pending if p.get('origin') != origin]
            self._save()

    def cancel_active(self):
        """Stop queued desktop actions when the user turns continuation off."""
        with self.lock:
            changed = False
            for session in self.sessions:
                if session.get('phase') not in ('switching', 'resuming'):
                    continue
                for item in session.get('items', []):
                    if item.get('state') not in TERMINAL:
                        item['state'] = 'skipped'
                        item['reason'] = 'continuation_disabled'
                session['phase'] = 'cancelled'
                session['updated_at'] = time.time()
                changed = True
            for item in self.pending:
                item['resume_enabled'] = False
            if changed or self.pending:
                self._save()

    def _queue_automatic_retry(self, session, item, reason, now, record=None):
        """Retry only a proven no-send failure or a confirmed terminal turn."""
        if task_metadata(self.paths.home, [item.get('thread_id')]).get(item.get('thread_id'), {}).get('kind') == 'subagent':
            return False
        delay = auto_retry_delay(reason, item.get('attempts'))
        if (delay is None or self.blocked or session.get('phase') == 'cancelled' or
                not self.settings().get('task_continuation') or
                self.current_email() != session.get('target')):
            return False
        observed = item.get('observed_turn_id')
        if reason in AUTO_RETRY_TURN_FAILURES:
            if (not THREAD_ID.fullmatch(str(observed)) or not record or
                    record.get('turn_id') != observed or record.get('status') != 'failed' or
                    turn_failure_reason(record.get('error')) != reason):
                return False
            latest = latest_turn(self.paths.home, item['thread_id'])
            if not latest or latest.get('turn_id') != observed:
                return False  # The user or another workflow already continued it.
            previous = item['turn_id']
            item['turn_id'] = observed
            item.pop('observed_turn_id', None)
            # Native Continue can fail on the same turn ID. The terminal
            # failure is explicit proof that a new attempt is now allowed.
            item['retry_authorized'] = observed == previous
        elif reason in AUTO_RETRY_PRE_DISPATCH:
            if observed:
                return False
            item['retry_authorized'] = True
        else:
            return False
        item.update(state='waiting', reason=reason, next_try=now + delay)
        session.update(phase='resuming', updated_at=now, seen_at=None)
        self.log.info('resume_retry_queued reason=%s attempts=%d delay=%d',
                      reason, item['attempts'], delay)
        return True

    def _ready(self):
        now = time.time()
        with self.lock:
            changed = False
            for session in self.sessions:
                for item in session['items']:
                    observed = item.get('observed_turn_id')
                    if item.get('reason') not in ('new_turn_observed', 'native_turn_resumed') or not observed:
                        continue
                    record = latest_turn(self.paths.home, item['thread_id'], observed)
                    if not record or record['turn_id'] != observed:
                        continue
                    if record['status'] == 'failed':
                        reason = turn_failure_reason(record.get('error'))
                        if not self._queue_automatic_retry(session, item, reason, now, record):
                            item.update(state='failed', reason=reason)
                            session.update(updated_at=now, seen_at=None)
                            if (session.get('phase') != 'cancelled' and
                                    all(i['state'] in TERMINAL for i in session['items'])):
                                session['phase'] = 'failed'
                            self.log.info('resume_followup_failed reason=%s', reason)
                        changed = True
                    elif record['status'] in ('completed', 'interrupted'):
                        item['reason'] = 'resumed_turn_completed' if record['status'] == 'completed' else 'resumed_turn_interrupted'
                        changed = True
            if changed:
                self._save()
            self._skip_subagent_work()
            if not self.settings().get('task_continuation') or self.desktop_transitioning():
                return None
            for session in self.sessions:
                if session.get('phase') != 'resuming':
                    continue
                if self.blocked:
                    self._fail_remaining(session, 'resume_state_unavailable')
                    self._save()
                    continue
                if self.current_email() != session.get('target'):
                    self._fail_remaining(session, 'account_changed')
                    self._save()
                    continue
                for item in session['items']:
                    if item['state'] == 'waiting' and item.get('next_try', 0) <= now:
                        claim = self._claim_key(item)
                        if (claim in self.claims and not item.get('retry_authorized')
                                and not self._claim_has_only_safe_failures(item)):
                            item.update(state='skipped', reason='duplicate_attempt')
                            self._save()
                            continue
                        # Durable before any desktop call. Clear/prune never clears
                        # claims; a crash, lost ACK or second session cannot replay it.
                        self.claims.add(claim)
                        item.update(state='acting', retry_authorized=False)
                        session['updated_at'] = now
                        self._save()
                        expected = session.get('target_identity_key') or self._target_identity(session.get('target'))
                        return session['id'], {**copy.deepcopy(item),
                            'settings_file': str(self.paths.data / 'state.json'),
                            'expected_account_key': expected}
                if session['items'] and all(i['state'] in TERMINAL for i in session['items']):
                    session['phase'] = ('failed' if any(i['state'] == 'failed'
                                                       for i in session['items']) else 'done')
                    session['updated_at'] = now
                    self._save()
        return None

    def _run(self):
        while not self.stop.is_set():
            try:
                ready = self._ready()
            except (OSError, ValueError):
                self.log.warning('resume_persist_failed')
                self.stop.wait(2)
                continue
            if not ready:
                self.wake.wait(2)
                self.wake.clear()
                continue
            session_id, item = ready
            with self.desktop_gate:
                with self.lock:
                    target = self._session(session_id)['target']
                if self.desktop_transitioning():
                    state, reason = 'defer', 'desktop_transitioning'
                elif not self.settings().get('task_continuation'):
                    state, reason = 'skipped', 'continuation_disabled'
                elif self.current_email() != target:
                    state, reason = 'failed', 'account_changed'
                else:
                    try:
                        state, reason = attempt_continuation(
                            self.paths.home, self.paths.desktop_resume_ps1, item, self.stop,
                            self.log)
                    except Exception as error:
                        self.log.warning('desktop_resume_error type=%s', type(error).__name__)
                        state, reason = 'failed', 'action_outcome_unknown'
            self._persist_outcome(session_id, item, state, reason)

    def _persist_outcome(self, session_id, item, state, reason):
        """Retry the journal commit, never repeat the desktop side effect.

        A disk failure leaves the previously committed `acting` entry intact.
        A restart then reports an uncertain result rather than replaying it.
        """
        while True:
            with self.lock:
                session = next((s for s in self.sessions if s['id'] == session_id), None)
                if session is None:
                    return
                live = next((i for i in session['items'] if self._key(i) == self._key(item)), None)
                if live is None or live['state'] == 'skipped':
                    return
                if state == 'defer' and reason == 'desktop_transitioning':
                    self.claims.discard(self._claim_key(live))
                    live.update(state='waiting', reason=reason, next_try=time.time() + 2)
                else:
                    live['attempts'] += 1
                    observed = item.get('observed_turn_id')
                    if isinstance(observed, str) and THREAD_ID.fullmatch(observed):
                        live['observed_turn_id'] = observed
                    live.update(state=state if state in TERMINAL else 'failed', reason=reason)
                    if state == 'failed':
                        record = (latest_turn(self.paths.home, live['thread_id'], observed)
                                  if reason in AUTO_RETRY_TURN_FAILURES and observed else None)
                        self._queue_automatic_retry(session, live, reason, time.time(), record)
                session['updated_at'] = time.time()
                if all(i['state'] in TERMINAL for i in session['items']):
                    session['phase'] = 'failed' if any(i['state'] == 'failed'
                                                      for i in session['items']) else 'done'
                try:
                    self._save()
                    return
                except (OSError, ValueError):
                    self.log.warning('resume_outcome_persist_failed')
            if self.stop.wait(2):
                return

    def summary(self):
        now = time.time()
        with self.lock:
            if self._prune():
                self._save()
            waiting = self._waiting_session()
            candidates = [s for s in reversed(self.sessions) if s.get('items')]
            candidates.sort(key=lambda s: s.get('phase') not in ('switching', 'resuming'))
            if waiting and not any(s.get('phase') in ('switching', 'resuming')
                                   for s in candidates):
                return {'id': waiting['id'], 'phase': 'waiting_account',
                        'done': 0, 'failed': 0, 'total': len(waiting['items'])}
            for session in candidates:
                if session.get('phase') == 'cancelled':
                    continue
                items = session.get('items', [])
                if not items:
                    continue
                active = session['phase'] in ('switching', 'resuming')
                failed = sum(i['state'] == 'failed' for i in items)
                if not active and (session.get('seen_at') or
                                   now - session.get('updated_at', now) >
                                   (FAILURE_BANNER_SECONDS if failed else 30)):
                    continue
                return {'id': session['id'], 'phase': session['phase'],
                        'done': sum(i['state'] == 'done' for i in items),

                        'failed': failed, 'attention': sum(i['state'] == 'failed' and i.get('reason') in ATTENTION_REASONS for i in items), 'total': len(items)}
        return None

    def _waiting_session(self):
        settings = self.settings()
        if not settings.get('auto_relay') or not settings.get('task_continuation'):
            return None
        origin = self.current_email()
        if origin in set(settings.get('auto_relay_excluded') or []):
            return None
        waiting = [p for p in self.pending if p.get('origin') == origin
                   and p.get('auto_enabled') and p.get('resume_enabled')]
        if not waiting:
            return None
        return {'id': 'waiting:' + origin, 'source': 'auto-limit',
                'origin': origin, 'target': None, 'phase': 'waiting_account',
                'created_at': min(p.get('created_at', time.time()) for p in waiting),
                'updated_at': max(p.get('created_at', 0) for p in waiting),
                'scheduled_at': min((p['scheduled_at'] for p in waiting
                                     if isinstance(p.get('scheduled_at'), (int, float))),
                                    default=None),
                'items': [self._item(p) for p in waiting]}

    def details(self):
        with self.lock:
            if self._prune():
                self._save()
            sessions = copy.deepcopy([s for s in self.sessions if s.get('items')])
            waiting = self._waiting_session()
            if waiting:
                sessions.append(waiting)
        ids = [item['thread_id'] for session in sessions for item in session.get('items', [])]
        metadata = task_metadata(self.paths.home, ids)
        parent_ids = [m['parent_id'] for m in metadata.values() if m.get('parent_id')]
        parents = task_metadata(self.paths.home, parent_ids) if parent_ids else {}
        for _ in range(8):
            ancestors = {m['parent_id'] for m in parents.values()
                         if m.get('kind') == 'subagent' and m.get('parent_id')} - parents.keys()
            if not ancestors:
                break
            parents.update(task_metadata(self.paths.home, ancestors))
        titles = title_prefixes(self.paths.home, ids)
        for session in sessions:
            for item in session.get('items', []):
                info = metadata.get(item['thread_id'], {})
                item['is_subagent'] = info.get('kind') == 'subagent'
                parent, visited = info.get('parent_id'), set()
                while parent and parent not in visited and parents.get(parent, {}).get('kind') == 'subagent':
                    visited.add(parent)
                    parent = parents[parent].get('parent_id')
                parent_info = parents.get(parent, {})
                item['parent_thread_id'] = parent_info.get('canonical_id') if parent_info.get('kind') == 'task' else None
                item['parent_title'] = parent_info.get('title') if item['parent_thread_id'] else None
                if item['is_subagent']:
                    agent = (info.get('agent_path') or '').rstrip('/').rsplit('/', 1)[-1]
                    item['title'] = '后台子任务' + ('：' + agent if agent else '')
                else:
                    item['title'] = info.get('title') or titles.get(item['thread_id']) or item['thread_id'][-8:]
                # Older versions stored every later turn failure under one
                # generic label. Reclassify the exact observed turn for display
                # without rewriting the durable history or replaying an action.
                if (item.get('state') == 'failed' and
                        item.get('reason') == 'resumed_turn_failed' and
                        THREAD_ID.fullmatch(str(item.get('observed_turn_id', '')))):
                    record = latest_turn(self.paths.home, item['thread_id'], item['observed_turn_id'])
                    if record and record.get('status') == 'failed':
                        item['reason'] = turn_failure_reason(record.get('error'))
        return sorted(sessions, key=lambda s: s.get('updated_at', 0), reverse=True)

    def clear_history(self):
        with self.lock:
            before = len(self.sessions)
            self.sessions = [s for s in self.sessions if s.get('phase') in ('switching', 'resuming')]
            removed = before - len(self.sessions)
            self._save()
        return {'ok': True, 'removed': removed}

    def mark_seen(self, session_id):
        with self.lock:
            if session_id.startswith('waiting:'):
                return {'ok': True}
            session = next((s for s in self.sessions if s.get('id') == session_id), None)
            if not session:
                return {'ok': False, 'error': '记录已过期'}
            if session['phase'] not in ('switching', 'resuming'):
                session['seen_at'] = time.time()
                self._save()
        return {'ok': True}

    def retry_task(self, session_id, thread_id):
        """Explicitly retry a safe pre-dispatch failure or a confirmed failed turn."""
        if task_metadata(self.paths.home, [thread_id]).get(thread_id, {}).get('kind') == 'subagent':
            return {'ok': False, 'error': '后台子任务不单独接续，请查看所属主任务'}
        with self.lock:
            if self.blocked:
                return {'ok': False, 'error': '接续记录无法验证，请先恢复记录备份'}
            session = next((s for s in self.sessions if s.get('id') == session_id), None)
            if not session or session.get('phase') != 'failed':
                return {'ok': False, 'error': '这次接续记录已变化'}
            item = next((i for i in session['items'] if i.get('thread_id') == thread_id
                         and i.get('state') == 'failed'), None)
            if not item:
                return {'ok': False, 'error': '该任务不能重试'}
            if not self.settings().get('task_continuation'):
                return {'ok': False, 'error': '请先开启自动接续任务'}
            if self.current_email() != session.get('target'):
                return {'ok': False, 'error': '请先切回接续时使用的账号'}
            reason = item.get('reason')
            observed = item.get('observed_turn_id')
            record = (latest_turn(self.paths.home, thread_id, observed)
                      if THREAD_ID.fullmatch(str(observed)) else None)
            if reason == 'resumed_turn_failed' and record and record.get('status') == 'failed':
                reason = turn_failure_reason(record.get('error'))
            if reason not in RETRYABLE_REASONS:
                return {'ok': False, 'error': '该任务不能重试'}
            if reason in AUTO_RETRY_TURN_FAILURES:
                current = latest_turn(self.paths.home, thread_id)
                if (not record or record.get('status') != 'failed' or
                        turn_failure_reason(record.get('error')) != reason or
                        not current or current.get('turn_id') != observed):
                    return {'ok': False, 'error': '原任务状态已变化，请打开原任务查看'}
                item['retry_authorized'] = True
                item['turn_id'] = observed
                item.pop('observed_turn_id', None)
                item['attempts'] = 0
            else:
                item['retry_authorized'] = True
            item.pop('deferred_since', None)
            item.update(state='waiting', next_try=0, reason='')
            session.update(phase='resuming', updated_at=time.time(), seen_at=None)
            self._save()
        self.wake.set()
        return {'ok': True}
