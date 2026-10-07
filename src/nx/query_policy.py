"""Persistent credential-scoped query circuit breaker, containing no identities."""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time

from .diagnostics_http import safe_code, safe_fields
from .storage import atomic_bytes

_LOCK = threading.RLock()
MAX_STATE_BYTES = 1024 * 1024


def account_key(email, scope='account'):
    prefix = 'query:reset_credits:' if scope == 'reset_credits' else 'query:'
    return hashlib.sha256((prefix + email.casefold()).encode('utf-8')).hexdigest()


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _number(value, default=0):
    # Range-check integers before float conversion: a corrupted JSON integer
    # can be arbitrarily large and math.isfinite would otherwise overflow.
    return value if type(value) in (int, float) and 0 <= value <= 253402300799 and math.isfinite(value) else default


class QueryPolicy:
    def __init__(self, data, clock=None):
        self.path = data / 'query-policy.json'
        self.clock = clock or time.time
        self._probes = set()

    def _read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_STATE_BYTES + 1)
        except FileNotFoundError:
            return {'accounts': {}, 'network': {}}
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError('query policy too large')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('accounts'), dict):
            raise ValueError('invalid query policy')
        accounts = {}
        for key, record in data['accounts'].items():
            if not _hex(key) or not isinstance(record, dict) or not _hex(record.get('credential')):
                continue
            accounts[key] = {**safe_fields(record), 'credential': record['credential'],
                'error_code': safe_code(record.get('error_code')), 'paused': record.get('paused') is True,
                'attempts': min(int(_number(record.get('attempts'))), 20),
                'retry_at': _number(record.get('retry_at')), 'updated_at': _number(record.get('updated_at'))}
        network = data.get('network')
        network = network if isinstance(network, dict) else {}
        recent = network.get('recent')
        return {'accounts': accounts, 'network': {
            'retry_at': _number(network.get('retry_at')),
            'attempts': min(int(_number(network.get('attempts'))), 20),
            'recent': {key: _number(value) for key, value in recent.items() if _hex(key)}
                if isinstance(recent, dict) else {}}}

    def _write(self, data):
        # Old fingerprints are replaced on every credential change. Bound old
        # removed-account metadata without deleting credentials or user files.
        if len(data['accounts']) > 512:
            data['accounts'] = dict(sorted(data['accounts'].items(),
                key=lambda item: item[1].get('updated_at', 0), reverse=True)[:512])
        atomic_bytes(self.path, json.dumps({'version': 1, **data}, separators=(',', ':')).encode('utf-8'))

    def _status(self, data, key, credential, consume=False, shared=True):
        now = self.clock()
        entry = data['accounts'].get(key, {})
        entry = entry if entry.get('credential') == credential else {}
        result = {**safe_fields(entry), 'error_code': entry.get('error_code'),
                  'paused': entry.get('paused', False), 'retry_at': entry.get('retry_at') or None,
                  'ready': not entry.get('paused') and entry.get('retry_at', 0) <= now}
        global_retry = data['network'].get('retry_at', 0) if shared else 0
        if global_retry > now and result['ready']:
            if key in self._probes:
                if consume:
                    self._probes.remove(key)
            else:
                result.update(error_code='network', ready=False, retry_at=global_retry, phase='policy')
        elif global_retry > now and not result['paused']:
            result['retry_at'] = max(result.get('retry_at') or 0, global_retry)
        return result

    def status(self, email, credential, consume=False, scope='account'):
        with _LOCK:
            # The primary query already consumed any authorized shared probe.
            # Its optional endpoint gate only decides whether that endpoint is
            # unsupported; do not reject a successful probe a second time.
            return self._status(self._read(), account_key(email, scope), credential, consume,
                                shared=scope != 'reset_credits')

    def failed(self, email, credential, code, details, scope='account'):
        with _LOCK:
            data, now, key = self._read(), self.clock(), account_key(email, scope)
            old = data['accounts'].get(key, {})
            same = old.get('credential') == credential and old.get('error_code') == code
            attempts = min(old.get('attempts', 0) + 1, 20) if same else 1
            paused = code in ('reauth_required', 403)
            transient = code in (429, 'network', 'timeout', 'schema', 'response_too_large') or \
                (type(code) is int and 500 <= code <= 599)
            if not paused and not transient:
                return {**safe_fields(details), 'error_code': code, 'paused': False, 'retry_at': None, 'ready': True}
            retry_at = 0
            if transient:
                delay = min(60 * 2 ** (attempts - 1), 1800 if code == 429 else 900)
                retry_at = math.ceil(max(now + delay, _number(details.get('retry_after_at'))))
            data['accounts'][key] = {**safe_fields(details), 'credential': credential, 'error_code': code,
                'paused': paused, 'retry_at': retry_at, 'attempts': attempts, 'updated_at': int(now)}
            if scope == 'account' and code in ('network', 'timeout'):
                network = data['network']
                recent = {k: v for k, v in network.get('recent', {}).items() if now - 60 <= v <= now}
                recent[key] = now
                network['recent'] = recent
                if len(recent) >= 2 or network.get('retry_at', 0) > now:
                    count = min(network.get('attempts', 0) + 1, 20)
                    network.update(attempts=count, retry_at=math.ceil(now + min(60 * 2 ** (count - 1), 900)))
            self._write(data)
            return self._status(data, key, credential)

    def succeeded(self, email, credential):
        with _LOCK:
            data, key = self._read(), account_key(email)
            if key in data['accounts'] or data['network'].get('retry_at') or data['network'].get('recent'):
                data['accounts'].pop(key, None)
                # A successful actual network request proves connectivity.
                data['network'] = {}
                self._probes.clear()
                self._write(data)

    def resume(self, email):
        """Explicit user action only. Never bypass 401 or rate-limit cooldown."""
        with _LOCK:
            data, key, now = self._read(), account_key(email), self.clock()
            entry = data['accounts'].get(key, {})
            if entry.get('error_code') == 'reauth_required' or \
                    (entry.get('error_code') == 429 and entry.get('retry_at', 0) > now):
                return False
            data['accounts'].pop(key, None)
            data['accounts'].pop(account_key(email, 'reset_credits'), None)
            if data['network'].get('retry_at', 0) > now:
                self._probes.add(key)
            self._write(data)
            return True
