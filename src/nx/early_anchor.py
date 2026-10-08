"""Optional tiny requests to start unused Plus windows, without desktop login."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import http.client
import json
import ssl
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import uuid

from .credentials import read_credential_bytes
from .storage import atomic_bytes, read_json, identity, claims, fingerprint, account_identity_key
from .quota import normalize_limits, numeric, RPCError
from .quota_http import limits_payload
from .diagnostics_http import http_diagnostics
from .history_store import latest_database, read_only
from .task_metadata import task_metadata
from .desktop import chatgpt_running
from . import app_bridge

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
        self.may_have_run = False
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
        if response.status != 200:
            self._http_failure(response)
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise RPCError('额度响应无法识别', 'schema')
        return json.loads(raw)

    @staticmethod
    def _http_failure(response):
        error = RPCError('接力预热请求未完成', 'reauth_required' if response.status == 401 else response.status)
        wrapped = urllib.error.HTTPError('https://chatgpt.com/backend-api/wham/usage',
            response.status, '', response.headers, response)
        error.diagnostics = http_diagnostics(wrapped, time.time())
        raise error

    def send(self, before_send=lambda: True, dispatch=lambda: nullcontext(True)):
        if self.conn.sock is None:
            raise RPCError('查询连接已断开', 'network')
        body = request_body()
        # Coordinate only the packet write, never the response wait. Switching
        # and settings changes use the same service gate; GETs hold no gate.
        with dispatch() as ready:
            if not ready or not before_send():
                raise RPCError('工作或账号状态已变化', 'cancelled')
            self.conn.sock.settimeout(2)
            try:
                self.may_have_run = True
                self.conn.request('POST', '/backend-api/codex/responses', body=body,
                    headers={**self.headers, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
            finally:
                if self.conn.sock is not None:
                    self.conn.sock.settimeout(25)
        with self.conn.getresponse() as response:
            if response.status != 200:
                if response.status in (400, 401, 403, 404, 422, 429):
                    self.may_have_run = False  # Explicit rejection, no inference.
                self._http_failure(response)
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
    """Latest main turns are candidates; the live desktop confirms actual work."""
    def __init__(self, home, clock=time.time, running=chatgpt_running):
        self.home, self.running = home, running
        self.lock = threading.Lock()

    def poll(self):
        if not self.running():
            return []
        path = latest_database(self.home, 'thread_history_*.sqlite')
        if not path:
            return []
        with read_only(path) as db:
            rows = db.execute('SELECT t.thread_id,t.turn_id FROM thread_turns t '
                'JOIN (SELECT thread_id,MAX(rollout_ordinal) ordinal FROM thread_turns GROUP BY thread_id) latest '
                'ON latest.thread_id=t.thread_id AND latest.ordinal=t.rollout_ordinal '
                'WHERE t.status=? AND t.completed_at IS NULL ORDER BY t.started_at DESC',
                ('inProgress',)).fetchall()
        metadata = task_metadata(self.home, [row[0] for row in rows])
        return [{'thread_id': thread, 'turn_id': turn, 'canonical_id': metadata[thread]['canonical_id']}
                for thread, turn in rows if metadata.get(thread, {}).get('kind') == 'task'
                and metadata[thread].get('canonical_id')]

    def confirm(self):
        """Read status only, without opening a tab or sending a message."""
        with self.lock:
            events = self.poll()
            if not events:
                return False
            pipe = None
            try:
                pipe = app_bridge.discover({'read_thread': {'threadId'}})
                pipe.timeout = 3
                for event in events:
                    target = event['canonical_id']
                    snapshot = app_bridge.text_result(pipe.request('tools/call', app_bridge.call_params(
                        target, 'nx-preheat-read', 'read_thread', {'threadId': target, 'hostId': 'local',
                        'turnLimit': 1, 'includeOutputs': False, 'maxOutputCharsPerItem': 0})))
                    thread, turns = snapshot.get('thread') or {}, snapshot.get('turns') or []
                    if (thread.get('id') == target and thread.get('kind') == 'codex'
                        and (thread.get('status') or {}).get('type') == 'active'
                        and len(turns) == 1 and turns[0].get('id') == event['turn_id']
                        and turns[0].get('status') == 'inProgress'):
                        return event['thread_id'], event['turn_id']
                return False
            except app_bridge.BridgeUnavailable:
                return False
            finally:
                if pipe:
                    pipe.close()

    def still_working(self, confirmed):
        # The final cheap check runs inside the dispatch gate. A completed or
        # replaced turn cannot inherit a previous live confirmation.
        return any((e['thread_id'], e['turn_id']) == confirmed for e in self.poll())


class EarlyAnchor:
    def __init__(self, paths, current, record_limits=lambda value: None,
                 allowed=lambda email: True, backend=Backend, clock=time.time,
                 dispatch=lambda email: nullcontext(True), watcher=None, query=None):
        self.paths, self.current, self.record_limits = paths, current, record_limits
        self.allowed, self.backend, self.clock = allowed, backend, clock
        self.dispatch = dispatch
        self.query = query
        self.path = paths.data / 'early-anchor.json'
        self.lock = threading.RLock()
        self.watcher = watcher or WorkWatcher(paths.home, clock)
        self.tick_lock = threading.Lock()
        self.due = {}
        self.observed = {}
        self.was_working = False
        self.configuration = None

    def _save(self, records):
        atomic_bytes(self.path, json.dumps(records, ensure_ascii=False).encode(), private=True)

    def _records(self):
        records = read_json(self.path, {}) if not self.path.exists() else read_json(self.path)
        if not isinstance(records, dict) or any(not isinstance(v, dict) for v in records.values()):
            raise RPCError('预热记录无法识别', 'anchor_state')
        return records

    def observe_limits(self, value):
        """Reuse normal quota refreshes to notice a changed/restored window."""
        if not value.get('ok'):
            return
        five = next((w for w in value.get('windows') or [] if w.get('duration_mins') == 300), None)
        if not five:
            return
        email, signature = value['email'], (five.get('used'), five.get('resets_at'))
        with self.lock:
            if email in self.observed and self.observed[email] != signature:
                self.due[email] = 0
            self.observed[email] = signature

    def _quota(self, connection, email, account_id, original):
        if self.query and not self.query.preheat_status(email, consume=True)['ready']:
            raise RPCError('额度查询正在冷却', 'cancelled')
        raw = connection.quota()
        read_at = self.clock()
        if fingerprint(self.paths.snapshot(email)) != original:
            raise RPCError('查询期间账号已变化', 'identity_mismatch')
        if not isinstance(raw, dict) or raw.get('account_id') != account_id or raw.get('email', '').casefold() != email.casefold():
            raise RPCError('查询账号不一致', 'identity_mismatch')
        value = normalize_limits(limits_payload(raw), email)
        value['fetched_at'] = read_at
        rate = raw.get('rate_limit') or {}
        win = rate.get('primary_window') or {}
        remaining = numeric(win.get('reset_after_seconds'), 0, WINDOW)
        if raw.get('plan_type') == 'plus' and win.get('limit_window_seconds') == WINDOW and remaining is None:
            raise RPCError('计时窗口数据不完整', 'schema')
        if self.query:
            state = self.query.record_preheat_result(email)
            if not state['ready']:
                raise RPCError('额度查询正在暂停', state['error_code'])
        self.record_limits(value)
        self.observe_limits(value)
        return raw, rate, win

    def _schedule(self, email, at):
        with self.lock:
            self.due[email] = max(self.clock() + 1, at)

    def _resolve(self, email, key, previous, win):
        """Only stable server reset times prove a zero-percent window started."""
        now, reset = self.clock(), win['reset_at']
        if win['reset_after_seconds'] < WINDOW:
            if previous.get('status') == 'started':
                self._schedule(email, reset + 1)
                return {'status': 'already_started'}
            if previous.get('status') in ('pending', 'sent', 'uncertain', 'failed'):
                sample = previous.get('sample') or {}
                confirmed = sample.get('reset_at') == reset and now - sample.get('at', now) >= 3
                with self.lock:
                    records = self._records()
                    record = records[key]
                    if confirmed:
                        record.update(status='started', reset_at=reset)
                        record.pop('sample', None)
                    else:
                        record['checks'] = int(record.get('checks') or 0) + 1
                        record['sample'] = {'reset_at': reset, 'at': now}
                    self._save(records)
                self._schedule(email, reset + 1 if confirmed else now + (3 if record['checks'] < 3 else 60))
                return {'status': 'started' if confirmed else 'checking', 'reset_at': reset}
            self._schedule(email, reset + 1)
            return {'status': 'already_started'}
        if previous.get('status') in ('pending', 'sent', 'uncertain', 'failed'):
            deadline = numeric(previous.get('attempt_until') or previous.get('until'), 1) or now
            if now < deadline:
                checks = int(previous.get('checks') or 0) + 1
                with self.lock:
                    records = self._records()
                    records[key].update(checks=checks)
                    records[key].pop('sample', None)
                    self._save(records)
                self._schedule(email, min(deadline + 1, now + (3 if checks < 3 else 60)))
                return {'status': 'checking'}
        return None

    def run(self, email, confirmed_work=None):
        connection = None
        reserved = False
        usage = None
        try:
            if email == self.current() or not self.allowed(email):
                return {'status': 'skipped'}
            if self.query:
                state = self.query.preheat_status(email)
                if not state['ready']:
                    self._schedule(email, state.get('retry_at') or self.clock() + 60)
                    return {'status': 'skipped'}
            confirmed_work = confirmed_work or self.watcher.confirm()
            if not confirmed_work:
                self._schedule(email, self.clock() + 5)
                return {'status': 'skipped'}
            path = self.paths.snapshot(email)
            who = identity(path)
            auth = claims(path).get('https://api.openai.com/auth') or {}
            if who[0] != email or auth.get('chatgpt_plan_type') != 'plus':
                return {'status': 'skipped'}
            key, original = account_identity_key(path, email), fingerprint(path)
            with self.lock:
                previous = self._records().get(key, {})
            tokens = json.loads(read_credential_bytes(path).decode('utf-8-sig')).get('tokens') or {}
            if tokens.get('account_id') != who[1] or not tokens.get('access_token'):
                raise RPCError('账号凭据不完整', 'reauth_required')
            connection = self.backend(tokens['access_token'], who[1])
            raw, rate, win = self._quota(connection, email, who[1], original)
            week = rate.get('secondary_window') or {}
            if (raw.get('plan_type') != 'plus' or win.get('limit_window_seconds') != WINDOW
                or rate.get('allowed') is not True
                or win.get('used_percent') != 0 or (week.get('used_percent') or 0) >= 100):
                resets = [w.get('reset_at') for w in (win, week) if (w.get('used_percent') or 0) >= 100]
                self._schedule(email, max(resets, default=win.get('reset_at') or self.clock() + 300) + 1)
                return {'status': 'skipped'}
            result = self._resolve(email, key, previous, win)
            if result:
                return result
            def reserve():
                nonlocal reserved
                with self.lock:
                    if (email == self.current() or not self.allowed(email)
                        or fingerprint(path) != original or not self.watcher.still_working(confirmed_work)
                        or self.query and not self.query.preheat_status(email)['ready']):
                        return False
                    records = self._records()
                    # Another worker can have reserved while this GET was in flight.
                    latest = records.get(key, {})
                    if latest != previous:
                        return False
                    records[key] = {'status': 'pending', 'at': self.clock(), 'attempt_until': win['reset_at']}
                    self._save(records)
                    reserved = True
                    return (email != self.current() and self.allowed(email)
                            and fingerprint(path) == original and self.watcher.still_working(confirmed_work))

            usage = connection.send(reserve, lambda: self.dispatch(email))
            with self.lock:
                records = self._records()
                records[key].update(status='sent', usage=usage)
                self._save(records)
            connection.close(); connection = self.backend(tokens['access_token'], who[1])
            with self.lock:
                previous = self._records()[key]
            _, _, cw = self._quota(connection, email, who[1], original)
            self._resolve(email, key, previous, cw)
            return {'status': 'sent', 'usage': usage}
        except Exception as error:
            possible = usage is not None or (connection is not None and connection.may_have_run)
            if reserved:
                with self.lock:
                    records = self._records()
                    records[key].update(status='sent' if usage else 'uncertain' if possible else 'not_sent',
                                        error_code=getattr(error, 'code', 'network'))
                    self._save(records)
            code = getattr(error, 'code', None) or ('timeout' if isinstance(error, TimeoutError) else 'network')
            state = self.query.record_preheat_result(email, error) if self.query and code != 'cancelled' else {}
            retry = state.get('retry_at') or self.clock() + (3 if possible else 300 if code == 'reauth_required' else 30)
            self._schedule(email, retry)
            return {'status': 'sent' if usage else 'skipped' if code == 'cancelled' else 'failed', 'error_code': code}
        finally:
            if connection:
                connection.close()

    def tick(self, settings, busy=False):
        selection = tuple(settings.get('early_anchor_accounts') or [])
        configuration = bool(settings.get('early_anchor')), selection, self.current()
        if configuration != self.configuration:
            with self.lock:
                self.due.clear()
            self.configuration = configuration
        if not configuration[0] or not selection or busy or not self.tick_lock.acquire(blocking=False):
            return []
        try:
            working = bool(self.watcher.poll())
            if working and not self.was_working:
                with self.lock:
                    self.due.clear()
            self.was_working = working
            if not working:
                return []
            with self.lock:
                ready = [email for email in dict.fromkeys(selection)
                         if email != self.current() and self.due.get(email, 0) <= self.clock()
                         and self.allowed(email)]
            if not ready:
                return []
            confirmed_work = self.watcher.confirm()
            if not confirmed_work:
                for email in ready:
                    self._schedule(email, self.clock() + 5)
                return []
            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(lambda email: self.run(email, confirmed_work), ready))
        finally:
            self.tick_lock.release()
