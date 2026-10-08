"""Quota validity shared by ranking, persisted cache recovery and automation."""
from __future__ import annotations
import math
import time

def number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)

def complete_windows(windows):
    return isinstance(windows, list) and bool(windows) and all(
        isinstance(w, dict) and number(w.get('used')) and 0 <= w['used'] <= 100
        and number(w.get('resets_at')) and 0 < w['resets_at'] < 253402300800 for w in windows)

def readable_quota(account):
    """A temporary query failure does not erase previously returned quota."""
    code = account.get('error_code')
    return account.get('ok') is True or code in (
        'network', 'timeout', 'cancelled', 'schema', 'response_too_large',
        'query_policy_unavailable', -32603, '-32603', 408, 429) or \
        (type(code) is int and 500 <= code <= 599)

def known_windows(account):
    return readable_quota(account) and complete_windows(account.get('windows'))

def usable_windows(account, now=None, *, require_timestamp=True):
    now = time.time() if now is None else now
    if not known_windows(account):
        return False
    stamp = account.get('fetched_at')
    if stamp is None and not require_timestamp:
        age = 0
    elif not number(stamp) or not -60 <= now - stamp <= (900 if account.get('ok') is not True else 600):
        return False
    return all(w['resets_at'] > now for w in account['windows'])

def fresh_windows(account, now=None, *, require_timestamp=True):
    now = time.time() if now is None else now
    if account.get('ok') is not True or not complete_windows(account.get('windows')):
        return False
    stamp = account.get('fetched_at')
    if stamp is None and not require_timestamp:
        pass
    elif not number(stamp) or not -60 <= now - stamp <= 600:
        return False
    return all(w['resets_at'] > now for w in account['windows'])

def merge_quota(previous, result):
    """Merge one account, retaining good data on failure and newer reads on races."""
    if not result.get('ok'):
        failure = {key: value for key, value in result.items() if key not in
                   ('windows', 'fetched_at', 'credits', 'credit_info', 'banked_resets')}
        return {**previous, **failure, 'fetched_at': previous.get('fetched_at')}
    if number(previous.get('fetched_at')) and number(result.get('fetched_at')) \
            and previous['fetched_at'] > result['fetched_at']:
        return previous
    updated = {**previous, **result}
    for key in ('query_warning', 'http_status', 'request_id', 'server_error_code',
                'phase', 'transport_error', 'timeout_ms', 'elapsed_ms'):
        if key not in result:
            updated.pop(key, None)
    updated.update(paused=False, retry_at=None)
    return updated

def sanitize_cached_account(account):
    account = dict(account)
    if not complete_windows(account.get('windows')):
        account.update(ok=False, windows=[], err='额度缓存需要重新读取', error_code='cache_invalid')
    else:
        account['ok'] = account.get('ok') is True
    if not number(account.get('fetched_at')):
        account['fetched_at'] = None
    if not isinstance(account.get('plan'), str):
        account['plan'] = 'unknown'
    return account
