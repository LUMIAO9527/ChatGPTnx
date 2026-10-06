"""Portable paths, atomic state, credential metadata, and reversible accounts.

Only allow-listed metadata crosses the UI bridge. Never return token strings.
JWT claims are decoded locally, NOT validated; they are cached hints only.
"""
from __future__ import annotations
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .settings import DEFAULTS, normalize_settings
from .credentials import (assert_safe_path, credential_store_lock, read_credential_bytes,
                          secure_path, write_credential_bytes)


def autostart_enabled_safe() -> bool:
    """Read the HKCU Run entry without importing desktop (tests run headless)."""
    if os.name != 'nt':
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key, 'ChatGPTnx')
            return True
    except OSError:
        return False

def atomic_bytes(path: Path, data: bytes, *, private=False) -> None:
    if private:
        assert_safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('xb') as f:
            if private:
                secure_path(tmp)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # Windows readers do not always share delete access.  A status monitor,
        # antivirus scanner, or backup process can therefore block the atomic
        # replacement for a few milliseconds even though neither file is bad.
        # Preserve atomicity and retry the same replacement; never fall back to
        # an in-place write that could expose partial JSON or credentials.
        delays = (0, .01, .02, .04, .08, .16)
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == len(delays) - 1:
                    raise
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return copy.deepcopy(default)

def load_owned_document(path: Path):
    """Return a JSON object + optional recovery path; preserve invalid bytes.

    Access failures propagate. Only a syntactically corrupt document is reset,
    and only after its exact bytes have been safely copied to recovery/.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    try:
        def reject_constant(value):
            raise ValueError('Non-finite JSON number')
        document = json.loads(raw.decode('utf-8-sig'), parse_constant=reject_constant)
        if not isinstance(document, dict):
            raise ValueError('Expected an object')
        return document, None
    except (UnicodeError, ValueError):
        recovery = path.parent / 'recovery' / f'{path.stem}-{time.time_ns()}.bad'
        atomic_bytes(recovery, raw)
        # These are metadata journals, never auth/snapshot files. Keep 5 copies
        # per document; do not prune credential transaction recovery backups.
        for old in sorted(recovery.parent.glob(path.stem + '-*.bad'))[:-5]:
            try:
                old.unlink()
            except OSError:
                pass
        return {}, recovery

def safe_email(email: str) -> str:
    if not isinstance(email, str) or len(email) > 200 or not re.fullmatch(r'[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+', email):
        raise ValueError('账号标识不合法')
    return email

def fingerprint(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

# get_data is called often while the panel is visible.  Parsing every snapshot's
# JSON/JWT on every poll caused visible stutter on machines with several accounts.
# Cache only decoded metadata and invalidate by atomic-file stat signature; raw
# credential/token strings never leave this module.
_credential_cache_lock = threading.RLock()
_credential_cache: dict[str, tuple[tuple[int, ...] | None, dict, dict]] = {}

def _credential_record(path: Path) -> tuple[dict, dict]:
    try:
        stat = path.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except OSError:
        signature = None
    key = str(path)
    with _credential_cache_lock:
        cached = _credential_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1], cached[2]
    try:
        data = json.loads(read_credential_bytes(path).decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    payload = {}
    try:
        token = data.get('tokens') or {}
        token = token if isinstance(token, dict) else {}
        raw = token.get('id_token', '')
        piece = raw.split('.')[1]
        obj = json.loads(base64.urlsafe_b64decode(piece + '=' * (-len(piece) % 4)))
        if isinstance(obj, dict):
            payload = obj
    except (TypeError, ValueError, IndexError, KeyError, AttributeError):
        payload = {}
    with _credential_cache_lock:
        _credential_cache[key] = (signature, data, payload)
    return data, payload

def claims(path: Path) -> dict:
    return _credential_record(path)[1]

def identity(path: Path) -> tuple[str | None, str | None]:
    data, info = _credential_record(path)
    token = data.get('tokens') or {}
    token = token if isinstance(token, dict) else {}
    auth = info.get('https://api.openai.com/auth') or {}
    auth = auth if isinstance(auth, dict) else {}
    email = info.get('email')
    workspace = token.get('account_id') or data.get('account_id') or auth.get('chatgpt_account_id')
    return email if isinstance(email,str) else None, workspace if isinstance(workspace,str) else None

def account_identity_key(path: Path, email: str) -> str:
    """Opaque deduplication key. User+workspace, not workspace alone."""
    _, payload = _credential_record(path)
    auth = payload.get('https://api.openai.com/auth') or {}
    auth = auth if isinstance(auth, dict) else {}
    workspace = identity(path)[1]
    subject = payload.get('sub')
    stable = f'{subject}|{workspace}' if subject and workspace else email.casefold()
    return hashlib.sha256(stable.encode('utf-8')).hexdigest()


def activity_identity_key(path: Path, email: str) -> str:
    """Conservative user-level dedup: do not sum a user's workspace copies."""
    subject = _credential_record(path)[1].get('sub')
    return hashlib.sha256(('activity:' + str(subject or email.casefold())).encode('utf-8')).hexdigest()


