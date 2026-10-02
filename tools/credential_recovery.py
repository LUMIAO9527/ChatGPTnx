"""Explicit local rollback utility. Never touches the official auth.json."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.credentials import (FORMAT_KEY, CredentialProtectionError, assert_safe_path,
    credential_store_lock, read_credential_bytes, secure_path, _tree)
from nx.storage import atomic_bytes


@contextmanager
def application_stopped():
    """Hold the same single-instance guard as the app for the whole rollback."""
    if os.name != 'nt':
        raise CredentialProtectionError('Windows is required')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'ChatGPTnx_SingleInstance')
    if not handle:
        raise CredentialProtectionError('Cannot acquire application guard')
    try:
        if ctypes.get_last_error() == 183:
            raise CredentialProtectionError('Exit ChatGPTnx before credential rollback')
        yield
    finally:
        kernel.CloseHandle(handle)


def decrypt_for_rollback(home: Path) -> dict:
    home = assert_safe_path(home)
    snapshots = assert_safe_path(home / 'snapshots')
    if not snapshots.is_dir():
        raise CredentialProtectionError('Snapshot directory is missing')
    with application_stopped(), credential_store_lock(snapshots):
        items = _tree(snapshots)
        targets = [p for p in items if p.is_file() and p.suffix.lower() == '.json']
        # Validate every document before changing any. Keep plaintext in memory.
        originals = [(p, p.stat(), read_credential_bytes(p)) for p in targets]
        for path in items:
            secure_path(path)
        restored = 0
        for path, info, plain in originals:
            if FORMAT_KEY not in json.loads(path.read_bytes().decode('utf-8-sig')):
                continue
            assert_safe_path(path)
            atomic_bytes(path, plain, private=True)
            secure_path(path)
            if path.read_bytes() != plain:
                raise CredentialProtectionError('Rollback verification failed')
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            restored += 1
        return {'restored': restored, 'checked': len(targets), 'official_auth_changed': False}


def main():
    parser = argparse.ArgumentParser(description='Restore private snapshot JSON for an explicit old-version rollback')
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--decrypt-for-rollback', required=True, action='store_true')
    args = parser.parse_args()
    try:
        result = decrypt_for_rollback(args.home)
    except Exception:
        # No filenames/OS errors in output. Partial conversion is safe to retry.
        print('Rollback incomplete. Exit ChatGPTnx, retain all files, check this Windows user and folder permissions.', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
