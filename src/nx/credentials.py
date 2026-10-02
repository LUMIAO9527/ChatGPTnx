"""Windows current-user credential encryption; never log credential material.

Only portable snapshots are encrypted. The official auth.json remains byte-for-
byte compatible. A migration failure aborts startup and keeps existing bytes.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import threading
import time
import uuid

FORMAT_KEY = 'chatgptnx_credential'
ENTROPY = b'ChatGPTnx credentials v1'
_lock = threading.RLock()


class CredentialProtectionError(OSError):
    """Safe to show: messages do not include secrets or raw OS diagnostics."""


def assert_safe_path(path: Path) -> Path:
    """Reject links/junctions in every existing component before any I/O."""
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CredentialProtectionError('Credential path contains a link or reparse point')
        if item == path and stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise CredentialProtectionError('Credential path has multiple hard links')
    return path


def _windows():
    if os.name != 'nt':
        raise CredentialProtectionError('Windows credential protection is required')
    return ctypes.WinDLL('crypt32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _dpapi(data: bytes, *, decrypt=False) -> bytes:
    crypt, kernel = _windows()
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(ENTROPY)
    output = _Blob()
    name = 'CryptUnprotectData' if decrypt else 'CryptProtectData'
    call = getattr(crypt, name)
    call.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    call.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; deliberately no LOCAL_MACHINE flag.
    if not call(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise CredentialProtectionError('Cannot decrypt credential for this Windows user' if decrypt
                                        else 'Cannot encrypt credential for this Windows user')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(output.data)


def _current_sid() -> str:
    _windows()
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise CredentialProtectionError('Cannot identify current Windows user')
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise CredentialProtectionError('Cannot identify current Windows user')
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise CredentialProtectionError('Cannot identify current Windows user')
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def secure_path(path: Path) -> None:
    """Replace DACL with current user, SYSTEM and Administrators only."""
    path = assert_safe_path(path)
    sid = _current_sid()
    inherit = 'OICI' if path.is_dir() else ''
    sddl = 'D:P' + ''.join(f'(A;{inherit};FA;;;{who})' for who in (sid, 'SY', 'BA'))
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                               ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise CredentialProtectionError('Cannot prepare private credential permissions')
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise CredentialProtectionError('Cannot prepare private credential permissions')
        # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        if advapi.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None):
            raise CredentialProtectionError('Cannot restrict credential permissions')
    finally:
        kernel.LocalFree(descriptor)


def _decode(raw: bytes) -> bytes:
    try:
        obj = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise CredentialProtectionError('Invalid credential document') from None
    if not isinstance(obj, dict):
        raise CredentialProtectionError('Invalid credential document')
    if FORMAT_KEY not in obj:
        return raw
    if obj.get(FORMAT_KEY) != 1 or obj.get('protection') != 'dpapi-current-user':
        raise CredentialProtectionError('Unsupported credential protection format')
    try:
        encrypted = base64.b64decode(obj['data'], validate=True)
    except (ValueError, TypeError, KeyError):
        raise CredentialProtectionError('Invalid protected credential') from None
    return _dpapi(encrypted, decrypt=True)


def read_credential_bytes(path: Path) -> bytes:
    return _decode(assert_safe_path(path).read_bytes())


def encode_credential_bytes(plaintext: bytes) -> bytes:
    encrypted = _dpapi(plaintext)
    envelope = json.dumps({FORMAT_KEY: 1, 'protection': 'dpapi-current-user',
                           'data': base64.b64encode(encrypted).decode('ascii')}, separators=(',', ':')).encode('ascii')
    if _decode(envelope) != plaintext:
        raise CredentialProtectionError('Credential encryption verification failed')
    return envelope


def write_credential_bytes(path: Path, plaintext: bytes, *, preserve_times=None) -> None:
    path = assert_safe_path(path)
    envelope = encode_credential_bytes(plaintext)
    path.parent.mkdir(parents=True, exist_ok=True)
    secure_path(path.parent)
    if path.exists():
        secure_path(path)
    tmp = path.with_name('.nx-' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('xb') as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())
        secure_path(tmp)
        if read_credential_bytes(tmp) != plaintext:
            raise CredentialProtectionError('Credential file verification failed')
        if preserve_times is not None:
            os.utime(tmp, ns=preserve_times)
        for attempt, delay in enumerate((0, .01, .02, .04, .08, .16)):
            if delay:
                time.sleep(delay)
            assert_safe_path(path)
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def credential_store_lock(snapshots: Path):
    """Same exclusive file-open lock as the PowerShell transaction helper."""
    snapshots = assert_safe_path(snapshots)
    snapshots.mkdir(parents=True, exist_ok=True)
    secure_path(snapshots)
    path = assert_safe_path(snapshots / '.credentials.lock')
    _, kernel = _windows()
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    with _lock:
        handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise CredentialProtectionError('Credential store is busy; retry after the current operation finishes')
        try:
            yield
        finally:
            kernel.CloseHandle(handle)


def _tree(path: Path):
    assert_safe_path(path)
    if not path.exists():
        return []
    found = [path]
    if path.is_dir():
        for item in path.iterdir():
            found.extend(_tree(item))
    return found


def protect_store(paths) -> dict:
    """Explicit startup migration; no deletion or plaintext recovery fallback.

    All paths are checked first, and encrypted documents must decrypt before
    any migration. Partial migration is safe to retry; original timestamps stay.
    """
    snapshot_items = _tree(paths.snapshots)
    metadata_items = _tree(paths.data)
    order_items = _tree(paths.order)
    with credential_store_lock(paths.snapshots):
        snapshot_items = _tree(paths.snapshots)
        candidates = [p for p in snapshot_items if p.is_file() and p.suffix.lower() == '.json']
        for path in candidates:
            read_credential_bytes(path)
        for path in snapshot_items + metadata_items + order_items:
            if path.name != '.credentials.lock':
                secure_path(path)
        migrated = 0
        for path in candidates:
            info = path.stat()
            raw = path.read_bytes()
            if FORMAT_KEY not in json.loads(raw.decode('utf-8-sig')):
                write_credential_bytes(path, _decode(raw), preserve_times=(info.st_atime_ns, info.st_mtime_ns))
                migrated += 1
        return {'migrated': migrated, 'protected': len(candidates)}
