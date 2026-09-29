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
    paths = [inherited] if re.fullmatch(re.escape(PIPE_PREFIX) + r'[0-9a-f-]{36}', inherited) else []
    try:
        paths += ['\\\\.\\pipe\\' + name for name in os.listdir('\\\\.\\pipe\\')
                  if re.fullmatch(r'codex-browser-use-[0-9a-f-]{36}', name)]
    except OSError:
        pass
    return list(dict.fromkeys(paths))


def discover(required=None):
    required = required or {'send_message_to_thread': {'threadId', 'prompt'},
                            'read_thread': {'threadId'}}
    paths = candidates()

    def compatible(pipe):
        result = pipe.request('tools/list', {'threadStartKind': 'all'})
        catalog = {t.get('name'): t for t in result.get('tools', [])
                   if isinstance(t, dict) and t.get('namespace') == 'codex_app'}
        return all(fields <= catalog.get(name, {}).get('inputSchema', {}).get('properties', {}).keys()
                   for name, fields in required.items())

    # The inherited endpoint belongs to the current desktop executor.  If it
    # advertises the required tools, use it immediately; stale helper pipes
    # from another window must not turn a valid current endpoint into a false
    # ambiguity.
    inherited = os.environ.get('CODEX_APP_TOOLS_PIPE_PATH', '')
    if paths and paths[0] == inherited:
        pipe = None
        try:
            pipe = Pipe(inherited, timeout=.6)
            if compatible(pipe):
                pipe.timeout = 20
                selected, pipe = pipe, None
                return selected
        except Exception:
            pass
        finally:
            if pipe:
                pipe.close()
        paths = paths[1:]

    selected = None
    try:
        for path in paths:
            pipe = None
            try:
                pipe = Pipe(path, timeout=.6)
                if compatible(pipe):
                    if selected is not None:
                        raise BridgeUnavailable('desktop_bridge_ambiguous')
                    pipe.timeout = 20
                    selected, pipe = pipe, None
            except BridgeUnavailable as error:
                if str(error) == 'desktop_bridge_ambiguous':
                    raise
            except Exception:
                pass
            finally:
                if pipe:
                    pipe.close()
        if selected is None:
            raise BridgeUnavailable('desktop_bridge_unavailable')
        return selected
    except Exception:
        if selected:
            selected.close()
        raise


def discover_when_ready(stop, auth_file, expected_auth, timeout=12, required=None):
    """Wait briefly for the restarted desktop bridge before any write occurs."""
    from .storage import fingerprint
    deadline = time.monotonic() + timeout
    while True:
        if stop.is_set():
            raise BridgeUnavailable('shutting_down')
        if fingerprint(auth_file) != expected_auth:
            raise BridgeUnavailable('account_changed')
        try:
            return discover(required)
        except BridgeUnavailable as error:
            if str(error) != 'desktop_bridge_unavailable' or time.monotonic() >= deadline:
                raise
        stop.wait(min(.35, max(0, deadline - time.monotonic())))


def call_params(source_thread, source_turn, tool, arguments, call_id=None):
    return {'arguments': arguments, 'callerSource': 'codex',
            'callId': call_id or 'nx-' + str(uuid.uuid4()), 'namespace': 'codex_app',
            'threadId': source_thread, 'turnId': source_turn, 'tool': tool}


def text_result(result):
    try:
        if not isinstance(result, dict) or result.get('success') is not True:
            raise ValueError('app_tool_failed')
        content = result.get('contentItems')
        if not isinstance(content, list):
            raise ValueError('invalid_tool_result')
        texts = [i.get('text') for i in content if isinstance(i, dict) and i.get('type') == 'inputText']
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise ValueError('invalid_tool_result')
        value = json.loads(texts[0])
        if not isinstance(value, dict):
            raise ValueError('invalid_tool_result')
        return value
    except (ValueError, TypeError) as error:
        raise BridgeUnavailable('invalid_tool_result') from error


