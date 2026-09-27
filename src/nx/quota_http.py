"""Read-only account HTTP queries. No child processes or credential refreshes."""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import urllib.error
import urllib.request

from .quota import RPCError, normalize_limits, normalize_usage
from .storage import fingerprint, identity, timestamp
from .version import APP_VERSION

BASE = 'https://chatgpt.com/backend-api'
ENDPOINTS = frozenset(('/wham/usage', '/wham/profiles/me', '/wham/rate-limit-reset-credits'))
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPClient:
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
            error.close()
            if error.code == 401:
                raise RPCError('登录已失效，请重新登录该账号', 'reauth_required') from None
            if error.code == 403:
                raise RPCError('当前账号无权访问此接口', 403) from None
            if error.code == 429:
                raise RPCError('查询过于频繁，请稍后重试', 429) from None
            raise RPCError('查询服务暂时不可用', error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
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
    def __init__(self, paths, settings, log=None, client=None):
        self.paths, self.settings, self.log = paths, settings, log
        self.client = client or HTTPClient()
        self._invalid = {}
        self._lock = threading.Lock()

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
        before = None
        try:
            if cancel and cancel.is_set():
                raise RPCError('后台查询已暂停', 'cancelled')
            if not path.is_file():
                raise RPCError('未找到该账号的凭据快照', 'missing_snapshot')
            saved = path.read_bytes()
            before = hashlib.sha256(saved).hexdigest()
            who = identity(path)
            tokens = json.loads(saved.decode('utf-8-sig')).get('tokens') or {}
            token, account_id = tokens.get('access_token'), tokens.get('account_id')
            if not who[0] or who[0].casefold() != email.casefold() or not account_id or who[1] != account_id:
                raise RPCError('本地凭据与查询账号不一致', 'identity_mismatch')
            if not isinstance(token, str) or not token:
                raise RPCError('登录已失效，请重新登录该账号', 'reauth_required')
            with self._lock:
                invalid = self._invalid.get(email.casefold()) == before
            if invalid:
                raise RPCError('登录已失效，请重新登录该账号', 'reauth_required')
            deadline = time.monotonic() + float(self.settings().get('query_timeout', 45))
            def get(endpoint):
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
                try:
                    payload['rateLimitResetCredits'] = reset_payload(get('/wham/rate-limit-reset-credits'))
                except RPCError as error:
                    if error.code in ('reauth_required', 'identity_mismatch', 'cancelled'):
                        raise
                    # Keep the count from usage if optional details are unavailable.
                result = normalize_limits(payload, email)
            if cancel and cancel.is_set():
                raise RPCError('后台查询已暂停', 'cancelled')
            if fingerprint(path) != before:
                raise RPCError('查询期间账号已变化', 'identity_mismatch')
            with self._lock:
                self._invalid.pop(email.casefold(), None)
            return result
        except (RPCError, OSError, ValueError, TypeError, AttributeError) as error:
            code = getattr(error, 'code', 'credential_unreadable')
            if code == 'reauth_required' and before:
                with self._lock:
                    self._invalid[email.casefold()] = before
            return {'email': email, 'ok': False,
                    'err': str(error) if isinstance(error, RPCError) else '本地凭据暂不可读',
                    'error_code': code, 'unsupported': False, 'attempted_at': int(time.time())}