def timestamp(value) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value) if 946684800 <= value <= 7258118400 else None
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                return None  # no invented timezone
            return timestamp(dt.timestamp())
    except (ValueError, OverflowError, OSError):
        pass
    return None

def credential_metadata(path: Path) -> dict:
    payload = claims(path)
    auth = payload.get('https://api.openai.com/auth') or {}
    auth = auth if isinstance(auth, dict) else {}
    # Experimental metadata, never interpreted as a verified billing expiry.
    until = timestamp(auth.get('chatgpt_subscription_active_until'))
    expiry = timestamp(payload.get('exp'))
    try:
        saved_at = int(path.stat().st_mtime)
    except OSError:
        saved_at = None
    return {'snapshot_at': saved_at, 'id_token_expires_at': expiry,
            'subscription': {'until': until, 'source': 'credential_hint' if until else 'unknown',
                             'verified': False, 'observed_at': saved_at}}

class Paths:
    def __init__(self, root: Path, codex_home: Path | None = None, resource_root: Path | None = None):
        self.root = root.resolve()
        self.resources = (resource_root or root).resolve()
        self.data = self.root / '_data'
        self.snapshots = self.root / 'snapshots'
        self.order = self.root / 'accounts.txt'
        self.home = (codex_home or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))).expanduser().resolve()
        self.auth = self.home / 'auth.json'
        self.ps1 = self.resources / 'switch_account.ps1'
        self.desktop_resume_ps1 = self.resources / 'continue_in_desktop.ps1'
        self.data.mkdir(parents=True, exist_ok=True)

    def snapshot(self, email: str) -> Path:
        return self.snapshots / (safe_email(email) + '.json')