def dispatch_message(pipe, source, target, prompt, *, call_id):
    """The sole write: the call ID is stable, but not assumed server-idempotent."""
    from .desktop_resume import THREAD_ID
    result = pipe.request('tools/call', call_params(
        source, call_id, 'send_message_to_thread',
        {'threadId': target, 'hostId': 'local', 'prompt': prompt}, call_id=call_id),
        side_effect=True)
    try:
        ack = text_result(result)
        if ack.get('threadId') != target:
            raise BridgeUncertain('invalid_dispatch_ack')
        new_turn = ack.get('turnId')
        if new_turn is not None and not THREAD_ID.fullmatch(str(new_turn)):
            raise BridgeUncertain('invalid_dispatch_ack')
        return ack
    except Exception as error:
        raise BridgeUncertain('invalid_dispatch_ack') from error


def resume_existing(home, item, stop, log, *, interrupted=False):
    """Send once for an eligible failed turn or interruption with no Continue."""
    import hashlib
    from pathlib import Path
    from .desktop_resume import latest_turn, continuation_guard, observe_start, THREAD_ID
    from .desktop_location import canonical_task
    from .resume_policy import message_resume_eligible
    from .storage import fingerprint
    from .settings import valid_setting

    if not all(THREAD_ID.fullmatch(str(item.get(k, ''))) for k in ('thread_id', 'turn_id')):
        return 'failed', 'invalid_task_id'
    before, reason = continuation_guard(home, item)
    if not before:
        return 'failed', reason
    auth = Path(home) / 'auth.json'
    try:
        settings_path = Path(item['settings_file'])
        def read_settings():
            document = json.loads(settings_path.read_text(encoding='utf-8-sig'))
            settings = document.get('settings') if isinstance(document, dict) else None
            if not isinstance(settings, dict):
                raise ValueError('invalid_settings')
            return settings
        settings = read_settings()
        source = settings.get('resume_source_thread_id')
        if not source or not valid_setting('resume_source_thread_id', source):
            return 'failed', 'resume_source_unconfigured'
        target = canonical_task(home, item['thread_id'])
        if not target:
            return 'failed', 'task_identity_unavailable'
        if source == target:
            return 'failed', 'resume_source_is_target'
        if canonical_task(home, source, allow_archived=True) != source:
            return 'failed', 'resume_source_unavailable'
        if settings.get('task_continuation') is not True:
            return 'failed', 'continuation_disabled'
        if not valid_setting('resume_message', settings.get('resume_message')):
            return 'failed', 'invalid_resume_message'
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return 'failed', 'account_guard_unavailable'
    pipe = None
    dispatched = False
    try:
        if stop.is_set():
            return 'failed', 'shutting_down'
        pipe = discover_when_ready(stop, auth, before)
        snapshot = text_result(pipe.request('tools/call', call_params(
            source, 'nx-read-' + str(uuid.uuid4()), 'read_thread',
            {'threadId': target, 'hostId': 'local', 'turnLimit': 1,
             'includeOutputs': False, 'maxOutputCharsPerItem': 0})))
        thread, turns = snapshot.get('thread'), snapshot.get('turns')
        if not isinstance(thread, dict) or thread.get('id') != target or thread.get('kind') != 'codex':
            return 'failed', 'bridge_target_mismatch'
        if not isinstance(turns, list) or len(turns) != 1 or not isinstance(turns[0], dict):
            return 'failed', 'history_unavailable'
        if turns[0].get('id') != item['turn_id']:
            return 'skipped', 'newer_turn'
        status = thread.get('status')
        expected_status = 'interrupted' if interrupted else 'failed'
        if (not isinstance(status, dict) or status.get('type') not in ('idle', 'notLoaded')
                or turns[0].get('status') != expected_status):
            return 'failed', 'desktop_task_not_idle'
        current = latest_turn(home, item['thread_id'])
        if not current:
            return 'failed', 'history_unavailable'
        if current['turn_id'] != item['turn_id']:
            return 'skipped', 'newer_turn'
        error = current.get('error')
        if interrupted:
            if current.get('status') not in ('interrupted', 'inProgress'):
                return 'failed', 'task_state_changed'
        elif current.get('status') != 'failed' or not message_resume_eligible(error):
            return 'failed', 'unrelated_failure'
        settings = read_settings()
        if settings.get('resume_source_thread_id') != source:
            return 'failed', 'resume_source_unconfigured'
        if settings.get('task_continuation') is not True:
            return 'failed', 'continuation_disabled'
        message = settings.get('resume_message')
        if not valid_setting('resume_message', message):
            return 'failed', 'invalid_resume_message'
        if canonical_task(home, item['thread_id']) != target:
            return 'failed', 'task_identity_unavailable'
        if stop.is_set():
            return 'failed', 'shutting_down'
        if fingerprint(auth) != before:
            return 'failed', 'account_changed'
        call_id = 'nx-' + hashlib.sha256(
            (item['thread_id'] + '\0' + item['turn_id']).encode('ascii')).hexdigest()
        dispatched = True
        ack = dispatch_message(pipe, source, target, message, call_id=call_id)
        log.info('desktop_bridge_dispatch acknowledged=true')
        if ack.get('turnId') == item['turn_id']:
            return 'failed', 'action_outcome_unknown'
        return observe_start(home, item, stop, expected_auth=before,
                             expected_turn=ack.get('turnId'))
    except Exception as error:
        if dispatched:
            return 'failed', 'action_outcome_unknown'
        reason = (str(error) if isinstance(error, BridgeUnavailable)
                  and str(error) in ('desktop_bridge_ambiguous', 'account_changed', 'shutting_down')
                  else 'desktop_bridge_unavailable')
        return 'failed', reason
    finally:
        if pipe:
            pipe.close()


