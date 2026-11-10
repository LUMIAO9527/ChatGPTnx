"""Drive the ChatGPT sign-in form one step at a time, then get out of the way.

The caller polls this once per tick while a login is pending. Each call may type
into at most one field; the stage is always established by reading the window
first, never by assuming the order the form will take.

Stop conditions are the point of this module. OpenAI inserts checks that cannot
be answered from stored credentials - a code mailed to an inbox the buyer does
not own, a phone number, a human check. Typing a TOTP code into an e-mail code
field spends an authentication attempt for nothing, so an unrecognised challenge
is reported, not guessed at.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .totp import TotpError, code_if_stable

POWERSHELL = 'powershell.exe'
CREATE_NO_WINDOW = 0x08000000
TIMEOUT = 25
UNKNOWN_LIMIT = 30.0          # seconds of an unclassifiable page before giving up
STAGE_ATTEMPTS = 3            # per field, per login
MIN_CODE_SECONDS = 8          # do not submit a code that expires mid-flight

# Failures that describe a moment, not a decision: the page is still settling,
# the window lost the foreground, the helper could not start. Retried a bounded
# number of times. Everything else is treated as a real answer and stops.
RETRYABLE = frozenset({'no_input', 'no_focus', 'not_foreground', 'user_active',
                       'stage_mismatch', 'no_target', 'no_window', 'not_sign_in',
                       'not_auth_surface',
                       'login_fill_unavailable', 'login_fill_empty',
                       'login_fill_unparsable'})

STOP_REASONS = {
    'phone': ('phone', '需要手机号验证，请手动完成后让程序自动保存'),
    'email_code': ('email_code', '验证码发到了邮箱，请手动完成后让程序自动保存'),
    'human_check': ('human_check', '需要人机验证，请手动完成后让程序自动保存'),
    'no_password': ('wrong_password', '没有保存这个账号的密码，请手动登录'),
    'no_secret': ('otp_rejected', '没有保存这个账号的 2FA 密钥，请手动输入验证码'),
    'otp_unrecognized': ('otp_rejected', '无法判断是哪一种验证码，已停下等待手动输入'),
    'not_sign_in': ('stopped', '登录窗口未就绪，稍后继续'),
    'timeout': ('timeout', '登录页结构无法识别，已停止自动填入'),
    'not_foreground': ('stopped', '登录窗口不在前台，已停止自动填入'),
    'user_active': ('stopped', '检测到正在操作键盘或鼠标，已暂停自动填入'),
    'no_window': ('stopped', '没有找到登录窗口'),
    'not_auth_surface': ('stopped', '当前窗口不是登录页，已停止自动填入'),
    'no_target': ('stopped', '没有找到输入框'),
    'no_focus': ('stopped', '输入框无法获得焦点'),
    'no_input': ('stopped', '键盘输入未送达'),
    'stage_mismatch': ('stopped', '页面已经切换，等待下一步'),
    'bad_payload': ('stopped', '填入参数无效'),
}


class FillError(OSError):
    """Safe to show: carries a result code, never a credential."""


def _run(script: Path, stage: str, payload: dict, *, timeout: int = TIMEOUT) -> dict:
    """Call the PowerShell helper with the payload on stdin, never on argv."""
    command = [POWERSHELL, '-NoLogo', '-NoProfile', '-NonInteractive',
               '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Stage', stage]
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    try:
        completed = subprocess.run(command, input=body, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, timeout=timeout,
                                   creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        raise FillError('login_fill_unavailable') from error
    text = completed.stdout.decode('utf-8-sig', errors='replace').strip()
    if not text:
        raise FillError('login_fill_empty')
    # The helper prints one object; tolerate stray host output before it.
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise FillError('login_fill_unparsable')


def probe(script: Path, *, runner=_run) -> dict:
    return runner(script, 'probe', {})


def _fill(script: Path, stage: str, payload: dict, *, runner=_run) -> dict:
    return runner(script, stage, payload)


def _stop(state: dict, reason: str) -> dict:
    code, message = STOP_REASONS.get(reason, ('stopped', '已停止自动填入'))
    state['stop'] = reason
    state['result'] = code
    state['message'] = message
    return {'action': 'stop', 'reason': reason, 'result': code, 'message': message}


def advance(script: Path, entry, state: dict | None = None, *,
            now: float | None = None, runner=_run) -> dict:
    """One probe plus at most one field. Mutates ``state`` in place.

    ``state`` keys: ``filled`` (per stage), ``attempts`` (per stage),
    ``unknown_since`` (float|None), ``stop`` (reason|None), ``result`` and
    ``message`` for the caller to surface.
    """
    moment = time.time() if now is None else now
    state = {} if state is None else state
    state.setdefault('filled', {})
    state.setdefault('attempts', {})

    if state.get('stop'):
        return {'action': 'stop', 'reason': state['stop'],
                'result': state.get('result', 'stopped'),
                'message': state.get('message', '')}

    try:
        observed = probe(script, runner=runner)
    except FillError as error:
        state['probe_failures'] = int(state.get('probe_failures', 0)) + 1
        if state['probe_failures'] < STAGE_ATTEMPTS:
            return {'action': 'wait', 'reason': str(error), 'retry': True}
        return _stop(state, str(error))
    state['probe_failures'] = 0

    step = str(observed.get('step') or 'unknown')
    hint = str(observed.get('hint') or 'none')

    # A challenge is reported before any typing, whatever field the page carries:
    # a phone box is an edit field too, and looks exactly like an e-mail box here.
    if hint == 'human_check':
        return _stop(state, 'human_check')
    if hint == 'phone':
        return _stop(state, 'phone')
    # The e-mail-code wording only settles the question on a code page; the
    # ordinary sign-in screen mentions the address without asking for a code.
    if hint == 'email_code' and step in ('otp', 'unknown'):
        return _stop(state, 'email_code')

    if step == 'unknown':
        if state.get('unknown_since') is None:
            state['unknown_since'] = moment
            return {'action': 'wait', 'step': step, 'hint': hint, 'reason': 'starting'}
        if moment - state['unknown_since'] >= UNKNOWN_LIMIT:
            return _stop(state, 'timeout')
        return {'action': 'wait', 'step': step, 'hint': hint, 'reason': 'unclassified'}

    state['unknown_since'] = None

    if step == 'otp' and hint != 'authenticator':
        return _stop(state, 'otp_unrecognized')

    if step not in ('launch', 'email', 'password', 'otp'):
        return {'action': 'wait', 'step': step, 'hint': hint, 'reason': 'no_stage'}

    if state['filled'].get(step):
        return {'action': 'wait', 'step': step, 'hint': hint, 'reason': 'already_filled'}

    attempts = int(state['attempts'].get(step, 0))
    if attempts >= STAGE_ATTEMPTS:
        return _stop(state, 'timeout')

    payload: dict[str, str] = {}
    if step == 'launch':
        pass
    elif step == 'email':
        payload['email'] = getattr(entry, 'email', '') or ''
        if not payload['email']:
            return _stop(state, 'not_sign_in')
    elif step == 'password':
        payload['password'] = getattr(entry, 'password', '') or ''
        if not payload['password']:
            return _stop(state, 'no_password')
    else:
        secret = getattr(entry, 'secret', '') or ''
        if not secret:
            return _stop(state, 'no_secret')
        try:
            code = code_if_stable(secret, minimum=MIN_CODE_SECONDS, at=moment)
        except TotpError:
            return _stop(state, 'no_secret')
        if code is None:
            # Wait for the next window rather than submit a nearly dead code.
            return {'action': 'wait', 'step': step, 'hint': hint, 'reason': 'code_expiring'}
        payload['code'] = code

    state['attempts'][step] = attempts + 1
    try:
        result = _fill(script, step, payload, runner=runner)
    except FillError as error:
        return _stop(state, str(error))

    if result.get('ok'):
        state['filled'][step] = True
        return {'action': 'filled', 'step': step, 'hint': hint,
                'clicked': bool(result.get('clicked')), 'reason': 'typed'}

    error = str(result.get('error') or 'stopped')
    if error in RETRYABLE and state['attempts'][step] < STAGE_ATTEMPTS:
        return {'action': 'wait', 'step': step, 'hint': hint,
                'reason': error, 'retry': True}
    return _stop(state, error)


def describe(reason: str) -> tuple[str, str]:
    """Map a stop reason to (vault result code, user facing message)."""
    return STOP_REASONS.get(reason, ('stopped', '已停止自动填入'))
