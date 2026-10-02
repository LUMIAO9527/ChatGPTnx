"""Read-only account HTTP queries. No child processes or credential refreshes."""
from __future__ import annotations

import hashlib
import http.client
import json
import shutil
import time
import urllib.error
import urllib.request

from .quota import RPCError, normalize_limits, normalize_usage
from .storage import fingerprint, identity, timestamp
from .credentials import read_credential_bytes
from .diagnostics_http import http_diagnostics, message, safe_code, safe_fields
from .query_policy import QueryPolicy
from .version import APP_VERSION

BASE = 'https://chatgpt.com/backend-api'
ENDPOINTS = frozenset(('/wham/usage', '/wham/profiles/me', '/wham/rate-limit-reset-credits'))
MAX_BYTES = 2 * 1024 * 1024


def credential_fingerprint(saved):
    """Stable across DPAPI encryption and current/snapshot serialization."""
    tokens = json.loads(saved.decode('utf-8-sig')).get('tokens') or {}
    return hashlib.sha256(json.dumps(tokens, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def failure_details(error, phase):
    raw = getattr(error, 'diagnostics', {})
    raw = raw if isinstance(raw, dict) else {}
    return {**safe_fields(raw), 'phase': phase, 'retry_after_at': raw.get('retry_after_at')}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPClient:
    def __init__(self, clock=None):
        self.clock = clock or time.time

    def get(self, endpoint, token, account_id, timeout, cancel=None):
        if endpoint not in ENDPOINTS:
            raise RPCError('查询地址不受支持', 'schema')
        if cancel and cancel.is_set():
            raise RPCError('后台查询已暂停', 'cancelled')
        request = urllib.request.Request(BASE + endpoint, method='GET', headers={
            'Authorization': 'Bearer ' + token,
            'ChatGPT-Account-Id': account_id,
            'Accept': 'application/json', 'User-Agent': 'ChatGPTnx/' + APP_VERSION})
        try:
            # Redirects must never forward account credentials to another URL.
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                body = response.read(MAX_BYTES + 1)
            if cancel and cancel.is_set():
                raise RPCError('后台查询已暂停', 'cancelled')
            if len(body) > MAX_BYTES:
                raise RPCError('查询响应超过读取上限', 'response_too_large')
            result = json.loads(body)
            if not isinstance(result, dict):
                raise RPCError('查询结构无法识别', 'schema')
            return result
        except urllib.error.HTTPError as error:
            details = http_diagnostics(error, self.clock())
            code = 'reauth_required' if error.code == 401 else safe_code(error.code)
            failure = RPCError(message(code), code)
            failure.diagnostics = details
            raise failure from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise RPCError('查询连接失败或超时', 'network') from None
        except (ValueError, UnicodeError):
            raise RPCError('查询结构无法识别', 'schema') from None


def limits_payload(raw):
    def window(value):
        if value is None:
            return None
        if not isinstance(value, dict):
            return {}
        seconds = value.get('limit_window_seconds')
        return {'usedPercent': value.get('used_percent'),
                'windowDurationMins': seconds / 60 if type(seconds) in (int, float) else None,
                'resetsAt': value.get('reset_at')}
    rate = raw.get('rate_limit')
    if not isinstance(rate, dict):
        raise RPCError('额度窗口数据不完整', 'schema')
    credits = raw.get('credits')
    if isinstance(credits, dict):
        credits = {'hasCredits': credits.get('has_credits'),
                   'unlimited': credits.get('unlimited'), 'balance': credits.get('balance')}
    resets = raw.get('rate_limit_reset_credits')
    return {'rateLimits': {'limitId': 'codex', 'planType': raw.get('plan_type'),
            'primary': window(rate.get('primary_window')),
            'secondary': window(rate.get('secondary_window')), 'credits': credits},
            'rateLimitResetCredits': {'availableCount': resets.get('available_count')}
                if isinstance(resets, dict) else None}


def reset_payload(raw):
    rows = raw.get('credits')
    return {'availableCount': raw.get('available_count'), 'credits': [
        {'title': r.get('title'), 'description': r.get('description'),
         'resetType': 'codexRateLimits' if r.get('reset_type') in ('codex', 'codex_rate_limits', 'codexRateLimits') else 'unknown',
         'status': r.get('status'), 'grantedAt': timestamp(r.get('granted_at')),
         **({'expiresAt': timestamp(r.get('expires_at'))} if 'expires_at' in r else {})}
        for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None}


def usage_payload(raw):
    stats = raw.get('stats')
    if not isinstance(stats, dict) or (raw.get('metadata') or {}).get('stats_error'):
        raise RPCError('用量统计暂不可用', 'schema')
    keys = {'lifetimeTokens': 'lifetime_tokens', 'peakDailyTokens': 'peak_daily_tokens',
            'longestRunningTurnSec': 'longest_running_turn_sec',
            'currentStreakDays': 'current_streak_days', 'longestStreakDays': 'longest_streak_days'}
    rows = stats.get('daily_usage_buckets')
    return {'summary': {k: stats.get(v) for k, v in keys.items()},
            'dailyUsageBuckets': [{'startDate': r.get('start_date'), 'tokens': r.get('tokens')}
                for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None}


class Query:
    def __init__(self, paths, settings, log=None, client=None, clock=None):
        self.paths, self.settings, self.log = paths, settings, log
        self.clock = clock or time.time
        self.client = client or HTTPClient(self.clock)
        self.policy = QueryPolicy(paths.data, self.clock)
        self._policy_unavailable = False
        self._status_cache = {}

    def _credential_hint(self, path, email):
        """Cache only an opaque digest and local error category, never plaintext."""
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        key = (str(path), email.casefold())
        cached = self._status_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1:]
        try:
            saved = read_credential_bytes(path)
            tokens = json.loads(saved.decode('utf-8-sig')).get('tokens') or {}
            digest = credential_fingerprint(saved)
            token, account_id = tokens.get('access_token'), tokens.get('account_id')
            who = identity(path)
            code = None
            if not who[0] or who[0].casefold() != email.casefold() or not account_id or who[1] != account_id:
                code = 'identity_mismatch'
            elif not isinstance(token, str) or not token:
                code = 'reauth_required'
        except (OSError, ValueError, TypeError, AttributeError):
            digest, code = None, 'credential_unreadable'
        self._status_cache[key] = (signature, digest, code)
        return digest, code

    def status(self, email, current=False):
        """Read-only scheduling metadata; decrypted token contents never escape."""
        path = self.paths.auth if current else self.paths.snapshot(email)
        try:
            if self._policy_unavailable:
                raise ValueError('query policy unavailable')
            try:
                credential, code = self._credential_hint(path, email)
            except FileNotFoundError:
                credential, code = None, 'missing_snapshot'
            if code:
                return {**safe_fields({'phase': 'credentials'}), 'ready': False, 'paused': True,
                        'retry_at': None, 'error_code': code}
            return self.policy.status(email, credential)
        except (OSError, ValueError, TypeError, AttributeError):
            return {**safe_fields({}), 'ready': False, 'paused': True, 'retry_at': None,
                    'error_code': 'query_policy_unavailable'}

    def ready(self, email, current=False):
        return self.status(email, current)['ready']

    def resume(self, email):
        try:
            resumed = self.policy.resume(email)
            self._policy_unavailable = False
            return resumed
        except (OSError, ValueError, TypeError):
            return False

    def _failure(self, email, code, details, policy=None):
        if (policy or {}).get('error_code') == 'query_policy_unavailable':
            code = 'query_policy_unavailable'
        return {'email': email, 'ok': False, 'err': message(code), 'error_code': code,
                'unsupported': False, 'attempted_at': int(self.clock()),
                **safe_fields(details), 'paused': bool((policy or {}).get('paused')),
                'retry_at': (policy or {}).get('retry_at')}

    def _record_failure(self, email, credential, code, details, scope='account'):
        try:
            return self.policy.failed(email, credential, code, details, scope=scope)
        except (OSError, ValueError, TypeError):
            self._policy_unavailable = True
            return {'paused': True, 'retry_at': None, 'error_code': 'query_policy_unavailable'}

    def cleanup_orphans(self):
        # Migration only: old versions left isolated app-server query homes.
        root = self.paths.data.resolve()
        removed = failed = 0
        for folder in root.glob('query-*'):
            try:
                if (not folder.is_dir() or folder.is_symlink() or folder.resolve().parent != root
                        or time.time() - folder.stat().st_mtime < 3600):
                    continue
                shutil.rmtree(folder)
                removed += 1
            except OSError:
                failed += 1
        return removed, failed

    def run(self, email, current, usage=False, subscription=False, cancel=None):
        path = self.paths.auth if current else self.paths.snapshot(email)
        before, credential, phase, warning = None, None, 'credentials', None
        try:
            if cancel and cancel.is_set():
                raise RPCError('后台查询已暂停', 'cancelled')
            if not path.is_file():
                raise RPCError('未找到该账号的凭据快照', 'missing_snapshot')
            before = fingerprint(path)
            saved = read_credential_bytes(path)
            credential = credential_fingerprint(saved)
            who = identity(path)
            tokens = json.loads(saved.decode('utf-8-sig')).get('tokens') or {}
            token, account_id = tokens.get('access_token'), tokens.get('account_id')
            if not who[0] or who[0].casefold() != email.casefold() or not account_id or who[1] != account_id:
                raise RPCError('本地凭据与查询账号不一致', 'identity_mismatch')
            if not isinstance(token, str) or not token:
                raise RPCError('登录已失效，请重新登录该账号', 'reauth_required')
            try:
                if self._policy_unavailable:
                    raise ValueError('query policy unavailable')
                state = self.policy.status(email, credential, consume=True)
            except (OSError, ValueError, TypeError):
                return self._failure(email, 'query_policy_unavailable', {'phase': 'policy'}, {'paused': True})
            if not state['ready']:
                return self._failure(email, state['error_code'], state, state)
            deadline = time.monotonic() + float(self.settings().get('query_timeout', 45))
            def get(endpoint):
                nonlocal phase
                phase = {'/wham/usage': 'quota', '/wham/profiles/me': 'usage',
                         '/wham/rate-limit-reset-credits': 'reset_credits'}[endpoint]
                if fingerprint(path) != before:
                    raise RPCError('查询期间账号已变化', 'identity_mismatch')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RPCError('查询超时', 'timeout')
                return self.client.get(endpoint, token, account_id, min(5, remaining), cancel)
            raw = get('/wham/usage')
            if raw.get('account_id') != account_id or str(raw.get('email', '')).casefold() != email.casefold():
                raise RPCError('查询身份与账号清单不一致', 'identity_mismatch')
            if usage:
                result = normalize_usage(usage_payload(get('/wham/profiles/me')))
            elif subscription:
                from .subscription import from_credential
                result = {'ok': True, **from_credential(path, checked_at=int(time.time()), account_read_ok=True),
                          'plan': raw.get('plan_type') or 'unknown'}
            else:
                payload = limits_payload(raw)
                optional = self.policy.status(email, credential, scope='reset_credits')
                if not optional['ready']:
                    warning = self._failure(email, optional['error_code'], optional, optional)
                else:
                    try:
                        payload['rateLimitResetCredits'] = reset_payload(get('/wham/rate-limit-reset-credits'))
                    except RPCError as error:
                        if error.code in ('reauth_required', 'identity_mismatch', 'cancelled'):
                            raise
                        # A denied optional entitlement endpoint does not revoke
                        # access to the successful primary quota endpoint.
                        code = safe_code(error.code)
                        details = failure_details(error, phase)
                        scope = 'reset_credits' if code == 403 else 'account'
                        state = self._record_failure(email, credential, code, details, scope=scope)
                        warning = self._failure(email, code, details, state)
                if warning:
                    warning.pop('email', None)
                    if warning['error_code'] == 403:
                        warning.update(scope='reset_credits', err='额度重置详情不可用，已暂停该接口；主额度查询继续')
                result = normalize_limits(payload, email)
            if cancel and cancel.is_set():
                raise RPCError('后台查询已暂停', 'cancelled')
            if fingerprint(path) != before:
                raise RPCError('查询期间账号已变化', 'identity_mismatch')
            if warning:
                result.update(query_warning=warning, paused=warning['paused'], retry_at=warning['retry_at'])
            if not warning or warning.get('scope') == 'reset_credits':
                try:
                    self.policy.succeeded(email, credential)
                except (OSError, ValueError, TypeError):
                    self._policy_unavailable = True
                    return self._failure(email, 'query_policy_unavailable', {'phase': 'policy'}, {'paused': True})
                result.update(paused=False, retry_at=None)
            return result
        except (RPCError, OSError, ValueError, TypeError, AttributeError) as error:
            code = safe_code(getattr(error, 'code', 'credential_unreadable'))
            details = failure_details(error, phase)
            state = self._record_failure(email, credential, code, details) if credential else None
            return self._failure(email, code, details, state)