def observe_bridge_start(pipe, home, source, target, item, stop, *, expected_auth,
                         expected_turn=None, allow_same_turn=False):
    """Confirm a new started turn from the same desktop that accepted the send."""
    from pathlib import Path
    from .desktop_resume import THREAD_ID
    from .resume_policy import turn_failure_reason
    from .storage import fingerprint
    for _ in range(75):
        if fingerprint(Path(home) / 'auth.json') != expected_auth:
            return 'failed', 'action_outcome_unknown'
        try:
            snapshot = text_result(pipe.request('tools/call', call_params(
                source, 'nx-observe-' + str(uuid.uuid4()), 'read_thread',
                {'threadId': target, 'hostId': 'local', 'turnLimit': 1,
                 'includeOutputs': False, 'maxOutputCharsPerItem': 0})))
        except Exception:
            return 'failed', 'action_outcome_unknown'
        turns = snapshot.get('turns')
        if snapshot.get('thread', {}).get('id') != target or not isinstance(turns, list):
            return 'failed', 'action_outcome_unknown'
        if len(turns) == 1 and isinstance(turns[0], dict):
            turn = turns[0]
            new_id = turn.get('id')
            if THREAD_ID.fullmatch(str(new_id)) and (new_id != item['turn_id'] or allow_same_turn):
                if expected_turn is not None and new_id != expected_turn:
                    return 'failed', 'action_outcome_unknown'
                item['observed_turn_id'] = new_id
                if turn.get('status') == 'failed':
                    return 'failed', turn_failure_reason(turn.get('error'))
                if turn.get('status') in ('inProgress', 'completed') and turn.get('startedAt'):
                    return 'done', ('new_turn_observed' if new_id != item['turn_id']
                                    else 'native_turn_resumed')
        if stop.wait(.2):
            return 'failed', 'action_outcome_unknown'
    return 'failed', 'start_not_observed'


def observe_native_start(home, item, stop, *, expected_auth):
    """Observe an interrupted turn after the native Continue button was clicked."""
    from pathlib import Path
    from .desktop_location import canonical_task
    try:
        settings = json.loads(Path(item['settings_file']).read_text(encoding='utf-8-sig'))['settings']
        source = settings['resume_source_thread_id']
        target = canonical_task(home, item['thread_id'])
        if not target or not source:
            return 'failed', 'action_outcome_unknown'
        pipe = discover_when_ready(stop, Path(home) / 'auth.json', expected_auth)
    except Exception:
        return 'failed', 'action_outcome_unknown'
    try:
        return observe_bridge_start(pipe, home, source, target, item, stop,
                                    expected_auth=expected_auth, allow_same_turn=True)
    finally:
        pipe.close()
