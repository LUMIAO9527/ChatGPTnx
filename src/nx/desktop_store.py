"""Clear the desktop app's Chromium storage for the current Windows profile.

`~/.codex/auth.json` is the credential store and belongs to switch_account.ps1.
This module only removes the *browser* state that makes the app look like a
different device to the service: cookies, local/session storage, IndexedDB and
caches. The two are deliberately separate - replacing a login and forgetting a
device are different operations with different failure modes.

Layout (MSIX package, verified on this machine):

    %LOCALAPPDATA%\\Packages\\OpenAI.Codex_<hash>\\LocalCache\\Roaming\\
        Codex\\web\\Codex\\Default\\           <- profile root
            Network\\Cookies                    cookies
            Local Storage\\leveldb\\            localStorage
            Session Storage\\                   sessionStorage
            IndexedDB\\                         IndexedDB
            Cache\\, Code Cache\\, GPUCache\\    caches
            Partitions\\<name>\\                 same layout per partition
            Preferences, Local State            kept unless deep

The package folder carries a hash suffix and may change between releases, so
the root is discovered by prefix rather than hard-coded.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_PREFIX = 'OpenAI.Codex_'
CREATE_NO_WINDOW = 0x08000000

# Relative to a profile root. Every entry is removed recursively.
GROUPS = {
    'cookies': ('Network/Cookies', 'Network/Cookies-journal',
                'Network/TransportSecurity', 'Network/Network Persistent State'),
    'storage': ('Local Storage', 'Session Storage', 'IndexedDB', 'WebStorage',
                'File System', 'Databases', 'blob_storage'),
    'cache': ('Cache', 'Code Cache', 'GPUCache', 'DawnGraphiteCache',
              'DawnWebGPUCache', 'Shared Dictionary', 'GrShaderCache',
              'Service Worker/CacheStorage', 'Service Worker/ScriptCache'),
}

# Removed only in deep mode: these carry settings and the cookie encryption key.
DEEP_ONLY = ('Local State', 'Preferences')

PARTITIONS = 'Partitions'
ALL_GROUPS = tuple(GROUPS)


class StoreError(OSError):
    """Safe to show: names a path or a stage, never file contents."""


@dataclass
class Result:
    ok: bool = True
    roots: list = field(default_factory=list)
    removed_files: int = 0
    freed_bytes: int = 0
    skipped: list = field(default_factory=list)
    error: str = ''

    def as_dict(self) -> dict:
        return {'ok': self.ok, 'roots': [str(root) for root in self.roots],
                'removed_files': self.removed_files, 'freed_bytes': self.freed_bytes,
                'skipped': self.skipped, 'error': self.error}


def profile_roots() -> list[Path]:
    """Every existing Chromium profile root of the packaged desktop app."""
    found: list[Path] = []
    local = os.environ.get('LOCALAPPDATA')
    if local:
        packages = Path(local) / 'Packages'
        try:
            entries = list(packages.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if not entry.name.startswith(PACKAGE_PREFIX):
                continue
            candidate = entry / 'LocalCache' / 'Roaming' / 'Codex' / 'web' / 'Codex' / 'Default'
            if candidate.is_dir():
                found.append(candidate)
    # Unpackaged installs keep the same tree under roaming app data.
    roaming = os.environ.get('APPDATA')
    if roaming:
        for candidate in (Path(roaming) / 'Codex' / 'web' / 'Codex' / 'Default',
                          Path(roaming) / 'ChatGPT' / 'web' / 'ChatGPT' / 'Default'):
            if candidate.is_dir():
                found.append(candidate)
    return found


def chatgpt_running() -> bool:
    """True while ChatGPT.exe is in the process list (toolhelp snapshot)."""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        from ctypes import wintypes as wt
        k32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x02

        class PE32(ctypes.Structure):
            _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD),
                        ('th32ProcessID', wt.DWORD),
                        ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                        ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                        ('th32ParentProcessID', wt.DWORD),
                        ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD),
                        ('szExeFile', wt.WCHAR * 260)]

        k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PE32)]
        k32.Process32FirstW.restype = wt.BOOL
        k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PE32)]
        k32.Process32NextW.restype = wt.BOOL
        k32.CloseHandle.argtypes = [wt.HANDLE]
        snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return False
        entry = PE32()
        entry.dwSize = ctypes.sizeof(PE32)
        running = False
        ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == 'chatgpt.exe':
                running = True
                break
            ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
        k32.CloseHandle(snapshot)
        return running
    except Exception:
        return False


def stop_app(timeout=25) -> bool:
    """Ask the packaged app to exit, then force it. Returns True when it is gone."""
    if not chatgpt_running():
        return True
    try:
        subprocess.run(['taskkill.exe', '/IM', 'ChatGPT.exe'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not chatgpt_running():
            return True
        time.sleep(0.2)
    try:
        subprocess.run(['taskkill.exe', '/F', '/IM', 'ChatGPT.exe'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=CREATE_NO_WINDOW, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(20):
        if not chatgpt_running():
            return True
        import time as clock
        clock.sleep(0.2)
    return not chatgpt_running()


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, 'st_file_attributes', 0) & 0x400)  # reparse point


def _inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _remove(path: Path, root: Path, result: Result) -> None:
    """Delete one entry, counting bytes and refusing anything outside the root."""
    if not path.exists():
        return
    if not _inside(root, path):
        result.skipped.append(f'outside_root:{path}')
        return
    if _is_link(path):
        result.skipped.append(f'link:{path}')
        return
    try:
        if path.is_dir():
            size = 0
            files = 0
            for base, _dirs, names in os.walk(path, followlinks=False):
                for name in names:
                    item = Path(base) / name
                    if _is_link(item):
                        result.skipped.append(f'link:{item}')
                        continue
                    try:
                        size += item.stat().st_size
                        files += 1
                    except OSError:
                        pass
            shutil.rmtree(path, ignore_errors=False)
            result.removed_files += files
            result.freed_bytes += size
        else:
            size = path.stat().st_size
            path.unlink()
            result.removed_files += 1
            result.freed_bytes += size
    except OSError as error:
        result.skipped.append(f'{path.name}:{type(error).__name__}')


def _targets(root: Path, groups, deep: bool):
    wanted = []
    for group in groups:
        wanted.extend(name for name in GROUPS[group])
    if deep:
        wanted.extend(DEEP_ONLY)
    for name in wanted:
        yield root / Path(name)
    partitions = root / PARTITIONS
    if not partitions.is_dir():
        return
    try:
        children = [item for item in partitions.iterdir() if item.is_dir()]
    except OSError:
        return
    for child in children:
        # Per-partition copies of the same named entries.
        for name in wanted:
            yield child / Path(name)


def clear(*, groups=('cookies', 'storage', 'cache'), deep=False,
          restart=True, roots=None) -> dict:
    """Remove the selected storage groups. The app must not be running.

    Returns a plain dict so the Core can hand it straight to the panel.
    """
    unknown = [group for group in groups if group not in GROUPS]
    if unknown:
        raise StoreError(f'未知的清理范围：{",".join(unknown)}')

    result = Result()
    candidates = [Path(item) for item in (roots if roots is not None else profile_roots())]
    targets_roots = [root for root in candidates if root.is_dir()]
    if not targets_roots:
        result.ok = False
        result.error = '没有找到 ChatGPT 桌面端的数据目录'
        return result.as_dict()

    was_running = chatgpt_running()
    if was_running:
        if not stop_app():
            result.ok = False
            result.error = 'ChatGPT 桌面端没有退出，清理未执行'
            return result.as_dict()

    try:
        for root in targets_roots:
            if not root.is_dir():
                result.skipped.append(f'missing:{root}')
                continue
            result.roots.append(root)
            for target in _targets(root, groups, deep):
                _remove(target, root, result)
    finally:
        if restart and was_running:
            from .desktop import launch_chatgpt
            launch_chatgpt()

    return result.as_dict()