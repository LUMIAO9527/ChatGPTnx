"""Public GitHub releases, bounded downloads and a reversible local EXE update.

No credentials, account files, shell interpolation or downloaded scripts.
The bundled helper runs independently after this process exits.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .storage import atomic_bytes
from .version import APP_VERSION

REPOSITORY = 'LUMIAO9527/ChatGPTnx'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_DOWNLOAD = 150 * 1024 * 1024
MAX_METADATA = 1024 * 1024
ALLOWED_HOSTS = frozenset({'api.github.com', 'github.com',
                         'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})


class UpdateError(RuntimeError):
    pass


def version_key(value):
    match = re.fullmatch(r'v?(\d{1,5})\.(\d{1,5})(?:\.(\d{1,5}))?', str(value))
    if not match:
        raise UpdateError('发布版本号格式不受支持')
    return tuple(int(part or 0) for part in match.groups())


def safe_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise UpdateError('更新下载地址未通过检查')
    return value


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url):
    req = urllib.request.Request(safe_url(url), headers={
        'User-Agent': f'ChatGPTnx/{APP_VERSION}', 'Accept': 'application/vnd.github+json'})
    return urllib.request.build_opener(ReleaseRedirect()).open(req, timeout=15)


def release_asset(document, current):
    if not isinstance(document, dict) or document.get('draft') or document.get('prerelease'):
        raise UpdateError('未找到正式发布版本')
    tag = document.get('tag_name')
    newer = version_key(tag) > version_key(current)
    assets = [a for a in document.get('assets', [])
              if isinstance(a, dict) and a.get('name') == 'ChatGPTnx.exe' and a.get('state') == 'uploaded']
    if len(assets) != 1:
        raise UpdateError('发布版缺少唯一的 Windows 程序')
    asset = assets[0]
    size, digest, url = asset.get('size'), asset.get('digest'), asset.get('browser_download_url')
    if type(size) is not int or not 1024 <= size <= MAX_DOWNLOAD:
        raise UpdateError('发布程序大小不受支持')
    if not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-fA-F]{64}', digest):
        raise UpdateError('发布程序缺少 SHA-256 校验值，请稍后重试')
    safe_url(url)
    expected = f'https://github.com/{REPOSITORY}/releases/download/{tag}/ChatGPTnx.exe'
    if url != expected:
        raise UpdateError('发布程序不属于指定仓库和版本')
    # Plain text only. Release notes never become HTML or executable input.
    notes = str(document.get('body') or '').replace('\x00', '')[:4000]
    return {'version': tag.removeprefix('v'), 'available': newer, 'size': size,
            'sha256': digest[7:].lower(), 'url': url, 'notes': notes}


def digest_file(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


class UpdateManager:
    def __init__(self, root, resources, notify=lambda: None, *, executable=None,
                 frozen=None, opener=request, current=APP_VERSION):
        self.root = Path(root).resolve()
        self.resources = Path(resources).resolve()
        self.executable = Path(executable or sys.executable).resolve()
        self.installable = (getattr(sys, 'frozen', False) if frozen is None else frozen) and (
            self.executable.parent == self.root and self.executable.suffix.lower() == '.exe')
        self.current, self.opener, self.notify = current, opener, notify
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.asset = None
        self.batch = None
        self.state = {'status': 'idle', 'current': current, 'installable': bool(self.installable),
                      'message': '检查是否有新版本', 'progress': 0}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **values):
        with self.lock:
            self.state.update(values)
        self.notify()

    def _start(self, status, job):
        with self.lock:
            if self.state['status'] in ('checking', 'downloading', 'installing'):
                return {'ok': False, 'error': '更新操作正在进行'}
            self.cancel.clear()
            self.state.update(status=status, progress=0, message='正在检查更新…' if status == 'checking' else '正在下载更新…')
        self.notify()
        def work():
            try:
                job()
            except Exception as error:
                message = str(error) if isinstance(error, UpdateError) else '连接 GitHub 失败或下载中断，请重试'
                self._set(status='error', message=message, progress=0)
        threading.Thread(target=work, daemon=True, name='nx-update-' + status).start()
        return {'ok': True, 'accepted': True}

    def check(self):
        def work():
            with self.opener(API) as response:
                raw = response.read(MAX_METADATA + 1)
                if len(raw) > MAX_METADATA:
                    raise UpdateError('发布信息过大')
            try:
                asset = release_asset(json.loads(raw), self.current)
            except (ValueError, TypeError, KeyError):
                raise UpdateError('发布信息格式不正确') from None
            with self.lock:
                self.asset = asset
            self._set(status='available' if asset['available'] else 'current',
                      version=asset['version'], notes=asset['notes'], size=asset['size'],
                      available=asset['available'], checked_at=int(time.time()),
                      message='发现新版本' if asset['available'] else '当前已是最新版本')
        return self._start('checking', work)

    def download(self):
        with self.lock:
            asset = dict(self.asset or {})
        if not asset.get('available'):
            return {'ok': False, 'error': '请先检查是否有新版本'}
        if not self.installable:
            return {'ok': False, 'error': '当前从源码运行；内置更新适用于独立 EXE'}
        def work():
            if shutil.disk_usage(self.root).free < asset['size'] + self.executable.stat().st_size + 32 * 1024 * 1024:
                raise UpdateError('程序所在磁盘空间不足，请清理后重试')
            batch = self.root / '_wip' / 'update' / uuid.uuid4().hex
            for folder in (self.root / '_wip', self.root / '_wip' / 'update'):
                if folder.exists() and (folder.is_symlink() or folder.resolve() != folder):
                    raise UpdateError('更新目录不能使用重定向路径')
            batch.mkdir(parents=True, exist_ok=False)
            if batch.resolve().parent != (self.root / '_wip' / 'update').resolve():
                raise UpdateError('更新目录未通过检查')
            stage = batch / 'ChatGPTnx.new.exe'
            sha, count, started, last_progress = hashlib.sha256(), 0, time.monotonic(), -1
            try:
                with self.opener(asset['url']) as response, stage.open('xb') as output:
                    while True:
                        if self.cancel.is_set():
                            raise UpdateError('下载已取消，可重新下载')
                        if time.monotonic() - started > 300:
                            raise UpdateError('下载超时，请重试')
                        chunk = response.read(128 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > asset['size'] or count > MAX_DOWNLOAD:
                            raise UpdateError('下载大小与发布信息不符')
                        output.write(chunk)
                        sha.update(chunk)
                        progress = int(count * 100 / asset['size'])
                        if progress != last_progress:
                            last_progress = progress
                            self._set(progress=progress, downloaded=count)
                    output.flush()
                    os.fsync(output.fileno())
                if count != asset['size'] or sha.hexdigest() != asset['sha256']:
                    raise UpdateError('下载校验失败，请重新下载')
                with stage.open('rb') as stream:
                    if stream.read(2) != b'MZ':
                        raise UpdateError('下载内容不是 Windows 程序')
                if self.cancel.is_set():
                    raise UpdateError('下载已取消，可重新下载')
                with self.lock:
                    self.batch = batch
                self._set(status='ready', progress=100, message='下载已校验，点击重启并更新')
            except Exception:
                stage.unlink(missing_ok=True)
                # Only this newly-created, empty batch is removed.
                batch.rmdir()
                raise
        return self._start('downloading', work)

    def cancel_download(self):
        with self.lock:
            if self.state['status'] != 'downloading':
                return {'ok': False, 'error': '当前没有正在下载的更新'}
            self.cancel.set()
        return {'ok': True}

    def install(self, parent_pid, popen=subprocess.Popen):
        with self.lock:
            if self.state['status'] != 'ready' or not self.batch or not self.installable:
                return {'ok': False, 'error': '请先下载并校验更新'}
            batch, asset = self.batch, dict(self.asset)
            stage = batch / 'ChatGPTnx.new.exe'
            if not stage.is_file() or digest_file(stage) != asset['sha256']:
                return {'ok': False, 'error': '更新文件发生变化，请重新下载'}
            helper_source = self.resources / 'ChatGPTnx.Update.exe'
            if not helper_source.is_file() or helper_source.stat().st_size < 1024:
                raise UpdateError('更新组件缺失，请重新安装当前版本')
            helper = batch / 'ChatGPTnx.Update.exe'
            with helper_source.open('rb') as source, helper.open('xb') as target:
                shutil.copyfileobj(source, target, length=256 * 1024)
                target.flush()
                os.fsync(target.fileno())
            token = uuid.uuid4().hex
            previous_sha256 = digest_file(self.executable)
            plan = {'root': str(self.root), 'executable': str(self.executable),
                    'parent_pid': parent_pid, 'version': asset['version'],
                    'sha256': asset['sha256'], 'size': asset['size'], 'token': token,
                    'previous_version': self.current,
                    'previous_sha256': previous_sha256,
                    'previous_size': self.executable.stat().st_size}
            journal = batch / 'plan.json'
            atomic_bytes(journal, json.dumps(plan).encode('utf-8'))
            environment = dict(os.environ)
            # The helper is a standalone .NET process. It builds a clean
            # environment for the candidate and never inherits PyInstaller's
            # private one-file variables into the restarted application.
            popen([str(helper), '-Plan', str(journal)], cwd=str(batch),
                  env=environment, creationflags=0x08000000 if os.name == 'nt' else 0,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.state.update(status='installing', message='正在重启并更新…')
        self.notify()
        return {'ok': True}


def startup_ack(root, executable, ack, token):
    """Only acknowledge a matching local update once the native UI is ready."""
    root, executable, ack = Path(root).resolve(), Path(executable).resolve(), Path(ack).resolve()
    directory = root / '_wip' / 'update'
    if not re.fullmatch('[0-9a-f]{32}', token or '') or ack.name != 'started.json':
        raise UpdateError('更新启动参数不正确')
    if directory not in ack.parents or ack.parent.parent != directory:
        raise UpdateError('更新确认目录不正确')
    plan = json.loads((ack.parent / 'plan.json').read_text(encoding='utf-8'))
    if (plan.get('token') != token or plan.get('version') != APP_VERSION
            or Path(plan.get('executable', '')).resolve() != executable
            or executable.parent != root or digest_file(executable) != plan.get('sha256')):
        raise UpdateError('更新程序未通过启动校验')
    atomic_bytes(ack, json.dumps({'ready': True, 'version': APP_VERSION,
                                'token': token, 'pid': os.getpid()}).encode('utf-8'))
