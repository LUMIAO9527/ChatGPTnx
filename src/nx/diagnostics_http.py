"""Small allow-listed HTTP diagnostics; never retain response text or headers."""
from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import math
import re

ERROR_BYTES = 16 * 1024
SERVER_CODES = frozenset(('account_deactivated', 'account_suspended', 'permission_denied',
    'access_denied', 'forbidden', 'rate_limit_exceeded', 'too_many_requests',
    'insufficient_quota', 'invalid_api_key', 'invalid_token', 'token_expired',
    'unauthorized', 'server_error', 'internal_error', 'temporarily_unavailable',
    'service_unavailable'))
LOCAL_CODES = frozenset(('reauth_required', 'network', 'timeout', 'schema', 'cancelled',
    'response_too_large', 'missing_snapshot', 'identity_mismatch', 'credential_unreadable',
    'query_policy_unavailable', 'unexpected'))
PHASES = frozenset(('credentials', 'quota', 'usage', 'reset_credits', 'subscription', 'policy'))
_REQUEST_ID = re.compile(r'(?:req_[A-Za-z0-9_-]{8,96}|[0-9a-fA-F]{16,64}|'
                         r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\Z')


def safe_code(value):
    return value if (type(value) is int and 100 <= value <= 599) or \
        (isinstance(value, str) and value in LOCAL_CODES) else 'unexpected'


def safe_fields(raw):
    """Revalidate even persisted metadata before exposing it to UI or logging."""
    raw = raw if isinstance(raw, dict) else {}
    status, request, code = raw.get('http_status'), raw.get('request_id'), raw.get('server_error_code')
    phase = raw.get('phase')
    return {'http_status': status if type(status) is int and 100 <= status <= 599 else None,
            'request_id': request if isinstance(request, str) and _REQUEST_ID.fullmatch(request) else None,
            'server_error_code': code if isinstance(code, str) and code in SERVER_CODES else None,
            'phase': phase if isinstance(phase, str) and phase in PHASES else 'policy'}


def retry_after(value, now):
    """Accept HTTP seconds/date without allowing invalid or infinite values."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        seconds = float(value) if value.strip().isdigit() else None
        if seconds is None:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = date.timestamp() - now
        return math.ceil(now + max(0, seconds)) if math.isfinite(seconds) and seconds <= 31536000 else None
    except (TypeError, ValueError, OverflowError):
        return None


def http_diagnostics(error, now):
    """Read at most 16 KiB of an error body; preserve only enumerated codes."""
    raw = {'http_status': error.code}
    headers = error.headers or {}
    raw['request_id'] = headers.get('x-request-id')
    try:
        body = error.read(ERROR_BYTES + 1)
        if len(body) <= ERROR_BYTES:
            obj = json.loads(body)
            detail = obj.get('error', obj) if isinstance(obj, dict) else {}
            raw['server_error_code'] = detail.get('code') if isinstance(detail, dict) else None
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, TypeError, AttributeError):
        pass
    finally:
        error.close()
    return {**safe_fields(raw), 'retry_after_at': retry_after(headers.get('Retry-After'), now)}


def message(code):
    # Never echo RPCError.__str__: even a mocked or future transport can contain
    # credentials, paths or a response body in its exception message.
    return {'reauth_required': '登录已失效，请重新登录该账号',
            403: '当前账号无权访问此接口，已暂停查询；可人工恢复',
            429: '查询过于频繁，等待冷却后重试',
            'network': '查询连接失败或超时，等待冷却后重试',
            'timeout': '查询超时，等待冷却后重试',
            'schema': '查询结构无法识别', 'cancelled': '后台查询已暂停',
            'response_too_large': '查询响应超过读取上限',
            'missing_snapshot': '未找到该账号的凭据快照',
            'identity_mismatch': '本地凭据或查询身份与账号不一致',
            'credential_unreadable': '本地凭据暂不可读',
            'query_policy_unavailable': '查询保护状态暂不可读，已暂停查询'}.get(code, '查询服务暂时不可用')
