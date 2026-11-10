"""Encrypted account vault: sign-in credentials used only to refill the login form.

Stored through the same protection as the credential snapshots
(``write_credential_bytes``): DPAPI for the current Windows user, a private
DACL, an atomic replace, and a read-back comparison before the write commits.

Contents are ordinary account material typed by the user - e-mail, password and
a TOTP secret. No token, cookie or auth.json content is ever written here, and
nothing in this module is allowed to log a value it holds.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

from .credentials import CredentialProtectionError, read_credential_bytes, write_credential_bytes
from .totp import normalize_secret, looks_like_secret, TotpError

SCHEMA = 'chatgptnx_vault'
VERSION = 1
MAX_ENTRIES = 200
MAX_PASSWORD = 512
MAX_LABEL = 64

# Login outcomes recorded for troubleshooting. They describe the shape of the
# attempt, never a credential.
RESULTS = ('ok', 'email_code', 'phone', 'human_check', 'wrong_password',
           'otp_rejected', 'timeout', 'stopped', 'identity_mismatch')


class VaultError(OSError):
    """Safe to show: messages describe the problem, never the stored value."""


@dataclass(frozen=True)
class Entry:
    email: str
    password: str = field(default='', repr=False)
    secret: str = field(default='', repr=False)
    exchange_code: str = field(default='', repr=False)
    exchange_url: str = field(default='', repr=False)
    recovery_codes: str = field(default='', repr=False)
    secret_source: str = 'imported'
    migrated_at: float = 0.0
    label: str = ''
    added_at: float = 0.0
    last_login_at: float = 0.0
    last_result: str = ''

    def public(self) -> dict:
        """Everything the UI may show. Secrets are not included."""
        return {'email': self.email, 'label': self.label,
                'has_password': bool(self.password), 'has_secret': bool(self.secret),
                'has_exchange': bool(self.exchange_code or self.exchange_url),
                'has_recovery': bool(self.recovery_codes),
                'secret_source': self.secret_source, 'migrated_at': self.migrated_at,
                'added_at': self.added_at, 'last_login_at': self.last_login_at,
                'last_result': self.last_result}


def _clean_email(value: object) -> str:
    if not isinstance(value, str):
        raise VaultError('邮箱不能为空')
    email = value.strip()
    if not email or '@' not in email or len(email) > 254 or any(ch.isspace() for ch in email):
        raise VaultError('邮箱格式不正确')
    return email


def _clean_password(value: object) -> str:
    if value is None or value == '':
        return ''
    if not isinstance(value, str) or len(value) > MAX_PASSWORD:
        raise VaultError('密码格式不正确')
    return value


def _clean_secret(value: object) -> str:
    if not value:
        return ''
    return normalize_secret(value)


def _text(value, maximum=4096):
    if not isinstance(value, str) or len(value) > maximum:
        raise VaultError('账号资料格式不正确')
    return value.strip()


def _url(value):
    text = _text(value)
    if text:
        try:
            parsed = urlparse(text)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError()
        except ValueError:
            raise VaultError('兑换链接格式不正确') from None
    return text


def material_fields(material='', exchange_url=''):
    """Read supplied account material locally; preserve opaque redemption data."""
    text = _text(material)
    link = _url(exchange_url)
    fields = {}
    if text.lower().startswith(('https://', 'http://')):
        link = _url(text)
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        candidate = (query.get('secret') or query.get('key') or query.get('seed') or [''])[0]
        if not candidate and parsed.path.startswith(('/tok/', '/totp/')):
            candidate = unquote(parsed.path.rstrip('/').split('/')[-1])
        if candidate and looks_like_secret(candidate):
            fields['secret'] = normalize_secret(candidate)
    elif text.lower().startswith('otpauth://') or (text and looks_like_secret(text)):
        fields['secret'] = normalize_secret(text)
    elif text:
        fields['exchange_code'] = text
    if link:
        fields['exchange_url'] = link
    return fields


def parse_line(line):
    parts = [part.strip() for part in re.split(r'-{4,}|\||\t+', line.strip())]
    if not 2 <= len(parts) <= 4:
        raise VaultError('请使用邮箱、密码、2FA 资料和可选兑换链接')
    fields = {'email': _clean_email(parts[0]), 'password': _clean_password(parts[1])}
    if len(parts) >= 3:
        fields.update(material_fields(parts[2], parts[3] if len(parts) == 4 else ''))
    return fields


class Vault:
    """Whole-vault load and replace. One file, one lock, no partial update."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, Entry] = {}
        self._load()

    # ---- persistence ---------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        # A vault is always written through write_credential_bytes. Refuse a
        # bare JSON file: the credential reader accepts unencrypted bytes for
        # auth.json compatibility, and that leniency must not reach this file.
        try:
            envelope = json.loads(self.path.read_bytes().decode('utf-8-sig'))
        except (OSError, ValueError, UnicodeError):
            raise VaultError('账号库内容无法识别，已保留原文件') from None
        if not isinstance(envelope, dict) or 'chatgptnx_credential' not in envelope:
            raise VaultError('账号库未加密，已保留原文件')
        try:
            plain = read_credential_bytes(self.path)
        except CredentialProtectionError:
            raise
        except OSError:
            raise VaultError('无法读取账号库') from None
        try:
            document = json.loads(plain.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise VaultError('账号库内容无法识别，已保留原文件') from None
        if not isinstance(document, dict) or document.get('schema') != SCHEMA:
            raise VaultError('账号库版本不受支持')
        if document.get('version') != VERSION:
            raise VaultError('账号库版本不受支持')
        items = document.get('accounts')
        if not isinstance(items, list) or len(items) > MAX_ENTRIES:
            raise VaultError('账号库内容无法识别，已保留原文件')
        entries: dict[str, Entry] = {}
        for item in items:
            if not isinstance(item, dict):
                raise VaultError('账号库内容无法识别，已保留原文件')
            try:
                entry = Entry(email=_clean_email(item.get('email')),
                              password=_clean_password(item.get('password')),
                              secret=_clean_secret(item.get('secret')),
                              exchange_code=_text(item.get('exchange_code') or ''),
                              exchange_url=_url(item.get('exchange_url') or ''),
                              recovery_codes=_text(item.get('recovery_codes') or '', 16384),
                              secret_source='enrolled' if item.get('secret_source') == 'enrolled' else 'imported',
                              migrated_at=float(item.get('migrated_at') or 0),
                              label=str(item.get('label') or '')[:MAX_LABEL],
                              added_at=float(item.get('added_at') or 0),
                              last_login_at=float(item.get('last_login_at') or 0),
                              last_result=str(item.get('last_result') or ''))
            except (VaultError, ValueError, TypeError):
                raise VaultError('账号库内容无法识别，已保留原文件') from None
            entries[entry.email.lower()] = entry
        self._entries = entries

    def _save(self) -> None:
        if len(self._entries) > MAX_ENTRIES:
            raise VaultError('账号库条目过多')
        document = {'schema': SCHEMA, 'version': VERSION,
                    'accounts': [asdict(entry) for entry in self._entries.values()]}
        plain = json.dumps(document, ensure_ascii=False).encode('utf-8')
        try:
            write_credential_bytes(self.path, plain)
        except CredentialProtectionError:
            raise
        except OSError:
            raise VaultError('无法保存账号库') from None

    # ---- reads ---------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def emails(self) -> list[str]:
        with self._lock:
            return [entry.email for entry in self._entries.values()]

    def get(self, email: object) -> Entry | None:
        with self._lock:
            return self._entries.get(str(email or '').strip().lower())

    def public(self) -> list[dict]:
        """Roster for the UI: no password, no secret."""
        with self._lock:
            return [entry.public() for entry in
                    sorted(self._entries.values(), key=lambda item: item.email.lower())]

    # ---- writes --------------------------------------------------------
    def put(self, email: object, *, password: object = None, secret: object = None,
            label: object = None, exchange_code=None, exchange_url=None,
            recovery_codes=None, secret_source=None, migrated_at=None) -> Entry:
        """Create or update one entry. Omitted fields keep their stored value."""
        clean_email = _clean_email(email)
        key = clean_email.lower()
        with self._lock:
            current = self._entries.get(key)
            # Omitted fields keep their stored value; a new entry starts from an empty base.
            base = current if current is not None else Entry(email=clean_email)
            new_password = base.password if password is None else _clean_password(password)
            new_secret = base.secret if secret is None else _clean_secret(secret)
            new_label = base.label if label is None else str(label or '')[:MAX_LABEL]
            changed = new_secret != base.secret
            source = ('imported' if changed else base.secret_source) if secret_source is None else secret_source
            if source not in ('imported', 'enrolled'):
                raise VaultError('2FA 来源不正确')
            entry = Entry(email=clean_email, password=new_password, secret=new_secret,
                          exchange_code=base.exchange_code if exchange_code is None else _text(exchange_code),
                          exchange_url=base.exchange_url if exchange_url is None else _url(exchange_url),
                          recovery_codes=base.recovery_codes if recovery_codes is None else _text(recovery_codes, 16384),
                          secret_source=source,
                          migrated_at=(0.0 if changed else base.migrated_at) if migrated_at is None else float(migrated_at),
                          label=new_label,
                          added_at=current.added_at if current else time.time(),
                          last_login_at=current.last_login_at if current else 0.0,
                          last_result='' if (changed or new_password != base.password) else base.last_result)
            self._entries[key] = entry
            try:
                self._save()
            except Exception:
                # Keep the in-memory roster equal to the bytes on disk.
                if current is None:
                    self._entries.pop(key, None)
                else:
                    self._entries[key] = current
                raise
            return entry

    def put_many(self, records):
        """Commit the parsed batch in one encrypted replacement."""
        with self._lock:
            before = self._entries.copy()
            save = self._save
            try:
                self._save = lambda: None
                for record in records:
                    self.put(**record)
                save()
            except Exception:
                self._entries = before
                raise
            finally:
                self._save = save
        return len(records)

    def forget(self, email: object) -> bool:
        key = str(email or '').strip().lower()
        with self._lock:
            current = self._entries.pop(key, None)
            if current is None:
                return False
            try:
                self._save()
            except Exception:
                self._entries[key] = current
                raise
            return True

    def record_login(self, email: object, result: str) -> Entry | None:
        """Remember how the last refill ended. Never raises on an unknown value."""
        key = str(email or '').strip().lower()
        with self._lock:
            current = self._entries.get(key)
            if current is None:
                return None
            updated = replace(current, last_login_at=time.time(),
                              last_result=result if result in RESULTS else 'stopped')
            self._entries[key] = updated
            try:
                self._save()
            except Exception:
                self._entries[key] = current
                raise
            return updated
