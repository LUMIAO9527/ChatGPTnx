"""Bounded adapter for the existing desktop app-tools pipe (no new Core).

This is a private desktop protocol. Discover its advertised schema on each
connection and fail closed if the installed desktop changes it. Never retry a
write whose acknowledgement was lost.
"""
from __future__ import annotations

import json
import os
import re
import struct
import time
import uuid


MAX_FRAME = 8 * 1024 * 1024
PIPE_PREFIX = '\\\\.\\pipe\\codex-browser-use-'


class BridgeUnavailable(Exception):
    pass


class BridgeUncertain(Exception):
    """A side-effect request may already have reached the desktop."""


class Pipe:
    def __init__(self, path, timeout=2):
        import win32file
        import win32con
        self.handle = win32file.CreateFile(path, win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                         0, None, win32con.OPEN_EXISTING,
                                         win32con.FILE_FLAG_OVERLAPPED, None)
        self.timeout = timeout
        self.sequence = 0

    def close(self):
        self.handle.Close()

    def _io(self, payload, writing, deadline):
        import pywintypes
        import win32event
        import win32file
        op = pywintypes.OVERLAPPED()
        op.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            code, buffer = (win32file.WriteFile(self.handle, payload, op) if writing else
                            win32file.ReadFile(self.handle, payload, op))
            if code not in (0, 997):
                raise BridgeUnavailable('pipe_io')
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if code == 997 and win32event.WaitForSingleObject(op.hEvent, remaining) != 0:
                win32file.CancelIoEx(self.handle, op)
                # Wait for cancellation before releasing the OVERLAPPED buffer.
                try:
                    win32file.GetOverlappedResult(self.handle, op, True)
                except Exception:
                    pass
                raise BridgeUnavailable('pipe_timeout')
            length = win32file.GetOverlappedResult(self.handle, op, True)
            if length == 0:
                raise BridgeUnavailable('pipe_closed')
            return length if writing else bytes(buffer[:length])
        finally:
            op.hEvent.Close()

    def request(self, method, params, *, side_effect=False):
        self.sequence += 1
        message = json.dumps({'id': self.sequence, 'jsonrpc': '2.0', 'method': method,
                              'params': params}, ensure_ascii=False).encode('utf-8')
        if len(message) > MAX_FRAME:
            raise BridgeUnavailable('frame_too_large')
        packet = struct.pack('<I', len(message)) + message
        deadline = time.monotonic() + self.timeout
        try:
            sent = 0
            while sent < len(packet):
                sent += self._io(packet[sent:], True, deadline)
            def read_exact(size):
                data = bytearray()
                while len(data) < size:
                    data.extend(self._io(size - len(data), False, deadline))
                return data
            size, = struct.unpack('<I', read_exact(4))
            if not 0 < size <= MAX_FRAME:
                raise BridgeUnavailable('invalid_frame')
            reply = json.loads(read_exact(size))
            if reply.get('id') != self.sequence or reply.get('jsonrpc') != '2.0':
                raise BridgeUnavailable('invalid_reply')
            if 'error' in reply:
                raise BridgeUnavailable('desktop_rejected_request')
            return reply['result']
        except Exception as error:
            # Even an error response can follow a completed downstream action.
            if side_effect:
                raise BridgeUncertain('dispatch_outcome_unknown') from error
            raise BridgeUnavailable('bridge_read_failed') from error


def candidates():
    if os.name != 'nt':
        return []
    # The executor's endpoint is preferred, never a saved endpoint from before
    # account switching. Other app-owned pipes are probed with tools/list only.
    inherited = os.environ.get('CODEX_APP_TOOLS_PIPE_PATH', '')
    paths = [inherited] if inherited.startswith(PIPE_PREFIX) else []
    try:
        paths += ['\\\\.\\pipe\\' + name for name in os.listdir('\\\\.\\pipe\\')
                  if re.fullmatch(r'codex-browser-use-[0-9a-f-]{36}', name)]
    except OSError:
        pass
    return list(dict.fromkeys(paths))[:12]


