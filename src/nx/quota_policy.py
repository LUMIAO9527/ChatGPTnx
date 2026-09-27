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
