"""Optional tiny requests to start unused Plus windows, without desktop login."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import ssl
import threading
import time
import urllib.parse
import urllib.request
import uuid

from .credentials import read_credential_bytes
from .storage import atomic_bytes, read_json, identity, claims, fingerprint, account_identity_key
from .quota import normalize_limits, RPCError
from .quota_http import limits_payload
from .history_store import latest_database, read_only
from .desktop_resume import desktop_task_events

MODEL = 'gpt-6-luna'
WINDOW = 18000


def request_body():
    return json.dumps({'model': MODEL, 'stream': True, 'store': False,
        'input': [{'role': 'developer', 'type': 'message', 'content': [
            {'type': 'input_text', 'text': 'Reply only OK.'}]},
            {'role': 'user', 'type': 'message', 'content': [{'type': 'input_text', 'text': 'OK'}]}],
        'tool_choice': 'auto', 'parallel_tool_calls': False,
        'reasoning': {'effort': 'low', 'context': 'all_turns'},
        'include': ['reasoning.encrypted_content'], 'text': {'verbosity': 'low'},
        'prompt_cache_key': str(uuid.uuid4())}, separators=(',', ':')).encode()


class Backend:
    """One verified HTTPS connection, one POST, zero request/stream retries."""
    def __init__(self, token, account_id):
        self.headers = {'Authorization': 'Bearer ' + token, 'ChatGPT-Account-Id': account_id,
                        'User-Agent': 'ChatGPTnx/1.0.1', 'Originator': 'ChatGPTnx'}
        proxy = urllib.request.getproxies().get('https')
        if proxy and not urllib.request.proxy_bypass('chatgpt.com'):
            url = urllib.parse.urlsplit(proxy if '://' in proxy else 'http://' + proxy)
            if url.scheme != 'http' or url.username or url.password:
                raise RPCError('当前代理配置不支持提前计时', 'anchor_proxy')
            self.conn = http.client.HTTPSConnection(url.hostname, url.port or 80,
                                                    timeout=25, context=ssl.create_default_context())
            self.conn.set_tunnel('chatgpt.com', 443)
        else:
            self.conn = http.client.HTTPSConnection('chatgpt.com', 443,
                                                    timeout=25, context=ssl.create_default_context())

    def quota(self):
        self.conn.request('GET', '/backend-api/wham/usage', headers={**self.headers, 'Accept': 'application/json'})
        response = self.conn.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200:
            raise RPCError('提前计时的额度查询未完成', 'reauth_required' if response.status == 401 else 'anchor_query')
        if len(raw) > 2 * 1024 * 1024:
            raise RPCError('额度响应无法识别', 'schema')
        return json.loads(raw)

    def send(self):
        if self.conn.sock is None:
            raise RPCError('查询连接已断开', 'network')
        self.conn.request('POST', '/backend-api/codex/responses', body=request_body(),
                          headers={**self.headers, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
        with self.conn.getresponse() as response:
            if response.status != 200:
                raise RPCError('提前计时请求未完成', 'reauth_required' if response.status == 401 else 'anchor_request')
            deadline = time.monotonic() + 60
            total, parts = 0, []
            while time.monotonic() < deadline:
                line = response.readline(65537)
                total += len(line)
                if not line or len(line) > 65536 or total > 256 * 1024:
                    raise RPCError('请求未完整返回', 'anchor_incomplete')
                if line.startswith(b'data:'):
                    parts.append(line[5:].strip())
                elif not line.strip() and parts:
                    event = json.loads(b'\n'.join(parts)); parts = []
                    if event.get('type') in ('error', 'response.failed', 'response.incomplete'):
                        raise RPCError('提前计时请求未完成', 'anchor_request')
                    if event.get('type') == 'response.completed':
                        result = event.get('response') or {}
                        usage = result.get('usage') or {}
                        if result.get('status') != 'completed' or type(usage.get('total_tokens')) is not int:
                            raise RPCError('请求未完整返回', 'anchor_incomplete')
                        return {key: usage[key] for key in ('input_tokens', 'output_tokens', 'total_tokens')
                                if type(usage.get(key)) is int}
            raise RPCError('提前计时请求超时', 'timeout')

    def close(self):
        self.conn.close()


class WorkWatcher:
    """Read only start/status metadata. Completed old work and subagents don't trigger."""
    def __init__(self, home, clock=time.time):
        self.home, self.clock = home, clock
        self.cursor, self.seen = int(clock()), set()

    def poll(self):
        path = latest_database(self.home, 'thread_history_*.sqlite')
        if not path:
            return []
        now = int(self.clock())
        with read_only(path) as db:
            rows = db.execute('SELECT thread_id,turn_id,started_at,status FROM thread_turns '
                'WHERE started_at>=? OR (status=? AND completed_at IS NULL AND started_at>=?) '
                'ORDER BY started_at DESC LIMIT 128', (self.cursor, 'inProgress', now - 86400)).fetchall()
        events = desktop_task_events(self.home, [
            {'thread_id': thread, 'turn_id': turn, 'started_at': started}
            for thread, turn, started, status in rows if status in ('inProgress', 'completed')
            and (thread, turn) not in self.seen])
        self.seen.update((e['thread_id'], e['turn_id']) for e in events)
        if rows:
            newest = max(int(r[2] or 0) for r in rows)
            if newest > self.cursor:
                self.cursor = newest
                self.seen = {key for key in self.seen if any((r[0], r[1]) == key
                             and (r[2] == newest or r[3] == 'inProgress') for r in rows)}
        return events


