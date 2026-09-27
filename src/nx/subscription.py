"""Automatic subscription metadata reading without inventing a billing API.

The usage endpoint reports online identity/plan, NOT verified billing dates. Explicit cached claims
are informative hints, never verified renewal/end dates. A positive network
response does not upgrade a cached hint to 'verified'. No credential strings
or raw account bodies cross the bridge.
"""
from __future__ import annotations
import time
from .storage import credential_metadata


def from_credential(path, *, checked_at=None, account_read_ok=False, error=None):
    meta = credential_metadata(path)
    hint = meta['subscription']
    return {'status': 'cached_hint' if hint.get('until') else 'not_provided',
            'date': hint.get('until'), 'date_kind': 'entitlement_hint' if hint.get('until') else None,
            'source': 'credential_claim' if hint.get('until') else 'not_available',
            'verified': False, 'observed_at': hint.get('observed_at'),
            'checked_at': checked_at, 'account_read_ok': bool(account_read_ok), 'account_checked_online': False,
            'error': error, 'billing_date_supported': False}
