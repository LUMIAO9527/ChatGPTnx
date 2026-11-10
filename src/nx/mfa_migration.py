"""Local TOTP formatting and comparison helpers.

Enrollment uses the secret supplied by the account's security settings. A local
code comparison only checks that the same key produces the same code; completion
of enrollment is confirmed on the service's own page before the vault is updated.
"""
from __future__ import annotations

import base64
import os
import time

from .totp import ALPHABET, TotpError, code, normalize_secret

SECRET_BYTES = 20          # 160 bit, the size RFC 4226 recommends for a new seed
DIGITS = 6
PERIOD = 30


def generate_secret() -> str:
    """A fresh Base32 secret, 32 characters, no padding."""
    return base64.b32encode(os.urandom(SECRET_BYTES)).decode('ascii').rstrip('=')


def format_secret(secret: object, group: int = 4) -> str:
    """Grouped for reading off the screen: `JBSW Y3DP EHPK 3PXP …`."""
    clean = normalize_secret(secret)
    if group < 1:
        raise TotpError('分组长度不正确')
    return ' '.join(clean[index:index + group] for index in range(0, len(clean), group))


def mask_secret(secret: object) -> str:
    """Enough to recognise which key it is, not enough to use it."""
    clean = normalize_secret(secret)
    return f'{clean[:4]}…{clean[-4:]}' if len(clean) > 8 else '…'


def verify_entered(secret: object, entered: object, *, at: float | None = None,
                   windows: int = 1) -> bool:
    """Compare a locally entered code with this secret.

    ``windows`` allows one step either side: typing a code back can straddle a
    30 second boundary, and that is a clock boundary, not a wrong key.
    """
    text = ''.join(ch for ch in str(entered or '') if ch.isdigit())
    if len(text) != DIGITS:
        return False
    moment = time.time() if at is None else float(at)
    for offset in range(-abs(windows), abs(windows) + 1):
        if code(secret, at=moment + offset * PERIOD) == text:
            return True
    return False


def current_code(secret: object, *, at: float | None = None) -> tuple[str, int]:
    """The code to type into the settings page, plus seconds left in the window."""
    moment = time.time() if at is None else float(at)
    remaining = PERIOD - int(moment) % PERIOD
    return code(secret, at=moment), remaining