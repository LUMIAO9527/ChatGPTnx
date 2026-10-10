"""One explicit reset per confirmation; uncertain retries reuse its request ID."""
from __future__ import annotations

import json
import http.client
import time
import urllib.error
import urllib.request
import uuid

from .credentials import read_credential_bytes
from .quota import RPCError, normalize_limits
from .quota_http import BASE, MAX_BYTES, HTTPClient, NoRedirect, limits_payload, reset_payload
from .storage import account_identity_key, atomic_bytes, fingerprint, identity, read_json
from .version import APP_VERSION


OUTCOMES = frozenset(('reset', 'already_redeemed', 'nothing_to_reset', 'no_credit'))
MESSAGES = {'reset': '额度已重置', 'already_redeemed': '额度已重置',
            'nothing_to_reset': '当前额度无需重置', 'no_credit': '没有可用的重置次数'}


class ResetClient(HTTPClient):
    def consume(self, token, account_id, credit_id, request_id, timeout):
        request = urllib.request.Request(BASE + '/wham/rate-limit-reset-credits/consume',
            method='POST', data=json.dumps({'credit_id': credit_id,
                'redeem_request_id': request_id}).encode('utf-8'), headers={
                'Authorization': 'Bearer ' + token, 'ChatGPT-Account-Id': account_id,
                'Content-Type': 'application/json', 'Accept': 'application/json',
                'User-Agent': 'ChatGPTnx/' + APP_VERSION})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                body = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            body = error.read(MAX_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise RPCError('重置结果未确认，请点击重试', 'reset_uncertain') from None
        try:
            value = json.loads(body) if len(body) <= MAX_BYTES else None
            code = value.get('code') if isinstance(value, dict) else None
            if code not in OUTCOMES:
                raise ValueError('unknown outcome')
            return code
        except (ValueError, TypeError, UnicodeError):
            raise RPCError('重置结果未确认，请点击重试', 'reset_uncertain') from None


class ResetCredits:
    def __init__(self, paths, current, settings, record_limits=lambda value: None,
                 client=None, clock=time.time):
        self.paths, self.current, self.settings = paths, current, settings
        self.record_limits, self.client, self.clock = record_limits, client or ResetClient(), clock
        self.path = paths.data / 'reset-attempts.json'

    def _records(self):
        records = read_json(self.path, {}) if not self.path.exists() else read_json(self.path)
        if not isinstance(records, dict) or any(not isinstance(r, dict) for r in records.values()):
            raise RPCError('重置记录无法读取，请检查本地文件', 'reset_state')
        return records

    def _save(self, records):
        atomic_bytes(self.path, json.dumps(records).encode('utf-8'), private=True)

    def pending(self, email):
        try:
            path = self.paths.auth if email == self.current() else self.paths.snapshot(email)
            record = self._records().get(account_identity_key(path, email), {})
            return ({'credit_id': record['credit_id'], 'request_id': record['request_id']}
                    if record.get('status') == 'pending' else None)
        except (OSError, ValueError, KeyError, TypeError, RPCError):
            return None

    def consume(self, email, credit_id, request_id):
        if not isinstance(credit_id, str) or not 0 < len(credit_id) <= 256:
            raise RPCError('请刷新重置详情后再使用', 'reset_credit')
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise RPCError('重置确认已失效，请重新确认', 'reset_request') from None
        path = self.paths.auth if email == self.current() else self.paths.snapshot(email)
        try:
            saved = json.loads(read_credential_bytes(path).decode('utf-8-sig'))
            tokens = saved.get('tokens') or {}
            who, account_id = identity(path)
            if (who != email or not account_id or tokens.get('account_id') != account_id
                or not isinstance(tokens.get('access_token'), str) or not tokens['access_token']):
                raise ValueError('identity')
        except (OSError, ValueError, TypeError, AttributeError):
            raise RPCError('账号本地登录信息不完整，请重新登录', 'identity_mismatch') from None
        key, original = account_identity_key(path, email), fingerprint(path)
        records = self._records()
        previous = records.get(key, {})
        if previous.get('request_id') == request_id and previous.get('status') == 'complete':
            if previous.get('credit_id') != credit_id:
                raise RPCError('重置确认与所选次数不匹配', 'reset_request')
            return previous['outcome']
        retrying = previous.get('status') == 'pending'
        if retrying:
            if previous.get('credit_id') != credit_id:
                raise RPCError('请先重试上一次尚未确认的重置', 'reset_pending')
            request_id = previous['request_id']
        timeout = float(self.settings().get('query_timeout', 45))
        token = tokens['access_token']

        def read():
            raw = self.client.get('/wham/usage', token, account_id, timeout)
            fetched_at = self.clock()
            if raw.get('account_id') != account_id or raw.get('email', '').casefold() != email.casefold():
                raise RPCError('查询账号身份不匹配', 'identity_mismatch')
            bank = self.client.get('/wham/rate-limit-reset-credits', token, account_id, timeout)
            value = normalize_limits({**limits_payload(raw),
                'rateLimitResetCredits': reset_payload(bank)}, email)
            if not value.get('ok') or fingerprint(path) != original:
                raise RPCError('账号信息已变化，请重新打开详情', 'identity_mismatch')
            value['fetched_at'] = fetched_at
            self.record_limits(value)
            return bank

        bank = read()
        available = next((r for r in bank.get('credits') or [] if isinstance(r, dict)
                          and r.get('id') == credit_id and r.get('status') == 'available'), None)
        if not retrying and not available:
            raise RPCError('这次重置已不可用，请刷新详情', 'reset_credit')
        if not retrying:
            records[key] = {'credit_id': credit_id, 'request_id': request_id,
                            'status': 'pending', 'at': self.clock()}
            self._save(records)
        outcome = self.client.consume(token, account_id, credit_id, request_id, timeout)
        if outcome not in OUTCOMES:
            raise RPCError('重置结果未确认，请点击重试', 'reset_uncertain')
        records[key].update(status='complete', outcome=outcome)
        self._save(records)
        # A completed reset stays completed even when its follow-up GET fails.
        try:
            read()
        except Exception:
            return outcome
        return outcome