def discover(required=None):
    required = required or {'send_message_to_thread': {'threadId', 'prompt'},
                            'read_thread': {'threadId'}}
    for path in candidates():
        pipe = None
        try:
            pipe = Pipe(path, timeout=.6)
            result = pipe.request('tools/list', {'threadStartKind': 'all'})
            catalog = {t.get('name'): t for t in result.get('tools', [])
                       if t.get('namespace') == 'codex_app'}
            if all(fields <= catalog.get(name, {}).get('inputSchema', {}).get('properties', {}).keys()
                   for name, fields in required.items()):
                pipe.timeout = 20
                return pipe
        except Exception:
            pass
        if pipe:
            pipe.close()
    raise BridgeUnavailable('desktop_bridge_unavailable')


def call_params(source_thread, source_turn, tool, arguments, call_id=None):
    return {'arguments': arguments, 'callerSource': 'codex',
            'callId': call_id or 'nx-' + str(uuid.uuid4()), 'namespace': 'codex_app',
            'threadId': source_thread, 'turnId': source_turn, 'tool': tool}


def text_result(result):
    if result.get('success') is not True:
        raise BridgeUnavailable('app_tool_failed')
    texts = [i['text'] for i in result.get('contentItems', []) if i.get('type') == 'inputText']
    if len(texts) != 1:
        raise BridgeUnavailable('invalid_tool_result')
    return json.loads(texts[0])


def dispatch_message(pipe, source, target, prompt):
    """One shared write path for automatic resume and the explicit self-check."""
    result = pipe.request('tools/call', call_params(
        source, 'nx-resume-' + str(uuid.uuid4()), 'send_message_to_thread',
        {'threadId': target, 'hostId': 'local', 'prompt': prompt}), side_effect=True)
    try:
        ack = text_result(result)
        if ack.get('threadId') != target:
            raise BridgeUncertain('invalid_dispatch_ack')
        return ack
    except Exception as error:
        raise BridgeUncertain('invalid_dispatch_ack') from error


def resume_existing(home, item, stop, log):
    """Dispatch once through the desktop; never touch the user's composer.

    The caller must be an explicitly configured, existing coordination thread.
    Never impersonate the target as its own sender or invent a source thread.
    """
    from pathlib import Path
    from .desktop_resume import latest_turn
    from .storage import fingerprint
    from .settings import valid_setting

    auth = Path(home) / 'auth.json'
    before = fingerprint(auth)
    if not before:
        return 'failed', 'account_guard_unavailable'
    try:
        settings_path = Path(item['settings_file'])
        settings = json.loads(settings_path.read_text(encoding='utf-8-sig')).get('settings', {})
        source = settings.get('resume_source_thread_id')
        if not source or not valid_setting('resume_source_thread_id', source):
            return 'failed', 'resume_source_unconfigured'
        if source == item['thread_id']:
            return 'failed', 'resume_source_is_target'
    except (OSError, ValueError, KeyError, AttributeError):
        return 'failed', 'account_guard_unavailable'
    try:
        pipe = discover()
    except BridgeUnavailable:
        return 'retry', 'desktop_bridge_unavailable'
    dispatched = False
    try:
        # A fresh desktop response is required, not just a window or pipe file.
        snapshot = text_result(pipe.request('tools/call', call_params(
            source, 'nx-read-' + str(uuid.uuid4()), 'read_thread',
            {'threadId': item['thread_id'], 'hostId': 'local', 'turnLimit': 1,
             'includeOutputs': False})))
        thread = snapshot.get('thread', {})
        turns = snapshot.get('turns', [])
        if thread.get('id') != item['thread_id'] or thread.get('kind') != 'codex':
            return 'failed', 'bridge_target_mismatch'
        if not turns:
            return 'retry', 'history_unavailable'
        if turns[0].get('id') != item['turn_id']:
            return 'done', 'newer_turn'
        if thread.get('status', {}).get('type') not in ('idle', 'notLoaded'):
            return 'retry', 'desktop_task_not_idle'
        if turns[0].get('status') not in ('failed', 'interrupted'):
            return 'retry', 'desktop_task_not_idle'
        if turns[0].get('status') == 'failed':
            # Do not resume arbitrary application/model failures. The local
            # normalized history and desktop latest-turn ID must agree.
            record = latest_turn(home, item['thread_id'])
            if not record or record['turn_id'] != item['turn_id']:
                return 'retry', 'history_unavailable'
            if (record.get('error') or {}).get('codexErrorInfo') != 'usageLimitExceeded':
                return 'failed', 'unrelated_failure'
        settings = json.loads(settings_path.read_text(encoding='utf-8-sig')).get('settings', {})
        if settings.get('resume_source_thread_id') != source:
            return 'failed', 'resume_source_unconfigured'
        if settings.get('task_continuation') is not True:
            return 'failed', 'continuation_disabled'
        message = settings.get('resume_message')
        if not valid_setting('resume_message', message):
            return 'failed', 'invalid_resume_message'
        current = latest_turn(home, item['thread_id'])
        if not current or current['turn_id'] != item['turn_id']:
            return ('done', 'newer_turn') if current else ('retry', 'history_unavailable')
        if stop.is_set():
            return 'retry', 'shutting_down'
        if fingerprint(auth) != before:
            return 'failed', 'account_changed'
        dispatched = True
        dispatch_message(pipe, source, item['thread_id'], recovery_message(message))
        log.info('desktop_bridge_dispatch acknowledged=true')
        for _ in range(75):
            after = latest_turn(home, item['thread_id'])
            if after and after['turn_id'] != item['turn_id']:
                return 'done', 'new_turn_observed'
            if stop.wait(.2):
                break
        return 'failed', 'start_not_observed'
    except Exception:
        # No native-button fallback: losing an ACK does not prove non-delivery.
        return ('failed', 'action_outcome_unknown') if dispatched else ('retry', 'desktop_bridge_unavailable')
    finally:
        pipe.close()