class State:
    def __init__(self, paths: Paths):
        self.path = paths.data / 'state.json'
        self.lock = threading.RLock()
        existing, self.recovery_path = load_owned_document(self.path)
        original = copy.deepcopy(existing)
        allowed_state = {'settings', 'cache', 'account_meta', 'usage', 'usage_revision',
                         'adding', 'reauth', 'subscriptions', 'hotkeys', 'reset_expiry_notices', 'relay_wait'}
        self.value = {key: value for key, value in existing.items() if key in allowed_state}
        saved_settings = existing.get('settings', {})
        saved_settings = saved_settings if isinstance(saved_settings, dict) else {}
        self.value['settings'] = normalize_settings(saved_settings)
        if self.recovery_path:
            self.value['settings'].update(auto_relay=False, task_continuation=False)
        self.value.setdefault('cache', {'updated': None, 'current': None, 'accounts': []})
        self.value.setdefault('account_meta', {})
        self.value.setdefault('usage', {})
        self.value.setdefault('usage_revision', 0)
        self.value.setdefault('adding', None)
        self.value.setdefault('reauth', None)
        waiting = self.value.get('relay_wait')
        if (self.recovery_path or not isinstance(waiting, dict)
                or not isinstance(waiting.get('id'), str)
                or not re.fullmatch(r'[0-9a-f]{32}', waiting['id'])
                or any(not isinstance(waiting.get(key), str) or not waiting[key]
                       for key in ('email', 'origin'))
                or waiting['email'] == waiting['origin']):
            waiting = None
        self.value['relay_wait'] = {key: waiting[key] for key in ('id', 'email', 'origin')} if waiting else None
        self.value.setdefault('subscriptions', {})
        self.value.setdefault('hotkeys', {})
        notices = self.value.get('reset_expiry_notices', {})
        self.value['reset_expiry_notices'] = {k: v for k, v in notices.items()
            if isinstance(k, str) and len(k) == 64 and type(v) is int and 0 < v <= 253402300799} \
            if isinstance(notices, dict) else {}
        # Shape-check caches and workflow state before callers dereference them.
        for key in ('account_meta', 'usage', 'subscriptions'):
            raw = self.value[key]
            self.value[key] = {k: v for k, v in raw.items()
                               if isinstance(k, str) and isinstance(v, dict)} if isinstance(raw, dict) else {}
        raw = self.value['hotkeys']
        self.value['hotkeys'] = {k: v for k, v in raw.items() if isinstance(k, str) and
            (v is None or isinstance(v, str) and re.fullmatch(
                r'(?:ctrl\+alt|ctrl\+shift|alt\+shift|ctrl\+alt\+shift)\+[1-9]', v))} if isinstance(raw, dict) else {}
        if type(self.value['usage_revision']) is not int or self.value['usage_revision'] < 0:
            self.value['usage_revision'] = 0
        cache = self.value['cache']
        if not isinstance(cache, dict):
            cache = {}
        rows = cache.get('accounts')
        rows = [v for v in rows if isinstance(v, dict) and isinstance(v.get('email'), str)] if isinstance(rows, list) else []
        from .quota_policy import sanitize_cached_account
        self.value['cache'] = {'updated': cache.get('updated') if type(cache.get('updated')) in (int, float) and 0 <= cache['updated'] < 253402300800 else None,
                              'current': cache.get('current') if isinstance(cache.get('current'), str) else None,
                              'accounts': [sanitize_cached_account(v) for v in rows]}
        for key in ('adding', 'reauth'):
            flow = self.value[key]
            if flow is not None and not isinstance(flow, dict):
                self.value[key] = {'phase': 'needs_recovery', 'previous': None}
        for value in self.value['account_meta'].values():
            if not isinstance(value.get('alias', ''), str):
                value['alias'] = ''
            if not isinstance(value.get('subscription_date'), (str, type(None))):
                value['subscription_date'] = None
        if self.value['settings'].get('autostart') != autostart_enabled_safe():
            # The registry is the source of truth; sync the mirrored setting.
            self.value['settings']['autostart'] = autostart_enabled_safe()
        if self.value != original:
            atomic_bytes(self.path, json.dumps(self.value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))

    def get(self, key, default=None):
        with self.lock:
            return copy.deepcopy(self.value.get(key, default))

    def update(self, **values):
        with self.lock:
            candidate = {**self.value, **copy.deepcopy(values)}
            atomic_bytes(self.path, json.dumps(candidate, ensure_ascii=False, indent=2,
                                               allow_nan=False).encode('utf-8'))
            self.value = candidate

    def change(self, key, transform):
        """Atomic read-modify-write, including in-memory commit after disk success."""
        with self.lock:
            value = transform(copy.deepcopy(self.value.get(key)))
            self.update(**{key: value})
            return copy.deepcopy(value)

    def setting(self, **values):
        with self.lock:
            settings = {**self.value['settings'], **values}
            self.update(settings=settings)
            return copy.deepcopy(settings)

