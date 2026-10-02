"""Allow-listed local diagnostics: no exception messages, paths or identities."""
from __future__ import annotations
from collections import deque
import copy
import re
import threading
import time
from .diagnostics_http import safe_fields, safe_code

SAFE_FILES = frozenset({'core.py', 'limit_watch.py', 'history_store.py',
    'resume_flow.py', 'desktop_resume.py', 'quota_http.py', 'query_policy.py',
    'storage.py', 'credentials.py', 'diagnostics.py'})
SAFE_ERRORS = frozenset({'TypeError', 'ValueError', 'RuntimeError', 'OSError',
    'PermissionError', 'FileNotFoundError', 'TimeoutError', 'KeyError',
    'AttributeError', 'OperationalError', 'DatabaseError', 'RPCError'})


def exception_location(error):
    """Use our source basename + line only. Never stringify errors or frames."""
    location = 'unknown'
    tb = error.__traceback__
    while tb:
        filename = tb.tb_frame.f_code.co_filename.replace('\\', '/').rsplit('/', 1)[-1]
        if filename in SAFE_FILES:
            location = f'{filename}:{tb.tb_lineno}'
        tb = tb.tb_next
    return {'error_type': type(error).__name__ if type(error).__name__ in SAFE_ERRORS else 'Exception',
            'location': location}


class Diagnostics:
    def __init__(self, log, clock=time.time):
        self.log, self.clock = log, clock
        self.lock = threading.RLock()
        self.events = deque(maxlen=20)
        self.health = {'state': 'starting', 'failures': 0, 'retry_at': None}

    def operation_failed(self, kind, error):
        safe_kind = kind if kind in {'refresh', 'switch', 'relay', 'add', 'remove',
            'restore', 'reauth', 'reauth_cancel', 'add_cancel'} else 'operation'
        event = {'at': int(self.clock()), 'kind': safe_kind, **exception_location(error)}
        with self.lock:
            self.events.append(event)
        self.log.warning('operation_diagnostic kind=%s type=%s location=%s',
                         safe_kind, event['error_type'], event['location'])

    def monitor_failed(self, error, details=None):
        now = self.clock()
        with self.lock:
            count = self.health['failures'] + 1
            delay = (5, 15, 60, 300)[min(count - 1, 3)]
            details = details or exception_location(error)
            self.health = {'state': 'degraded', 'failures': count,
                           'retry_at': int(now + delay), **details}
            self.events.append({'at': int(now), 'kind': 'limit_watch', **details})
        # Called once per delayed attempt, never at the 1-second polling rate.
        self.log.warning('limit_watch_degraded type=%s location=%s failures=%d retry_seconds=%d',
                         details['error_type'], details['location'], count, delay)
        return delay

    def monitor_ok(self):
        with self.lock:
            recovered = self.health['state'] == 'degraded'
            self.health = {'state': 'ok', 'failures': 0, 'retry_at': None}
        if recovered:
            self.log.info('limit_watch_recovered')

    def snapshot(self):
        with self.lock:
            return {'monitor': copy.deepcopy(self.health), 'events': list(copy.deepcopy(self.events))}


QUERY_CODES = frozenset({'reauth_required', 'network', 'timeout', 'schema',
    'missing_snapshot', 'identity_mismatch', 'credential_unreadable', 'cancelled',
    'cache_invalid', 'response_too_large', 'unexpected', 'query_policy_unavailable'})


def query_summary(account, index):
    """An explicit schema, not a redaction regex over private source data."""
    item = {'account': index, 'ok': account.get('ok') is True,
            'paused': account.get('paused') is True, **safe_fields(account)}
    code = account.get('error_code')
    item['error_code'] = code if ((type(code) is int and 100 <= code <= 599)
                                or (isinstance(code, str) and code in QUERY_CODES)) else None
    for key in ('retry_at', 'attempted_at', 'fetched_at', 'http_status'):
        value = account.get(key)
        if type(value) in (int, float) and 0 <= value <= 253402300799:
            item[key] = int(value)
    # HTTP diagnostics have already been sanitized by the transport. Keep the
    # export schema independent so future response fields cannot leak by default.
    request_id = account.get('request_id')
    if isinstance(request_id, str) and re.fullmatch(r'(?:req_[A-Za-z0-9_-]{1,96}|[0-9a-fA-F-]{16,64})', request_id):
        item['request_id'] = request_id
    warning = account.get('query_warning')
    if isinstance(warning, dict) and warning.get('scope') == 'reset_credits':
        item['optional_query'] = {**safe_fields(warning), 'scope': 'reset_credits',
            'error_code': safe_code(warning.get('error_code')),
            'paused': warning.get('paused') is True}
    return item
