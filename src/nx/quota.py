"""Quota and activity normalization shared by read-only HTTP queries."""
from __future__ import annotations
import time
import math

class RPCError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

def numeric(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if value < minimum or (maximum is not None and value > maximum):
        return None
    return value


def label(minutes):
    if minutes == 300:
        return '5h'
    if minutes == 10080:
        return '周'
    if minutes and minutes % 1440 == 0:
        return f'{int(minutes / 1440)}d'
    if minutes and minutes % 60 == 0:
        return f'{int(minutes / 60)}h'
    return f'{minutes}m' if minutes else '?'


def normalize_banked_resets(raw):
    """Keep the read-only reset entitlement separate from usage credits."""
    def timestamp(value):
        return value if isinstance(value, int) and not isinstance(value, bool) \
            and 0 < value <= 253402300799 else None

    if not isinstance(raw, dict):
        return None
    count = raw.get('availableCount')
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 2**53 - 1:
        return None
    rows = raw.get('credits')
    if rows is not None and not isinstance(rows, list):
        rows = None
    items = None if rows is None else []
    if items is not None:
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            expiry = timestamp(row.get('expiresAt'))
            items.append({
                'title': row.get('title')[:100] if isinstance(row.get('title'), str) else None,
                'description': row.get('description')[:300] if isinstance(row.get('description'), str) else None,
                'reset_type': row.get('resetType') if row.get('resetType') in ('codexRateLimits', 'unknown') else 'unknown',
                'status': row.get('status') if row.get('status') in ('available', 'redeeming', 'redeemed') else 'unknown',
                'granted_at': timestamp(row.get('grantedAt')),
                'expires_at': expiry,
                'expires_known': 'expiresAt' in row and (row['expiresAt'] is None or expiry is not None),
            })
    return {'available_count': count, 'items': items}


def normalize_usage_credits(raw) -> dict:
    """Preserve balance precision; absence, unlimited and invalid are distinct.

    CreditsSnapshot uses {hasCredits, unlimited, balance}. This is independent
    of rateLimitResetCredits and must not be inferred from subscription level.
    """
    from decimal import Decimal, InvalidOperation
    if raw is None:
        return {'status': 'not_provided', 'balance': None}
    if not isinstance(raw, dict):
        return {'status': 'invalid', 'balance': None}
    if raw.get('unlimited') is True:
        return {'status': 'unlimited', 'balance': None}
    value = raw.get('balance')
    if value is None:
        return {'status': 'not_provided', 'balance': None}
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return {'status': 'invalid', 'balance': None}
    text = str(value).strip()
    try:
        number = Decimal(text)
        # Bound pathological input without losing legitimate decimal precision.
        if not number.is_finite() or number < 0 or len(text) > 80 or abs(number.adjusted()) > 30:
            raise ValueError('invalid credit balance')
        if number == 0:
            number = number.copy_abs()
        return {'status': 'available', 'balance': format(number, 'f')}
    except (InvalidOperation, ValueError, OverflowError):
        return {'status': 'invalid', 'balance': None}


def normalize_limits(result: dict, email: str) -> dict:
    if not isinstance(result, dict):
        raise RPCError('额度结构无法识别', 'schema')
    primary = result.get('rateLimits') or {}
    by_id = result.get('rateLimitsByLimitId') or {}
    if not isinstance(primary, dict) or not isinstance(by_id, dict):
        raise RPCError('额度结构无法识别', 'schema')
    # Never merge differently metered buckets. Codex is the default bucket.
    limit = by_id.get('codex') or primary
    if not isinstance(limit, dict):
        raise RPCError('额度结构无法识别', 'schema')
    windows = []
    malformed = False
    for raw in (limit.get('primary'), limit.get('secondary')):
        if raw is None:
            continue
        if not isinstance(raw, dict):
            malformed = True
            continue
        used = numeric(raw.get('usedPercent'), 0, 100)
        duration = numeric(raw.get('windowDurationMins'), 1)
        resets = numeric(raw.get('resetsAt'), 1)
        if used is None or duration is None or resets is None:
            malformed = True
            continue
        windows.append({'label': label(duration), 'duration_mins': duration,
                        'used': used, 'resets_at': resets})
    if not windows or malformed:
        raise RPCError('额度窗口数据不完整', 'schema')
    credit = normalize_usage_credits(limit.get('credits'))
    return {'email': email, 'ok': True, 'err': None, 'error_code': None,
            'plan': limit.get('planType') or primary.get('planType') or 'unknown',
            'windows': windows, 'credits': credit['balance'], 'credit_info': credit,
            'banked_resets': normalize_banked_resets(result.get('rateLimitResetCredits')),
            'bucket': limit.get('limitId') or 'codex',
            'other_buckets': sorted(str(k) for k in by_id if k != (limit.get('limitId') or 'codex')),
            'fetched_at': int(time.time())}


def normalize_usage(result: dict) -> dict:
    from .usage import normalized
    try:
        return normalized(result)
    except ValueError as error:
        raise RPCError(str(error), 'schema') from error


from .quota_http import Query