class EarlyAnchor:
    def __init__(self, paths, current, record_limits=lambda value: None,
                 allowed=lambda email: True, backend=Backend, clock=time.time):
        self.paths, self.current, self.record_limits = paths, current, record_limits
        self.allowed, self.backend, self.clock = allowed, backend, clock
        self.path = paths.data / 'early-anchor.json'
        self.lock = threading.RLock()
        self.watcher = WorkWatcher(paths.home, clock)
        self.configuration = None

    def _save(self, records):
        atomic_bytes(self.path, json.dumps(records, ensure_ascii=False).encode(), private=True)

    def run(self, email):
        connection = None
        reserved = False
        try:
            if email == self.current() or not self.allowed(email):
                return {'status': 'skipped'}
            path = self.paths.snapshot(email)
            who = identity(path)
            auth = claims(path).get('https://api.openai.com/auth') or {}
            if who[0] != email or auth.get('chatgpt_plan_type') != 'plus':
                return {'status': 'skipped'}
            key, original = account_identity_key(path, email), fingerprint(path)
            with self.lock:
                previous = read_json(self.path, {}).get(key, {})
                if previous.get('until', 0) > self.clock():
                    return {'status': 'already_started'}
            tokens = json.loads(read_credential_bytes(path).decode('utf-8-sig')).get('tokens') or {}
            if tokens.get('account_id') != who[1] or not tokens.get('access_token'):
                raise RPCError('账号凭据不完整', 'reauth_required')
            connection = self.backend(tokens['access_token'], who[1])
            raw = connection.quota()
            if raw.get('account_id') != who[1] or raw.get('email', '').casefold() != email.casefold():
                raise RPCError('查询账号不一致', 'identity_mismatch')
            self.record_limits(normalize_limits(limits_payload(raw), email))
            rate = raw.get('rate_limit') or {}
            win, week = rate.get('primary_window') or {}, rate.get('secondary_window') or {}
            if (raw.get('plan_type') != 'plus' or win.get('limit_window_seconds') != WINDOW
                or rate.get('allowed') is False
                or win.get('used_percent') != 0 or (week.get('used_percent') or 0) >= 100
                or win.get('reset_after_seconds') != WINDOW):
                return {'status': 'already_started' if win.get('used_percent') == 0 else 'skipped'}
            if (email == self.current() or not self.allowed(email) or fingerprint(path) != original):
                return {'status': 'skipped'}
            with self.lock:
                records = read_json(self.path, {})
                if records.get(key, {}).get('until', 0) > self.clock():
                    return {'status': 'already_started'}
                records[key] = {'status': 'pending', 'at': self.clock(), 'until': self.clock() + WINDOW}
                self._save(records)  # Persist before sending; uncertain outcomes never retry this window.
                reserved = True
            usage = connection.send()
            with self.lock:
                records = read_json(self.path, {})
                records[key].update(status='sent', usage=usage)
                self._save(records)
            connection.close(); connection = self.backend(tokens['access_token'], who[1])
            confirmation = connection.quota()
            if confirmation.get('account_id') != who[1] or confirmation.get('email', '').casefold() != email.casefold():
                raise RPCError('查询账号不一致', 'identity_mismatch')
            self.record_limits(normalize_limits(limits_payload(confirmation), email))
            cw = (confirmation.get('rate_limit') or {}).get('primary_window') or {}
            confirmed = cw.get('reset_after_seconds', WINDOW) < WINDOW
            with self.lock:
                records = read_json(self.path, {})
                records[key].update(status='started' if confirmed else 'sent', reset_at=cw.get('reset_at'))
                self._save(records)
            return {'status': 'started' if confirmed else 'sent', 'usage': usage, 'reset_at': cw.get('reset_at')}
        except Exception as error:
            if reserved:
                with self.lock:
                    records = read_json(self.path, {})
                    records[key].update(status='sent' if records[key].get('usage') else 'failed',
                                        error_code=getattr(error, 'code', 'network'))
                    self._save(records)
            return {'status': 'sent' if reserved and records[key].get('usage') else 'failed',
                    'error_code': getattr(error, 'code', 'network')}
        finally:
            if connection:
                connection.close()

    def tick(self, settings, busy=False):
        selection = tuple(settings.get('early_anchor_accounts') or [])
        configuration = bool(settings.get('early_anchor')), selection, self.current()
        if configuration != self.configuration:
            self.watcher = WorkWatcher(self.paths.home, self.clock)
            self.configuration = configuration
        if not configuration[0] or not selection or busy or not self.watcher.poll():
            return []
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(self.run, dict.fromkeys(selection)))