def recovery_message(message):
    """Return exactly the configured continuation text; add no hidden guidance."""
    return message


def explicit_selfcheck(source, target, report_path):
    """User-invoked diagnostic. Never entered by the automatic queue.

    Uses the packaged adapter's actual write path, but intentionally does not
    simulate a quota failure or alter task history/production settings.
    """
    from pathlib import Path
    from .desktop_resume import THREAD_ID
    from .storage import atomic_bytes
    if not all(THREAD_ID.fullmatch(v or '') for v in (source, target)) or source == target:
        raise ValueError('invalid diagnostic source/target')
    report = Path(report_path)
    # Exclusive, durable journal: invoking the same command again cannot resend.
    with report.open('x', encoding='utf-8') as stream:
        json.dump({'state': 'started', 'source': source, 'target': target}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    result = {'state': 'failed', 'source': source, 'target': target, 'sent': False}
    pipe = None
    try:
        pipe = discover()
        snapshot = text_result(pipe.request('tools/call', call_params(
            source, 'nx-selfcheck-read', 'read_thread',
            {'threadId': target, 'turnLimit': 1, 'includeOutputs': False})))
        thread = snapshot.get('thread', {})
        turns = snapshot.get('turns', [])
        if (thread.get('id') != target
                or thread.get('status', {}).get('type') not in ('idle', 'notLoaded')
                or not turns
                or turns[0].get('status') not in ('completed', 'failed', 'interrupted')):
            raise BridgeUnavailable('target_not_idle')
        result['previous_turn'] = snapshot['turns'][0]['id']
        prompt = ('这是用户明确授权的 ChatGPTnx 候选 EXE 发送路径自检，只执行一次。'
                  '不要继续原投递任务，不要填写、点击表单按钮、提交、刷新、关闭或新建页面。'
                  '请检查本轮直接提供的浏览器工具，先获取当前连接清单，再按原百威申请页及稳定扩展实例确认浏览器，'
                  '不要复用旧编号或绑定。按当前工具文档绑定原有标签页，只读读取并保留页面。'
                  '仅在本任务最终回复自检是否成功及具体阻塞，不向其他任务发送消息。')
        result['state'] = 'dispatching'
        atomic_bytes(report, json.dumps(result).encode())
        dispatch_message(pipe, source, target, prompt)
        result.update(state='acknowledged', sent=True)
    except BridgeUncertain:
        result.update(state='uncertain', sent=None)
    except Exception as error:
        result['error_type'] = type(error).__name__
    finally:
        if pipe:
            pipe.close()
        atomic_bytes(report, json.dumps(result).encode())
    return result
