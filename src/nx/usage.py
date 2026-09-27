"""Account-activity aggregation, never quota aggregation.

Missing data stays missing. Account identity keys are opaque and never contain
credentials. Source dates are not converted to the viewer's local timezone.
Rolling windows use recorded daily buckets; "all" retains lifetime totals while
exposing only the available daily history for the trend.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import time

SOURCE = 'account/usage/read'
SUMMARY_KEYS = ('lifetimeTokens', 'peakDailyTokens', 'longestRunningTurnSec',
                'currentStreakDays', 'longestStreakDays')


def _local_date(timestamp):
    """Use the viewer's calendar day; source bucket dates remain untouched."""
    return datetime.fromtimestamp(timestamp).date()


def count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def normalized(result: dict, now=None) -> dict:
    from datetime import date
    if not isinstance(result, dict) or not isinstance(result.get('summary'), dict):
        raise ValueError('用量结构无法识别')

    def wire(v):
        n = count(v)
        return str(n) if n is not None and n > 9007199254740991 else n

    summary = {key: wire(result['summary'].get(key)) for key in SUMMARY_KEYS}
    raw = result.get('dailyUsageBuckets')
    buckets = None
    conflicts = set()
    if isinstance(raw, list):
        days = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                day = date.fromisoformat(item.get('startDate', '')).isoformat()
            except (TypeError, ValueError):
                continue
            tokens = count(item.get('tokens'))
            if tokens is None:
                continue
            if day in days and days[day] != tokens:
                conflicts.add(day)
            days[day] = tokens
        buckets = [
            {'startDate': day, 'tokens': wire(tokens)}
            for day, tokens in sorted(days.items()) if day not in conflicts
        ]
    return {
        'ok': True,
        'source': SOURCE,
        'scope': 'chatgpt_account_activity',
        'fetched_at': int(now or time.time()),
        'summary': summary,
        'dailyUsageBuckets': buckets,
        'conflicting_dates': sorted(conflicts),
    }


def _aggregate_days(eligible, start, end, unique_count):
    by_day = {}
    for value in eligible:
        for bucket in value.get('dailyUsageBuckets') or []:
            day, tokens = bucket['startDate'], count(bucket.get('tokens'))
            if not start.isoformat() <= day <= end.isoformat() or tokens is None:
                continue
            row = by_day.setdefault(day, {'tokens': 0, 'accounts': 0})
            row['tokens'] += tokens
            row['accounts'] += 1
    return by_day


def aggregate(accounts: list[dict], cache: dict, *, days=30, now=None) -> dict:
    """Return source-stamped totals plus the rolling period only.

    Only successful, same-source results bound to the present identity
    enter totals. Failed/missing values remain visible in rows. Daily peaks and
    streaks are never summed across accounts. Missing dates remain missing; they
    are not silently interpreted as zero activity.
    """
    now = int(now or time.time())
    days = days if days in (7, 30, 90, 180, 'all') else 30
    end = _local_date(now)
    start = end - timedelta(days=days - 1) if days != 'all' else None

    rows, eligible, seen = [], [], set()
    for account in accounts:
        email = account['email']
        key = account.get('identity_key') or 'email:' + email.casefold()
        activity_key = account.get('activity_key') or key
        duplicate = activity_key in seen
        seen.add(activity_key)
        value = cache.get(email)
        valid = isinstance(value, dict) and value.get('ok') is True and value.get('source') == SOURCE
        bound = not value or value.get('identity_key') == key
        ts = value.get('fetched_at') if isinstance(value, dict) else None
        tokens = count((value.get('summary') or {}).get('lifetimeTokens')) if valid else None
        status = 'duplicate' if duplicate else ('identity_changed' if not bound else (
            'unavailable' if value and not valid else 'pending' if not value else
            'missing_total' if tokens is None else 'ready'))
        row = {
            'email': email,
            'alias': account.get('alias', ''),
            'plan': account.get('plan', 'unknown'),
            'archived': bool(account.get('archived')),
            'identity_key': key,
            'activity_key': activity_key,
            'status': status,
            'fetched_at': ts,
            'tokens': str(tokens) if tokens is not None else None,
            'usage': value,
            'included': status == 'ready',
        }
        rows.append(row)
        if not duplicate and bound and valid:
            eligible.append(value)

    total_rows = [r for r in rows if r['included']]
    total = sum(int(r['tokens']) for r in total_rows) if total_rows else None
    unique_count = len(seen)

    if days == 'all':
        from datetime import date
        observed = [date.fromisoformat(bucket['startDate'])
                    for value in eligible for bucket in value.get('dailyUsageBuckets') or []
                    if bucket['startDate'] <= end.isoformat()]
        start = min(observed, default=None)

    for row in rows:
        value = row['usage']
        valid = (isinstance(value, dict) and value.get('ok') is True
                 and value.get('source') == SOURCE and row['status'] not in
                 ('duplicate', 'identity_changed', 'unavailable', 'pending'))
        buckets = [bucket for bucket in value.get('dailyUsageBuckets') or []
                   if start and start.isoformat() <= bucket['startDate'] <= end.isoformat()
                   and count(bucket.get('tokens')) is not None] if valid else []
        row['period_tokens'] = str(sum(count(bucket['tokens']) for bucket in buckets)) if buckets else None
        row['period_days'] = len(buckets)

    period_map = _aggregate_days(eligible, start, end, unique_count) if start else {}
    daily = [
        {
            'date': day,
            'tokens': str(v['tokens']),
            'accounts': v['accounts'],
            'complete': v['accounts'] == unique_count,
        }
        for day, v in sorted(period_map.items())
    ]
    full_period = (days != 'all' and unique_count > 0 and len(daily) == days
                   and all(d['complete'] for d in daily))

    return {
        'ok': True,
        'source': SOURCE,
        'scope': 'chatgpt_account_activity',
        'total_tokens': str(total) if total is not None else None,
        'included_accounts': len(total_rows),
        'unique_accounts': unique_count,
        'total_complete': bool(unique_count and len(total_rows) == unique_count),
        'rows': rows,
        'daily': daily,
        'period': {
            'days': days,
            'start': start.isoformat() if start else None,
            'end': end.isoformat(),
            'span_days': (end - start).days + 1 if start else 0,
            'complete': full_period,
            'recorded_tokens': str(sum(int(d['tokens']) for d in daily)) if daily else None,
        },
        'oldest_fetched_at': min((r['fetched_at'] for r in total_rows), default=None),
        'newest_fetched_at': max((r['fetched_at'] for r in total_rows), default=None),
        'generated_at': now,
    }