class Accounts:
    def __init__(self, paths: Paths):
        self.paths = paths
        self._order_lock = threading.RLock()
        self._order_signature = None
        self._order_values = []

    def all(self) -> list[str]:
        try:
            stat = self.paths.order.stat()
            signature = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except FileNotFoundError:
            signature = None
        with self._order_lock:
            if signature == self._order_signature:
                return list(self._order_values)
        if signature is None:
            result = []
        else:
            text = self.paths.order.read_text(encoding='utf-8-sig')
            result = []
            seen = set()
            for row in text.splitlines():
                row = row.strip()
                if row and not row.startswith('#'):
                    safe_email(row)
                    folded = row.casefold()
                    if folded not in seen:
                        seen.add(folded); result.append(row)
        with self._order_lock:
            self._order_signature, self._order_values = signature, list(result)
        return result

    def current(self) -> str | None:
        email, account_id = identity(self.paths.auth)
        if not email:
            return None
        # A workspace ID identifies a workspace, not a person. Two members can
        # share it; only match a roster email AND, when present, its workspace.
        for item in self.all():
            if item.casefold() != email.casefold():
                continue
            snap_email, snap_id = identity(self.paths.snapshot(item))
            if account_id and snap_id and account_id != snap_id:
                continue
            if snap_email and snap_email.casefold() != email.casefold():
                continue
            return item
        return None

    def write(self, emails: list[str]):
        for email in emails:
            safe_email(email)
        try:
            comments = [line for line in self.paths.order.read_text(encoding='utf-8-sig').splitlines()
                        if line.strip().startswith('#')]
        except FileNotFoundError:
            comments = ['# 行序 = 面板顺序 = 全局热键序号；不要放入凭据。']
        atomic_bytes(self.paths.order, ('\n'.join(comments + emails) + '\n').encode('utf-8'), private=True)
        with self._order_lock:
            self._order_signature = None
            self._order_values = []

    def append(self, email: str):
        with self._order_lock:
            emails = self.all()
            safe_email(email)
            if email.casefold() not in {v.casefold() for v in emails}:
                self.write(emails + [email])

    def activate(self, email: str):
        """Make one identity active and end any older archived state for it.

        A fresh active snapshot must already exist before this is called. If an
        old archive cannot be removed, the account remains correctly active and
        archived() hides that stale storage record.
        """
        with credential_store_lock(self.paths.snapshots):
            self.append(email)
            removed = self.paths.snapshots / 'removed'
            for path in removed.glob('*.json'):
                archived_email, _ = identity(path)
                if archived_email and archived_email.casefold() == email.casefold():
                    try:
                        assert_safe_path(path).unlink()
                    except OSError:
                        pass

    def archive(self, email: str) -> str:
        with credential_store_lock(self.paths.snapshots):
            return self._archive(email)

    def _archive(self, email: str) -> str:
        if email not in self.all():
            raise ValueError('账号不在清单中')
        if self.current() == email:
            raise ValueError('请先切换到其他账号，再归档当前账号')
        source = assert_safe_path(self.paths.snapshot(email))
        target = assert_safe_path(self.paths.snapshots / 'removed' / f'{email}.{int(time.time())}.{uuid.uuid4().hex[:8]}.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        secure_path(target.parent)
        moved = False
        try:
            if source.exists():
                info = source.stat()
                write_credential_bytes(source, read_credential_bytes(source),
                                       preserve_times=(info.st_atime_ns, info.st_mtime_ns))
                os.replace(source, target)
                moved = True
            self.write([v for v in self.all() if v != email])
        except Exception:
            if moved:
                os.replace(target, source)
            raise
        return target.name if moved else ''

    def archived(self) -> list[dict]:
        result = []
        active = {email.casefold() for email in self.all()}
        for path in sorted((self.paths.snapshots / 'removed').glob('*.json'), reverse=True):
            email, _ = identity(path)
            if email and email.casefold() not in active:
                result.append({'key': path.name, 'email': email, 'archived_at': int(path.stat().st_mtime)})
        return result

    def restore(self, key: str):
        with credential_store_lock(self.paths.snapshots):
            return self._restore(key)

    def _restore(self, key: str):
        if not isinstance(key, str) or Path(key).name != key or '/' in key or '\\' in key:
            raise ValueError('归档标识不合法')
        source = assert_safe_path(self.paths.snapshots / 'removed' / key)
        email, _ = identity(source)
        safe_email(email)
        target = assert_safe_path(self.paths.snapshot(email))
        if email.casefold() in {v.casefold() for v in self.all()} or target.exists():
            raise ValueError('已有同名账号；不会覆盖现有凭据')
        info = source.stat()
        write_credential_bytes(source, read_credential_bytes(source),
                               preserve_times=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(source, target)
        try:
            self.append(email)
        except Exception:
            os.replace(target, source)
            raise
        return email
