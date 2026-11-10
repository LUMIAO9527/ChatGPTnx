"""RFC 6238 TOTP for the account vault. Never log or return secret material.

Standard library only. Six digits, 30 second period, SHA-1: the parameters
OpenAI issues when a TOTP authenticator is enrolled. Any otpauth:// URI that
asks for something else is rejected instead of silently producing wrong codes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import time
from urllib.parse import parse_qs, urlparse

ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
DIGITS = 6
PERIOD = 30
MIN_SECRET = 16
MAX_SECRET = 128


class TotpError(ValueError):
    """Safe to show: messages never include secret material."""


def normalize_secret(raw: object) -> str:
    """Accept a bare Base32 secret or a whole otpauth:// enrolment URI."""
    if not isinstance(raw, str):
        raise TotpError('2FA 密钥格式不正确')
    text = raw.strip()
    if text.lower().startswith('otpauth://'):
        try:
            uri = urlparse(text)
            if uri.netloc.lower() != 'totp':
                raise ValueError()
            query = parse_qs(uri.query)
        except ValueError:
            raise TotpError('2FA 密钥格式不正确') from None
        values = query.get('secret') or []
        text = values[0] if len(values) == 1 else ''
        if query.get('digits') and query['digits'][0] != str(DIGITS):
            raise TotpError('仅支持 6 位验证码')
        if query.get('period') and query['period'][0] != str(PERIOD):
            raise TotpError('仅支持 30 秒周期')
        if query.get('algorithm') and query['algorithm'][0].upper() not in ('SHA1', 'SHA-1'):
            raise TotpError('仅支持 SHA-1')
    cleaned = re.sub(r'[\s-]', '', text.upper()).rstrip('=')
    if not re.fullmatch(r'[A-Z2-7]+', cleaned):
        raise TotpError('2FA 密钥不是有效的 Base32')
    if len(cleaned) < MIN_SECRET:
        raise TotpError('2FA 密钥太短')
    if len(cleaned) > MAX_SECRET:
        raise TotpError('2FA 密钥太长')
    _key(cleaned)
    return cleaned


def looks_like_secret(raw: object) -> bool:
    """Cheap shape test used when splitting imported account lines."""
    if not isinstance(raw, str):
        return False
    try:
        normalize_secret(raw)
        return True
    except TotpError:
        return False


def _key(secret: str) -> bytes:
    padded = secret + '=' * (-len(secret) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except Exception:
        raise TotpError('2FA 密钥不是有效的 Base32') from None


def code(secret: str, at: float | None = None) -> str:
    """Six digit code for the 30 second window containing ``at``."""
    moment = time.time() if at is None else float(at)
    counter = int(moment // PERIOD)
    digest = hmac.new(_key(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def remaining(at: float | None = None) -> int:
    """Seconds left in the current window, 1..30."""
    moment = time.time() if at is None else float(at)
    return PERIOD - int(moment) % PERIOD


def code_if_stable(secret: str, minimum: int = 8, at: float | None = None) -> str | None:
    """Code only when the window has at least ``minimum`` seconds left.

    Filling a code with two seconds left wastes an authentication attempt on a
    code that expires while the page is still submitting it.
    """
    moment = time.time() if at is None else float(at)
    if remaining(moment) < minimum:
        return None
    return code(secret, moment)
