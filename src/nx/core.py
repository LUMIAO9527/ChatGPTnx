"""One operation coordinator; small stable bridge; no UI dependencies."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from datetime import date
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import re
import subprocess
import threading
import time
import uuid
import unicodedata
from .storage import Accounts, Paths, State, credential_metadata, identity, account_identity_key, activity_identity_key, claims
from .quota import Query
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
from .resume_flow import ResumeCoordinator

from .version import APP_VERSION
from .quota_policy import complete_windows, fresh_windows
from .settings import valid_setting
from .diagnostics import Diagnostics, query_summary


def relay_candidates(accounts, current, excluded=()):
    """One ordering for both the desktop decision and its UI."""
    now = time.time()
    def remaining(account, minutes):
        for window in account.get('windows', []):
            duration = window.get('duration_mins') or {'5h': 300, '周': 10080}.get(window.get('label'))
            if duration == minutes:
                return 100 - window.get('used') if isinstance(window.get('used'), (int, float)) else None
        return None

    def usable(account):
        return (fresh_windows(account, now)
                and all(w['used'] < 100 for w in account['windows']))

    excluded = set(excluded)
    candidates = [account for account in accounts if account.get('email') != current
                  and account.get('email') not in excluded and usable(account)]
    def rank(account):
        five, week = remaining(account, 300), remaining(account, 10080)
        windows = account['windows']
        floor = min(100 - window['used'] for window in windows)
        has_five = five is not None
        # Max-uptime tiers: healthy Plus first, healthy weekly-only accounts
        # as a reserve, then tight and emergency accounts.  The floor is the
        # actual bottleneck because using a Plus account consumes both windows.
        if has_five and floor >= 50:
            tier = 5
        elif has_five and floor >= 20:
            tier = 4
        elif not has_five and floor >= 20:
            tier = 3
        elif floor >= 5:
            tier = 2
        else:
            tier = 1
        limiting_resets = [window.get('resets_at') for window in windows
                           if 100 - window['used'] == floor and
                           isinstance(window.get('resets_at'), (int, float))]
        reset_rank = -min(limiting_resets) if limiting_resets else float('-inf')
        return (tier, floor, has_five, reset_rank,
                five if five is not None else -1,
                week if week is not None else -1)
    return sorted(candidates, key=rank, reverse=True)


def relay_candidate(accounts, current, picked=None):
    candidates = relay_candidates(accounts, current)
    return next((account for account in candidates if account.get('email') == picked),
                candidates[0] if candidates else None)

class Service:
    def __init__(self, paths: Paths, query=None, runner=None):
        self.paths, self.accounts, self.state = paths, Accounts(paths), State(paths)
        self.lock = threading.RLock()
        self.gate = threading.Lock()
        self.stop = threading.Event()
        self.listeners = []
        self.operation = None
        self.last_error = None
        self.last_result = None
        self.recent_results = []
        self.relay_pick = None  # one-shot UI choice; deliberately never persisted
        self._relay_wait_refresh_after = 0.0
        self._relay_wait_attempt_after = 0.0
        self.auto_relay_attempt = None
        self.auto_relay_retry_after = 0.0
        self.hotkey_status = {}
        self._cancel_event = None
        self.desktop_gate = threading.Lock()
        self.query = query or Query(paths, lambda: self.state.get('settings'))
        self.runner = runner or self._powershell
        self.log = logging.getLogger('chatgptnx.' + str(id(self)))
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        handler = RotatingFileHandler(paths.data / 'run.log', maxBytes=128 * 1024, backupCount=1, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        self.log.addHandler(handler)
        self.diagnostics = Diagnostics(self.log)
        if isinstance(self.query, Query):
            self.query.log = self.log
            removed, failed = self.query.cleanup_orphans()
            if removed or failed:
                self.log.info('query_orphan_cleanup removed=%d failed=%d', removed, failed)
        self.resumer = ResumeCoordinator(paths, self.accounts.current, self.stop, self.log,
                                         self.notify, self.desktop_gate,
                                         lambda: self.state.get('settings'),
                                         self.desktop_transitioning)
        from .early_anchor import EarlyAnchor
        self.early_anchor = EarlyAnchor(paths, self.accounts.current, self._record_anchor_limits,
                                       self._anchor_allowed)
        if self.state.recovery_path or self.resumer.recovery_path:
            self.last_error = {'id': uuid.uuid4().hex, 'kind': 'recovery', 'target': None,
                'message': '本地状态文件损坏，已保留原文件并恢复；请检查设置与接续记录',
                'created_at': time.time(), 'seen': False}
        self.log.info('service_started version=%s pid=%d', APP_VERSION, os.getpid())

    def _powershell(self, *args):
        neutral_cwd = os.environ.get('WINDIR') or os.environ.get('SystemRoot')
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                                 '-ExecutionPolicy', 'Bypass', '-File', str(self.paths.ps1),
                                 '-AuthFile', str(self.paths.auth),
                                 '-SnapshotDir', str(self.paths.snapshots), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=120, creationflags=NO_WINDOW, cwd=neutral_cwd)
        if result.returncode:
            # Never put raw stdout/stderr or credential contents in diagnostics.
            raise RuntimeError(f'本地账号操作失败（退出码 {result.returncode}）；原凭据已保留，请检查桌面端路径或文件占用')

    def notify(self):
        for listener in tuple(self.listeners):
            try:
                listener()
            except Exception:
                self.log.warning('listener_failed')

    def phase(self, message):
        with self.lock:
            if self.operation:
                self.operation['phase'] = message
        self.notify()

    def begin(self, kind, target, job, allow_adding=False, allow_reauth=False, refresh_after=False,
              background=False, interruptible=False, cancel_event=None, source=None, previous=None):
        if self.state.get('adding') and not allow_adding:
            return {'ok': False, 'error': '请先完成或取消添加账号'}
        if self.state.get('reauth') and not allow_reauth:
            return {'ok': False, 'error': '请先完成或取消重新登录'}
        if not self.gate.acquire(blocking=False):
            with self.lock:
                maintenance = bool(self.operation and (self.operation.get('background')
                                                        or self.operation.get('interruptible')))
                if maintenance and self._cancel_event:
                    self._cancel_event.set()
            # A foreground click may arrive just after show() asked automatic
            # maintenance to stop. Waiting here blocks only the bridge worker,
            # never the WebView UI thread, and makes that click deterministic.
            if background or not maintenance or not self.gate.acquire(timeout=2.5):
                return {'ok': False, 'error': '当前操作尚未完成'}
        # Recheck after acquiring the gate: another workflow may have started
        # while this request was waiting for interruptible maintenance.
        if self.stop.is_set() or (self.state.get('adding') and not allow_adding) or (self.state.get('reauth') and not allow_reauth):
            self.gate.release()
            return {'ok': False, 'error': '状态已变化，请重新打开操作页'}
        ident = uuid.uuid4().hex
        cancel_event = cancel_event or threading.Event()
        started_at = time.time()
        with self.lock:
            self.operation = {'id': ident, 'kind': kind, 'target': target, 'phase': '准备中',
                              'started_at': started_at, 'background': bool(background),
                              'interruptible': bool(interruptible), 'source': source,
                              'previous': previous}
            self._cancel_event = cancel_event
            self.last_error = None
            # Keep the last terminal result while a follow-up refresh runs.
        self.notify()

        def work():
            try:
                job()
                with self.lock:
                    self.last_result = {'id': ident, 'kind': kind, 'target': target, 'ok': True,
                                        'source': source, 'previous': previous,
                                        'resume_session_id': self.operation.get('resume_session_id'),
                                        'started_at': started_at, 'finished_at': time.time()}
                    if source in ('auto', 'auto-limit'):
                        self.auto_relay_retry_after = 0.0
                if refresh_after and not self.stop.is_set():
                    self.phase('更新当前账号额度')
                    try:
                        self._refresh(self.accounts.current(), cancel_event)
                    except Exception as error:
                        # The account transaction is already committed. A quota
                        # read failure must not trigger another account switch.
                        self.log.warning('post_commit_refresh_failed type=%s', type(error).__name__)
                        with self.lock:
                            self.last_error = {'id': ident, 'kind': 'refresh', 'target': target,
                                'message': '账号操作已完成，额度更新失败；可单独刷新额度',
                                'created_at': time.time(), 'seen': False}
                self.log.info('operation_completed kind=%s source=%s', kind, source or 'direct')
            except Exception as error:
                self.diagnostics.operation_failed(kind, error)
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '操作失败；原数据未被主动删除，请重试'
                with self.lock:
                    self.last_error = {'id': ident, 'kind': kind, 'target': target, 'message': message[:180], 'created_at': time.time(), 'seen': False}
                    self.last_result = {'id': ident, 'kind': kind, 'target': target, 'ok': False,
                                        'source': source, 'previous': previous,
                                        'resume_session_id': self.operation.get('resume_session_id'),
                                        'started_at': started_at, 'finished_at': time.time()}
                    if source in ('auto', 'auto-limit'):
                        self.auto_relay_retry_after = time.monotonic() + 15
                self.log.warning('operation_failed kind=%s source=%s type=%s',
                                 kind, source or 'direct', type(error).__name__)
            finally:
                with self.lock:
                    if self.last_result and self.last_result['id'] == ident:
                        self.recent_results = (self.recent_results + [copy.deepcopy(self.last_result)])[-8:]
                    self.operation = None
                    self._cancel_event = None
                self.gate.release()
                self.notify()
        threading.Thread(target=work, daemon=True, name='nx-' + kind).start()
        return {'ok': True, 'accepted': True, 'operation_id': ident, 'source': source}

    def get_data(self):
        cache = self.state.get('cache')
        meta = self.state.get('account_meta', {})
        emails = self.accounts.all()
        indexed = {a['email']: a for a in cache.get('accounts', [])}
        accounts = []
        current_email = self.accounts.current()
        subscriptions = self.state.get('subscriptions', {})
        for email in emails:
            item = copy.deepcopy(indexed.get(email, {'email': email, 'ok': False, 'err': '等待首次查询', 'windows': [], 'plan': 'unknown'}))
            if isinstance(self.query, Query):
                policy = self.query.status(email, email == current_email)
                if not policy.get('ready', True):
                    from .diagnostics_http import message
                    item.update(policy, ok=False, err=message(policy.get('error_code')))
            item['alias'] = meta.get(email, {}).get('alias', '')
            auth_path = self.paths.auth if current_email == email else self.paths.snapshot(email)
            item['identity_key'] = account_identity_key(auth_path, email)
            item['activity_key'] = activity_identity_key(auth_path, email)
            from .subscription import from_credential
            subscription = subscriptions.get(email)
            if not subscription or subscription.get('identity_key') != item['identity_key']:
                subscription = from_credential(auth_path)
            item['membership'] = subscription
            item['manual_subscription_date'] = meta.get(email, {}).get('subscription_date')
            accounts.append(item)
        with self.lock:
            raw_op = copy.deepcopy(self.operation)
        op = None if raw_op and raw_op.get('background') else raw_op
        try:
            from .desktop import chatgpt_running
            app_running = chatgpt_running()
        except Exception:
            app_running = True
        # Onboarding hint: an account is logged into the desktop app but the
        # roster is still empty (or does not contain it yet).
        pending = None
        if not emails:
            logged_in = identity(self.paths.auth)[0]
            if logged_in:
                pending = logged_in
        hotkeys = self.resolved_hotkeys(emails)
        add_state = self.state.get('adding')
        add_login_status = self._add_login_status(add_state, emails)
        settings = self.state.get('settings')
        settings['relay_pick'] = self.relay_pick if self.relay_pick in emails else None
        excluded = set(settings.get('auto_relay_excluded') or [])
        ranked_all = relay_candidates(accounts, None)
        ranked = [a for a in ranked_all if a['email'] != current_email]
        ranked_auto = [a for a in ranked if a['email'] not in excluded]
        recommended = next((a for a in ranked if a['email'] == settings['relay_pick']),
                           ranked[0] if ranked else None)
        return {'version': APP_VERSION, 'updated': cache.get('updated'), 'accounts': accounts,
                'monitor_health': self.diagnostics.snapshot()['monitor'],
                'current': current_email, 'operation': op,
                'switching': op['target'] if op and op['kind'] == 'switch' else None,
                'refreshing': bool(op and op['kind'] == 'refresh'),
                'background_refreshing': bool(raw_op and raw_op.get('background')),
                'adding': bool(add_state), 'add_state': add_state,
                'add_login_status': add_login_status,
                'reauth': self.state.get('reauth'),
                'last_error': self.visible_error(), 'last_result': copy.deepcopy(self.last_result),
                'recent_results': copy.deepcopy(self.recent_results),
                'hotkeys': [{'email': email, 'shortcut': hotkeys.get(email),
                             'registered': self.hotkey_status.get(email)} for email in emails],
                'settings': settings, 'relay_wait': self.state.get('relay_wait'),
                'relay_email': recommended.get('email') if recommended else None,
                'auto_relay_email': ranked_auto[0]['email'] if ranked_auto and current_email not in excluded else None,
                'relay_order': [a['email'] for a in ranked_all],
                'chatgpt_running': app_running,
                'pending': pending,
                'usage_revision': self.state.get('usage_revision', 0),
                'resume': self.resumer.summary()}

    def get_diagnostics(self):
        """Preview only: creates no file and never reads credential/log bodies."""
        data = self.get_data()
        result = {'version': APP_VERSION, 'generated_at': int(time.time()),
                  'auto_relay': data['settings']['auto_relay'],
                  'task_continuation': data['settings']['task_continuation'],
                  **self.diagnostics.snapshot(),
                  'accounts': [query_summary(a, i + 1) for i, a in enumerate(data['accounts'])]}
        return {'ok': True, 'text': json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)}

    def retry_query(self, email):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        def work():
            if isinstance(self.query, Query):
                if not self.query.resume(email):
                    raise RuntimeError('查询仍暂停，请检查保护状态、登录状态或等待冷却结束')
            self._refresh(email)
        return self.begin('refresh', email, work, interruptible=True)

    def _query_ready(self, email, current):
        return not isinstance(self.query, Query) or self.query.ready(email, email == current)

    def visible_error(self):
        with self.lock:
            error = self.last_error
            if not error or error.get('seen') or time.time() - error.get('created_at', time.time()) >= 86400:
                return None
            return copy.deepcopy(error)

    def dismiss_error(self, error_id):
        with self.lock:
            if self.last_error and self.last_error.get('id') == error_id:
                self.last_error['seen'] = True
        self.notify()
        return {'ok': True}

    def get_resume_details(self):
        return self.resumer.details()

    def clear_resume_history(self):
        return self.resumer.clear_history()

    def mark_resume_seen(self, session_id):
        return self.resumer.mark_seen(session_id)

    def retry_resume_task(self, session_id, thread_id):
        if self.desktop_transitioning():
            return {'ok': False, 'error': '账号操作尚未完成，请稍后重试'}
        return self.resumer.retry_task(session_id, thread_id)

    def desktop_transitioning(self):
        operation = self.operation
        return bool(self.state.get('adding') or self.state.get('reauth') or
                    operation and operation['kind'] in
                    ('switch', 'add_start', 'add_cancel', 'add_finish', 'adopt',
                     'reauth_start', 'reauth_cancel', 'reauth_finish'))

    def _serialize_desktop(self, work):
        with self.desktop_gate:
            work()

    def _add_login_status(self, pending=None, emails=None):
        """Describe the external desktop login without persisting its identity."""
        pending = self.state.get('adding') if pending is None else pending
        if not pending or pending.get('phase') != 'login':
            return 'inactive'
        email, account_id = identity(self.paths.auth)
        if not email or not account_id:
            return 'waiting'
        if email == pending.get('previous'):
            return 'unchanged'
        if email in (emails if emails is not None else self.accounts.all()):
            return 'existing'
        return 'ready'

    def _record_current(self):
        cache = self.state.get('cache')
        cache['current'] = self.accounts.current()
        self.state.update(cache=cache)

    def _refresh(self, targets=None, cancel=None):
        emails = self.accounts.all()
        current = self.accounts.current()
        if targets is None:
            targets = ([current] if current in emails else []) + [email for email in emails if email != current]
        elif isinstance(targets, str):
            targets = [targets]
        else:
            targets = list(dict.fromkeys(email for email in targets if email in emails))
        previous = self.state.get('cache')
        indexed = {a['email']: a for a in previous.get('accounts', [])}
        settings = self.state.get('settings')
        count = 0
        results = {}
        with ThreadPoolExecutor(max_workers=min(2, max(1, int(settings['query_workers'])))) as pool:
            futures = {pool.submit(self.query.run, email, email == current, cancel=cancel): email for email in targets}
            for future in as_completed(futures):
                if cancel and cancel.is_set():
                    continue
                email = futures[future]
                try:
                    result = future.result()
                except Exception:
                    result = {'email': email, 'ok': False, 'err': '查询失败', 'error_code': 'unexpected'}
                if not result.get('ok'):
                    old = indexed.get(email, {})
                    result = {**old, **result, 'fetched_at': old.get('fetched_at'),
                              'attempted_at': int(time.time())}
                result.update(credential_metadata(self.paths.auth if email == current else self.paths.snapshot(email)))
                indexed[email] = result
                results[email] = copy.deepcopy(result)
                count += 1
                self.phase(f'正在刷新 {count}/{len(targets)}')
                # Progressive per-account timestamps, not a misleading global timestamp.
                self.state.update(cache={'updated': previous.get('updated'), 'current': current,
                                         'accounts': [indexed[e] for e in emails if e in indexed]})
                self.notify()
        full = set(targets) == set(emails) and len(results) == len(targets) and not (cancel and cancel.is_set())
        self.state.update(cache={'updated': int(time.time()) if full else previous.get('updated'),
                                 'current': current, 'accounts': [indexed[e] for e in emails if e in indexed]})
        if current in targets and self.resumer.has_limit_origin(current):
            self.resumer.defer_limit(current, 0, refreshed=True)
        return results

    def refresh(self, email=None, background=False):
        """The home refresh updates the whole roster, current account first.
        Account detail refresh remains deliberately scoped to that account."""
        if email is not None and email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        targets = email
        if background:
            current = self.accounts.current()
            targets = [e for e in ([email] if email else self.accounts.all())
                       if self._query_ready(e, current)]
            if not targets:
                return {'ok': True, 'accepted': False, 'reason': 'query_paused'}
        cancel = threading.Event()
        return self.begin('refresh', email, lambda: self._refresh(targets, cancel),
                          background=background, interruptible=True, cancel_event=cancel)

    def switch(self, email):
        return self._switch(email, 'manual')

    def _switch(self, email, source, exhaustion_key=None, failure_events=(), relay_wait_id=None):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不在清单中'}
        if self.accounts.current() == email:
            self._record_current()
            return {'ok': True, 'accepted': False, 'already_current': True}
        previous = self.accounts.current()
        cancel = threading.Event()
        def work():
            # Validate the target online without refreshing its credentials.
            # A locally correct identity may still have been revoked; never
            # switch away from the current desktop session in that case.
            self.phase('验证目标账号登录状态')
            results = self._refresh(email, cancel)
            target = results.get(email) or {}
            if target.get('error_code') == 'reauth_required':
                self.state.update(reauth={'email': email, 'previous': previous, 'phase': 'ready'})
                raise RuntimeError('目标账号需要重新登录；当前账号没有切换')
            if not target.get('ok'):
                raise RuntimeError('目标账号在线状态尚未确认；当前账号没有切换')
            warning = target.get('query_warning') or {}
            if ((warning.get('scope') != 'reset_credits' and
                    (warning.get('paused') or (warning.get('retry_at') or 0) > time.time()))
                    or not self._query_ready(email, previous)):
                raise RuntimeError('目标账号查询已暂停；当前账号没有切换')
            if self.stop.is_set() or cancel.is_set():
                raise RuntimeError('操作已取消；当前账号没有切换')
            if source in ('auto', 'auto-limit'):
                if not self.state.get('settings').get('auto_relay'):
                    raise RuntimeError('自动接力已关闭；当前账号没有切换')
                excluded = set(self.state.get('settings').get('auto_relay_excluded') or [])
                if previous in excluded or email in excluded:
                    raise RuntimeError('账号已退出自动接力；当前账号没有切换')
            if source in ('relay', 'recovery', 'auto', 'auto-limit') and not relay_candidates([target], None):
                raise RuntimeError('目标账号额度已耗尽；当前账号没有切换')
            # One gate serializes desktop continuation and account replacement.
            # Snapshot after preflight, as close to stopping ChatGPT as possible.
            with self.desktop_gate:
                if self.accounts.current() != previous:
                    raise RuntimeError('预检期间当前账号已变化；没有切换')
                continuation = self.state.get('settings')['task_continuation']
                if continuation:
                    from .desktop_resume import active_turns
                    interrupted = active_turns(self.paths.home)
                    session_id = self.resumer.prepare(previous, email, source, interrupted,
                                                      failure_events)
                    with self.lock:
                        self.operation['resume_session_id'] = session_id
                else:
                    session_id = None
                try:
                    if relay_wait_id:
                        # Cancellation remains effective during online preflight.
                        # Consume the one-shot request atomically at the switch boundary.
                        with self.lock:
                            waiting = self.state.get('relay_wait')
                            if (not waiting or waiting['id'] != relay_wait_id
                                    or waiting['email'] != email or waiting['origin'] != previous):
                                raise RuntimeError('恢复后接力已取消；当前账号没有切换')
                            self.state.update(relay_wait=None)
                    self.phase('保存当前账号 · 本地切换')
                    self.runner('-To', email)
                    self.phase('核验本地凭据')
                    if self.accounts.current() != email:
                        raise RuntimeError('切换后账号身份未匹配；没有标记为成功')
                    self._record_current()
                except Exception:
                    if session_id:
                        if self.accounts.current() == email:
                            self.resumer.switched(session_id)
                        else:
                            self.resumer.switch_failed(session_id)
                    raise
                if session_id:
                    self.resumer.switched(session_id)
                else:
                    self.resumer.discard_origin(previous)
            if source == 'auto' and exhaustion_key:
                self.auto_relay_attempt = exhaustion_key
        result = self.begin('switch', email, work, cancel_event=cancel,
                            source=source, previous=previous)
        if result.get('accepted'):
            with self.lock:
                self.relay_pick = None
                if not relay_wait_id:
                    self.state.update(relay_wait=None)
            self.notify()
        return result

    def relay(self, email=None, source='relay'):
        """A deliberate relay action, kept distinct from a manual account switch."""
        data = self.get_data()
        target = email or data.get('relay_email')
        if not target or target != data.get('relay_email'):
            return {'ok': False, 'error': '下一棒已变化，请重新打开面板'}
        return self._switch(target, source)

    def relay_when_recovered(self):
        """Honor one explicit recovery request, independently of automatic rotation."""
        waiting = self.state.get('relay_wait')
        if not waiting:
            return {'ok': True, 'accepted': False, 'reason': 'no_request'}
        data = self.get_data()
        target = next((a for a in data['accounts'] if a['email'] == waiting['email']), None)
        if data.get('current') != waiting['origin'] or not target:
            with self.lock:
                self.state.change('relay_wait', lambda value:
                    None if value and value['id'] == waiting['id'] else value)
            self.notify()
            return {'ok': True, 'accepted': False, 'reason': 'request_obsolete'}
        if (self.operation or data.get('adding') or data.get('reauth')
                or data.get('chatgpt_running') is False or self.stop.is_set()):
            return {'ok': True, 'accepted': False, 'reason': 'busy'}
        if not self._query_ready(waiting['email'], data['current']):
            return {'ok': True, 'accepted': False, 'reason': 'query_paused'}
        if not relay_candidates([target], None):
            if (not fresh_windows(target) and
                    time.monotonic() >= self._relay_wait_refresh_after):
                self._relay_wait_refresh_after = time.monotonic() + 60
                result = self.refresh(waiting['email'], background=True)
                return {'ok': True, 'accepted': False, 'reason':
                        'refreshing' if result.get('accepted') else 'waiting'}
            return {'ok': True, 'accepted': False, 'reason': 'waiting'}
        if time.monotonic() < self._relay_wait_attempt_after:
            return {'ok': True, 'accepted': False, 'reason': 'cooldown'}
        self._relay_wait_attempt_after = time.monotonic() + 60
        return self._switch(waiting['email'], 'recovery', relay_wait_id=waiting['id'])

    def auto_relay_if_needed(self):
        """Start one automatic relay for one exhausted quota window.

        The caller owns deduplication across repeated UI/tray refreshes.  This
        method deliberately requires fresh, complete quota data and never
        treats missing data as exhausted.
        """
        data = self.get_data()
        settings = data.get('settings') or {}
        if (not settings.get('auto_relay') or self.operation or data.get('adding')
                or data.get('reauth')):
            return {'ok': True, 'accepted': False, 'reason': 'disabled_or_busy'}
        if time.monotonic() < self.auto_relay_retry_after:
            return {'ok': True, 'accepted': False, 'reason': 'cooldown'}
        if self.refresh_stale_relay_accounts(data):
            return {'ok': True, 'accepted': False, 'reason': 'refreshing_candidates'}
        account = next((a for a in data['accounts'] if a['email'] == data.get('current')), None)
        if data.get('current') in set(settings.get('auto_relay_excluded') or []):
            return {'ok': True, 'accepted': False, 'reason': 'excluded'}
        if not account or not account.get('ok') or not account.get('windows'):
            return {'ok': True, 'accepted': False, 'reason': 'quota_unavailable'}
        now = time.time()
        if not fresh_windows(account, now):
            return {'ok': True, 'accepted': False, 'reason': 'quota_stale'}
        exhausted = [w for w in account['windows']
                     if w['used'] >= 100]
        if not exhausted:
            return {'ok': True, 'accepted': False, 'reason': 'not_exhausted'}
        target = data.get('auto_relay_email')
        if not target:
            return {'ok': True, 'accepted': False, 'reason': 'no_candidate'}
        exhaustion_key = (data['current'], tuple(sorted(
            (str(w.get('label')), int(w.get('resets_at'))) for w in exhausted)))
        if exhaustion_key == self.auto_relay_attempt:
            return {'ok': True, 'accepted': False, 'reason': 'already_attempted'}
        result = self._switch(target, 'auto', exhaustion_key=exhaustion_key)
        if result.get('accepted'):
            result['exhaustion_key'] = exhaustion_key
        return result

    def refresh_stale_relay_accounts(self, data):
        """Refresh stale eligible accounts once, then let normal selection rerun."""
        if self.operation or data.get('adding') or data.get('reauth'):
            return False
        excluded = set((data.get('settings') or {}).get('auto_relay_excluded') or [])
        now = time.time()
        targets = [a['email'] for a in data.get('accounts', [])
                   if a['email'] not in excluded and not fresh_windows(a, now)
                   and self._query_ready(a['email'], data.get('current'))]
        if not targets:
            return False
        # Failed requests must not create a refresh storm on every UI update.
        if time.monotonic() < getattr(self, '_relay_refresh_after', 0):
            return False
        self._relay_refresh_after = time.monotonic() + 60
        cancel = threading.Event()
        result = self.begin('refresh', None, lambda: self._refresh(targets, cancel),
                            background=True, interruptible=True, cancel_event=cancel)
        return bool(result.get('accepted'))

    def auto_relay_on_usage_limit(self, observed_current, events=()):
        """Relay on an exact task limit error even while quota cache is stale."""
        data = self.get_data()
        settings = data.get('settings') or {}
        if not settings.get('auto_relay'):
            return {'ok': True, 'accepted': False, 'reason': 'disabled'}
        if self.operation or data.get('adding') or data.get('reauth'):
            return {'ok': True, 'accepted': False, 'reason': 'busy'}
        if not observed_current or data.get('current') != observed_current:
            return {'ok': True, 'accepted': False, 'reason': 'current_changed'}
        if observed_current in set(settings.get('auto_relay_excluded') or []):
            return {'ok': True, 'accepted': False, 'reason': 'excluded'}
        if time.monotonic() < self.auto_relay_retry_after:
            return {'ok': True, 'accepted': False, 'reason': 'cooldown'}
        account = next((a for a in data['accounts'] if a['email'] == observed_current), None)
        target = data.get('auto_relay_email')
        if target:
            result = self._switch(target, 'auto-limit', failure_events=events)
            if result.get('accepted'):
                self.log.info('auto_relay_limit_event')
            return result
        reset_confirmed = bool(events and all(
            event.get('refreshed') and
            isinstance(event.get('account_reset_at'), (int, float)) and
            event['account_reset_at'] <= time.time() and
            isinstance((account or {}).get('fetched_at'), (int, float)) and
            account['fetched_at'] >= int(event.get('created_at', 0))
            for event in events))
        if reset_confirmed and account and relay_candidates([account], None):
            if settings.get('task_continuation') and self.resumer.recover_current(observed_current):
                self.log.info('auto_relay_current_recovered')
                return {'ok': True, 'accepted': True, 'recovered_current': True}
            self.resumer.discard_origin(observed_current)
            return {'ok': True, 'accepted': False, 'reason': 'current_recovered'}
        return {'ok': True, 'accepted': False, 'reason': 'no_candidate'}

    @staticmethod
    def _next_relay_reset_at(accounts, excluded=(), now=None):
        """Earliest known time when every exhausted window of one account resets."""
        now = time.time() if now is None else now
        resets = []
        def timestamp(value):
            return value if (isinstance(value, (int, float)) and
                             not isinstance(value, bool) and math.isfinite(value)) else 0
        for account in accounts:
            if account.get('email') in excluded:
                continue
            exhausted = [window for window in account.get('windows') or []
                         if isinstance(window.get('used'), (int, float))
                         and not isinstance(window['used'], bool) and window['used'] >= 100]
            if not exhausted or any(
                    not isinstance(window.get('resets_at'), (int, float)) or
                    isinstance(window['resets_at'], bool) or
                    not math.isfinite(window['resets_at']) for window in exhausted):
                continue
            reset_at = max(window['resets_at'] for window in exhausted)
            checked_at = max(timestamp(account.get('fetched_at')),
                             timestamp(account.get('attempted_at')))
            if reset_at > now:
                resets.append(reset_at)
            elif checked_at < reset_at:
                resets.append(now)
        return min(resets) if resets else None

    def reauth_start(self, email):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不在清单中'}
        pending = self.state.get('reauth')
        if pending and (pending.get('email') != email or pending.get('phase') != 'ready'):
            return {'ok': False, 'error': '已在重新登录流程中'}
        previous = pending.get('previous') if pending else self.accounts.current()
        expected_email, expected_id = identity(self.paths.snapshot(email))
        if not expected_email or not expected_id:
            return {'ok': False, 'error': '账号快照不完整，无法安全重新登录'}
        def work():
            self.state.update(reauth={'email': email, 'previous': previous, 'phase': 'parking'})
            self.phase('保存当前账号 · 打开登录窗口')
            try:
                # Reuse the add-account transaction: preserve the current
                # snapshot, remove only live auth, then open a clean login.
                self.runner('-Park')
                self.state.update(reauth={'email': email, 'previous': previous, 'phase': 'login'})
                self._record_current()
            except Exception:
                self.state.update(reauth={'email': email, 'previous': previous,
                                          'phase': 'needs_recovery'})
                raise
        return self.begin('reauth_start', email,
                          lambda: self._serialize_desktop(work), allow_reauth=True)

    def reauth_cancel(self):
        pending = self.state.get('reauth')
        if not pending:
            return {'ok': True, 'accepted': False}
        if pending.get('phase') == 'ready':
            self.state.update(reauth=None)
            self.notify()
            return {'ok': True, 'accepted': False}
        def work():
            self.phase('恢复重新登录前的账号')
            previous = pending.get('previous')
            if previous:
                self.runner('-To', previous)
                if self.accounts.current() != previous:
                    raise RuntimeError('尚未恢复原账号；重新登录流程已保留')
            self.state.update(reauth=None)
            self._record_current()
        return self.begin('reauth_cancel', pending.get('email'),
                          lambda: self._serialize_desktop(work), allow_reauth=True)

    def reauth_finish(self):
        pending = self.state.get('reauth')
        if not pending:
            return {'ok': False, 'error': '请先开始重新登录'}
        if pending.get('phase') != 'login':
            return {'ok': False, 'error': '登录窗口尚未准备完成'}
        target = pending.get('email')
        expected = identity(self.paths.snapshot(target))
        def work():
            actual = identity(self.paths.auth)
            if not actual[0] or not actual[1]:
                raise RuntimeError('尚未完成登录；请先在 ChatGPT 中继续')
            if actual != expected:
                raise RuntimeError('登录的不是待修复账号；不会覆盖原账号快照')
            self.phase('验证新的登录状态')
            results = self._refresh(target)
            checked = results.get(target) or {}
            if not checked.get('ok'):
                raise RuntimeError('新的登录状态尚未通过验证；请确认 ChatGPT 已完成登录')
            self.runner('-Snapshot')
            self.state.update(reauth=None)
            self._record_current()
        return self.begin('reauth_finish', target,
                          lambda: self._serialize_desktop(work), allow_reauth=True)

    def add_start(self):
        if self.state.get('adding'):
            return {'ok': False, 'error': '已在添加流程中'}
        previous = identity(self.paths.auth)[0]
        def work():
            self.state.update(adding={'previous': previous, 'phase': 'parking'})
            self.phase('保存当前账号 · 打开登录窗口')
            try:
                self.runner('-Park')
                self.state.update(adding={'previous': previous, 'phase': 'login'})
                self._record_current()
            except Exception:
                self.state.update(adding={'previous': previous, 'phase': 'needs_recovery'})
                raise
        return self.begin('add_start', None, lambda: self._serialize_desktop(work))

    def adopt_current(self):
        """Onboarding: save the account currently logged into the ChatGPT
        desktop app as the first (or an extra) roster entry. Unlike add_start
        there is no previous account to park - nothing is at risk."""
        email, account_id = identity(self.paths.auth)
        if not email or not account_id:
            return {'ok': False, 'error': '桌面端尚未登录；请先在 ChatGPT 桌面端完成登录'}
        if email in self.accounts.all():
            return {'ok': False, 'error': '这个账号已经在清单里'}
        def work():
            self.phase('保存当前登录的账号')
            self.runner('-Snapshot')
            self.accounts.activate(email)
            self._record_current()
        return self.begin('adopt', email, lambda: self._serialize_desktop(work),
                          refresh_after=True)

    def add_cancel(self):
        pending = self.state.get('adding')
        if not pending:
            return {'ok': True, 'accepted': False}
        def work():
            self.phase('恢复添加前的账号')
            if pending.get('previous'):
                self.runner('-To', pending['previous'])
                if identity(self.paths.auth)[0] != pending['previous']:
                    raise RuntimeError('尚未恢复原账号；请保留添加流程并重试取消')
            self.state.update(adding=None)
            self._record_current()
        return self.begin('add_cancel', None, lambda: self._serialize_desktop(work),
                          allow_adding=True, refresh_after=True)

    def add_finish(self):
        pending = self.state.get('adding')
        if not pending:
            return {'ok': False, 'error': '请先开始添加账号'}
        if pending.get('phase') != 'login':
            return {'ok': False, 'error': '登录窗口尚未准备完成，请先恢复原账号'}
        status = self._add_login_status(pending)
        if status == 'waiting':
            return {'ok': False, 'error': '尚未检测到完整登录，请先在 ChatGPT 中完成登录'}
        if status == 'unchanged':
            return {'ok': False, 'error': '当前仍是添加前的账号，请先登录新账号'}
        if status == 'existing':
            return {'ok': False, 'error': '这个账号已经在清单里，无需重复添加'}
        def work():
            email, account_id = identity(self.paths.auth)
            if not email or not account_id:
                raise RuntimeError('未读取到完整登录凭据，请先在桌面端完成登录')
            self.phase('保存新账号快照')
            self.runner('-Snapshot')
            self.accounts.activate(email)
            self.state.update(adding=None)
            self._record_current()
        return self.begin('add_finish', None, lambda: self._serialize_desktop(work),
                          allow_adding=True, refresh_after=True)

    def remove(self, email):
        def work():
            self.accounts.archive(email)
            self._record_current()
        return self.begin('remove', email, work)

    def restore(self, key):
        return self.begin('restore', None, lambda: self.accounts.restore(key), refresh_after=True)

    def get_archives(self):
        return self.accounts.archived()

    def _load_usage(self, targets, cancel=None):
        current = self.accounts.current()
        def query(email):
            value = self.query.run(email, email == current, usage=True, cancel=cancel)
            value['identity_key'] = account_identity_key(self.paths.auth if email == current else self.paths.snapshot(email), email)
            value['attempted_at'] = int(time.time())
            return value
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(query, email): email for email in targets}
            for index, task in enumerate(as_completed(pending), 1):
                if cancel and cancel.is_set():
                    continue
                email = pending[task]
                try:
                    value = task.result()
                except Exception:
                    value = {'ok': False, 'err': '用量查询失败', 'attempted_at': int(time.time())}
                items = self.state.get('usage')
                # A failed retry must not blank a previously valid dashboard.
                if not value.get('ok') and items.get(email, {}).get('ok'):
                    old = items[email]
                    value = {**old, 'attempted_at': value.get('attempted_at', int(time.time())),
                             'last_attempt_error': value.get('err') or '用量查询失败'}
                items[email] = value
                revision = int(self.state.get('usage_revision', 0) or 0) + 1
                self.state.update(usage=items, usage_revision=revision)
                self.phase(f'读取用量 {index}/{len(targets)}')
                self.notify()

    def get_usage(self, email, force=False):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        previous = self.state.get('usage').get(email)
        key = account_identity_key(self.paths.auth if self.accounts.current() == email else self.paths.snapshot(email), email)
        if (not force and previous and previous.get('identity_key') == key
                and 0 <= time.time() - previous.get('fetched_at', previous.get('attempted_at', 0)) < 600):
            return previous
        cancel = threading.Event()
        accepted = self.begin('usage', email, lambda: self._load_usage([email], cancel),
                              interruptible=True, cancel_event=cancel)
        return {**accepted, 'cached': previous}

    def read_usage(self, email):
        return self.state.get('usage').get(email)

    def read_usage_all(self, days=30):
        from .usage import aggregate
        accounts = self.get_data()['accounts']
        meta = self.state.get('account_meta', {})
        archived_emails = set()
        for archived in self.accounts.archived():
            email = archived['email']
            if email.casefold() in archived_emails:
                continue
            archived_emails.add(email.casefold())
            path = self.paths.snapshots / 'removed' / archived['key']
            archived_auth = claims(path).get('https://api.openai.com/auth') or {}
            archived_plan = archived_auth.get('chatgpt_plan_type') if isinstance(archived_auth, dict) else None
            accounts.append({'email': email, 'alias': meta.get(email, {}).get('alias', ''),
                             'plan': archived_plan if isinstance(archived_plan, str) else 'unknown', 'archived': True,
                             'identity_key': account_identity_key(path, email),
                             'activity_key': activity_identity_key(path, email)})
        return aggregate(accounts, self.state.get('usage'), days=days)

    def get_usage_all(self, force=False):
        cache = self.state.get('usage')
        targets = []
        for account in self.get_data()['accounts']:
            email = account['email']
            old = cache.get(email) or {}
            age = time.time() - old.get('fetched_at', old.get('attempted_at', 0))
            # 10 minutes, not an hour: opening the usage page should refresh in
            # the background reasonably often, while repeated opens stay cheap
            # and always render the persisted state.json data first.
            if force or not old or old.get('identity_key') != account['identity_key'] or not 0 <= age < 600:
                targets.append(email)
        if not targets:
            return {'ok': True, 'accepted': False}
        current = self.accounts.current()
        targets.sort(key=lambda value: value != current)
        cancel = threading.Event()
        return self.begin('usage', None, lambda: self._load_usage(targets, cancel),
                          interruptible=True, cancel_event=cancel)

    def get_subscription(self, email, force=False):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        previous = self.state.get('subscriptions').get(email)
        current = self.accounts.current()
        auth_path = self.paths.auth if current == email else self.paths.snapshot(email)
        key = account_identity_key(auth_path, email)
        if (not force and previous and previous.get('identity_key') == key
                and 0 <= time.time() - (previous.get('checked_at') or 0) < 21600):
            return {'ok': True, 'accepted': False, 'subscription': previous}
        def work():
            from .subscription import from_credential
            self.phase('自动读取会员信息')
            result = self.query.run(email, current == email, subscription=True)
            if not result.get('ok'):
                result = from_credential(auth_path, checked_at=int(time.time()),
                    error=result.get('err') or '暂时无法核验账号')
            result['identity_key'] = key
            values = self.state.get('subscriptions')
            values[email] = result
            self.state.update(subscriptions=values)
        return self.begin('subscription', email, work)

    def set_preferences(self, changes):
        if not isinstance(changes, dict):
            return {'ok': False, 'error': '设置格式不合法'}
        writable = {'appearance', 'notify_low', 'notify_reset_expiry', 'notify_credential',
                    'auto_relay', 'early_anchor', 'task_continuation', 'resume_message'}
        if any(key not in writable or not valid_setting(key, value) for key, value in changes.items()):
            return {'ok': False, 'error': '设置项或值不合法'}
        allowed = changes
        if allowed.get('task_continuation') is False:
            self.state.setting(**allowed)
            self.resumer.cancel_active()
        else:
            self.state.setting(**allowed)
            if allowed.get('task_continuation') is True:
                self.resumer.wake.set()
        if 'auto_relay' in allowed:
            settings = self.state.get('settings')
            self.resumer.set_auto_enabled(settings['auto_relay'],
                                          settings.get('auto_relay_excluded') or [])
        self.notify()
        return {'ok': True}

    def set_relay_pick(self, email=None):
        with self.lock:
            if email is not None and (email not in self.accounts.all() or email == self.accounts.current()):
                return {'ok': False, 'error': '这个账号不能设为下一棒'}
            if email is not None and (self.operation or self.state.get('adding') or self.state.get('reauth')):
                return {'ok': False, 'error': '请先完成当前操作'}
            account = next((a for a in self.get_data()['accounts'] if a['email'] == email), None)
            exhausted = bool(account and account.get('ok') and complete_windows(account.get('windows'))
                             and any(w['used'] >= 100 for w in account['windows']))
            origin = self.accounts.current()
            if exhausted and not origin:
                return {'ok': False, 'error': '请先确认当前账号'}
            self.state.update(relay_wait={'id': uuid.uuid4().hex, 'email': email, 'origin': origin}
                              if exhausted else None)
            self._relay_wait_refresh_after = self._relay_wait_attempt_after = 0.0
            self.relay_pick = None if exhausted else email
        self.notify()
        mode = 'waiting' if exhausted else 'picked' if email else 'cancelled'
        return {'ok': True, 'mode': mode, 'message': {
            'waiting': '已安排，额度恢复后自动接力', 'picked': '已设为下一棒', 'cancelled': '已取消'}[mode]}

    def set_auto_relay_account(self, email, enabled):
        if email not in self.accounts.all() or not isinstance(enabled, bool):
            return {'ok': False, 'error': '自动接力账号设置不合法'}
        def toggle(settings):
            excluded = set(settings.get('auto_relay_excluded') or [])
            excluded.discard(email) if enabled else excluded.add(email)
            settings['auto_relay_excluded'] = sorted(excluded)
            return settings
        self.state.change('settings', toggle)
        if email == self.accounts.current():
            self.resumer.set_limit_enabled(email, enabled and
                                          self.state.get('settings').get('auto_relay'))
        self.notify()
        return {'ok': True}

    def set_early_anchor_account(self, email, enabled):
        if email not in self.accounts.all() or type(enabled) is not bool:
            return {'ok': False, 'error': '提前计时账号设置不合法'}
        auth = claims(self.paths.snapshot(email)).get('https://api.openai.com/auth') or {}
        if auth.get('chatgpt_plan_type') != 'plus':
            return {'ok': False, 'error': '提前计时适用于 Plus 账号'}
        def toggle(settings):
            selected = set(settings.get('early_anchor_accounts') or [])
            selected.add(email) if enabled else selected.discard(email)
            settings['early_anchor_accounts'] = sorted(selected)
            return settings
        self.state.change('settings', toggle)
        self.notify()
        return {'ok': True}

    def _anchor_allowed(self, email):
        settings = self.state.get('settings')
        return (not self.stop.is_set() and settings.get('early_anchor')
                and email in (settings.get('early_anchor_accounts') or [])
                and email in self.accounts.all() and email != self.accounts.current())

    def _record_anchor_limits(self, value):
        def merge(cache):
            accounts = cache.get('accounts', [])
            previous = next((a for a in accounts if a.get('email') == value['email']), {})
            # This request reads quota only; keep separately queried reset details.
            quota = {key: item for key, item in value.items() if key != 'banked_resets'}
            updated = {**previous, **quota}
            cache['accounts'] = [updated if a.get('email') == value['email'] else a for a in accounts]
            if not previous:
                cache['accounts'].append(updated)
            return cache
        self.state.change('cache', merge)
        self.notify()

    def resolved_hotkeys(self, emails=None):
        emails = emails or self.accounts.all()
        saved = self.state.get('hotkeys', {})
        saved = saved if isinstance(saved, dict) else {}
        result = {}
        for index, email in enumerate(emails):
            if email in saved:
                result[email] = saved[email]
            else:
                result[email] = f'ctrl+alt+{index + 1}' if index < 9 else None
        return result

    def set_account_hotkey(self, email, shortcut):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        shortcut = shortcut.lower() if isinstance(shortcut, str) else None
        if shortcut is not None and not re.fullmatch(r'(?:ctrl\+alt|ctrl\+shift|alt\+shift|ctrl\+alt\+shift)\+[1-9]', shortcut):
            return {'ok': False, 'error': '请使用两个以上修饰键加数字 1–9'}
        with self.state.lock:
            for other, value in self.resolved_hotkeys().items():
                if other != email and shortcut is not None and value == shortcut:
                    return {'ok': False, 'error': '这个快捷键已分配给其他账号'}
            self.state.change('hotkeys', lambda values: {**values, email: shortcut})
        self.notify()
        return {'ok': True}

    def set_account_meta(self, email, alias='', subscription_date=None):
        """Legacy full-form API; new inline editors use explicit field patches."""
        return self.update_account_meta(email, {'alias': alias, 'subscription_date': subscription_date})

    def update_account_meta(self, email, changes):
        if email not in self.accounts.all():
            return {'ok': False, 'error': '账号不存在'}
        if not isinstance(changes, dict) or not changes or set(changes) - {'alias', 'subscription_date'}:
            return {'ok': False, 'error': '账号信息字段不合法'}
        patch = dict(changes)
        if 'alias' in patch:
            alias = patch['alias']
            if not isinstance(alias, str) or len(alias.strip()) > 24 or any(unicodedata.category(c).startswith('C') for c in alias):
                return {'ok': False, 'error': '昵称最多 24 个可显示字符'}
            patch['alias'] = alias.strip()
        if 'subscription_date' in patch:
            value = patch['subscription_date']
            if value not in (None, ''):
                if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    return {'ok': False, 'error': '日期格式应为 YYYY-MM-DD'}
                try:
                    date.fromisoformat(value)
                except ValueError:
                    return {'ok': False, 'error': '请输入有效的到期日期'}
            patch['subscription_date'] = value or None
        # State.change locks read/merge/write and publishes only after disk success.
        saved = self.state.change('account_meta', lambda meta: {**meta, email: {
            **meta.get(email, {}), **patch}})
        self.notify()
        return {'ok': True, 'meta': saved[email]}

    def _record_usage_limit_events(self, events):
        settings = self.state.get('settings')
        origin = self.accounts.current()
        account = next((a for a in self.state.get('cache').get('accounts', [])
                        if a.get('email') == origin), None)
        exhausted = [w.get('resets_at') for w in (account or {}).get('windows') or []
                     if isinstance(w.get('used'), (int, float))
                     and w['used'] >= 100 and isinstance(w.get('resets_at'), (int, float))]
        if exhausted:
            events = [{**event, 'account_reset_at': max(exhausted)} for event in events]
        self.resumer.note_limit_events(
            events, origin,
            settings.get('auto_relay') and
            origin not in set(settings.get('auto_relay_excluded') or []))
        self.log.info('usage_limit_event_detected tasks=%d',
                      len(events))

    def start_poll(self):
        self.resumer.start()
        def watch_work():
            delay = 2
            while not self.stop.wait(delay):
                try:
                    results = self.early_anchor.tick(self.state.get('settings'), busy=bool(
                        self.operation or self.state.get('adding') or self.state.get('reauth')))
                    if results:
                        self.log.info('early_anchor_batch sent=%d failed=%d',
                            sum(r['status'] in ('started', 'sent') for r in results),
                            sum(r['status'] == 'failed' for r in results))
                    delay = 2
                except Exception as error:
                    self.log.warning('early_anchor_watch_failed type=%s', type(error).__name__)
                    delay = 30
        threading.Thread(target=watch_work, name='nx-work-watch', daemon=True).start()
        def watch_login():
            """Announce a new login only after its credential has stayed stable."""
            observed = announced = None
            stable_since = 0.0
            while not self.stop.wait(.5):
                status = self._add_login_status()
                if status != observed:
                    observed = status
                    stable_since = time.monotonic()
                stable = status != 'ready' or time.monotonic() - stable_since >= 2.0
                if stable and status != announced:
                    announced = status
                    self.notify()
                if status == 'inactive':
                    observed = announced = None
        threading.Thread(target=watch_login, name='nx-login-watch', daemon=True).start()

        def watch_usage_limit():
            from .limit_watch import UsageLimitWatcher
            watcher = UsageLimitWatcher(self.paths.home)
            if not watcher.prime():
                self.log.info('usage_limit_watch_unavailable')
            delay = 1
            while not self.stop.wait(delay):
                try:
                    watcher.poll(self._record_usage_limit_events)
                    if not watcher.available:
                        raise RuntimeError('history_unavailable')
                    for origin, group in self.resumer.limit_groups().items():
                        if origin != self.accounts.current():
                            self.resumer.defer_limit(origin, 5)
                            continue
                        result = self.auto_relay_on_usage_limit(origin, group['events'])
                        if result.get('accepted'):
                            self.resumer.defer_limit(origin, 5)
                        elif result.get('reason') == 'no_candidate' and not group['refreshed']:
                            refresh = self.refresh(background=True)
                            accepted = bool(refresh.get('accepted'))
                            self.resumer.defer_limit(origin, 3 if accepted else 10,
                                                     refreshed=accepted)
                        elif result.get('reason') == 'no_candidate':
                            data = self.get_data()
                            reset_at = self._next_relay_reset_at(
                                data['accounts'], data['settings'].get('auto_relay_excluded') or [])
                            if reset_at is not None:
                                self.resumer.defer_limit(origin, max(2, reset_at - time.time() + 2),
                                                         refreshed=False, scheduled_at=reset_at)
                            else:
                                interval = max(60, int(data['settings']['poll_minutes']) * 60)
                                self.resumer.defer_limit(origin, interval, refreshed=True)
                        elif result.get('reason') in ('busy', 'cooldown'):
                            self.resumer.defer_limit(origin, 5)
                        elif result.get('reason') in ('disabled', 'excluded'):
                            self.resumer.disable_limit(origin)
                        elif result.get('reason') in ('current_changed', 'current_recovered'):
                            self.resumer.discard_origin(origin)
                        else:
                            self.resumer.defer_limit(origin, 30)
                    self.diagnostics.monitor_ok()
                    delay = 1
                except Exception as error:
                    delay = self.diagnostics.monitor_failed(error, watcher.failure if not watcher.available else None)
                    self.notify()
        threading.Thread(target=watch_usage_limit, name='nx-limit-watch', daemon=True).start()

        def loop():
            # Refresh the roster slowly. Near exhaustion, probe only the active
            # account each minute; exact task limit errors still take the 1 s path.
            last_current_probe = 0.0
            while not self.stop.is_set():
                settings = self.state.get('settings')
                interval = max(60, int(settings['poll_minutes']) * 60)
                cache = self.state.get('cache')
                current = self.accounts.current()
                account = next((a for a in cache.get('accounts', [])
                                if a.get('email') == current), None)
                now = time.time()
                self.relay_when_recovered()
                if self.operation:
                    pass
                elif settings.get('auto_relay') and self.refresh_stale_relay_accounts(self.get_data()):
                    pass
                elif now - (cache.get('updated') or 0) >= interval:
                    self.refresh(background=True)
                elif (settings.get('auto_relay') and account and account.get('ok')
                      and any(isinstance(w.get('used'), (int, float))
                              and w['used'] >= 80 and w.get('resets_at', 0) > now
                              for w in account.get('windows') or [])
                      and time.monotonic() - last_current_probe >= 60):
                    result = self.refresh(current, background=True)
                    if result.get('accepted'):
                        last_current_probe = time.monotonic()
                if self.stop.wait(15):
                    return
        threading.Thread(target=loop, name='nx-poll', daemon=True).start()
