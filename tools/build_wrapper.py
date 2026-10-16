"""Build the native public launcher around the PyInstaller core payload."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import json
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / '_wip' / 'build' / 'resources'
DIST = ROOT / '_wip' / 'build' / 'dist'
sys.path.insert(0, str(ROOT / 'src'))
from nx.version import APP_VERSION


def build(core=None, output=None, *, version=APP_VERSION) -> Path:
    core = Path(core or DIST / 'ChatGPTnx.Core').resolve()
    if not (core / 'ChatGPTnx.Core.exe').is_file():
        raise RuntimeError('Build the ChatGPTnx.Core directory before the launcher')
    template = (ROOT / 'src' / 'update_wrapper.cs').read_text(encoding='utf-8')
    output = Path(output or DIST / 'ChatGPTnx.exe').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = output.with_suffix('.core.zip')
    files = sorted(p for p in core.rglob('*') if p.is_file())
    manifest = []
    with ZipFile(payload, 'w', ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_symlink():
                raise RuntimeError('Core payload must not contain redirected files')
            data = path.read_bytes()
            name = path.relative_to(core).as_posix()
            archive.writestr(name, data)
            manifest.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        manifest_bytes = json.dumps({'files': manifest}, separators=(',', ':')).encode('utf-8')
        archive.writestr('CORE-MANIFEST.json', manifest_bytes)
    with ZipFile(payload) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Core payload ZIP failed verification')
    sha = hashlib.sha256(payload.read_bytes()).hexdigest()
    source = output.with_suffix('.generated.cs')
    file_version = '.'.join((version.split('.') + ['0'] * 4)[:4])
    source.write_text(template.replace('__PAYLOAD_VERSION__', version)
                      .replace('__PAYLOAD_SHA256__', sha)
                      .replace('__MANIFEST_SHA256__', hashlib.sha256(manifest_bytes).hexdigest())
                      .replace('__FILE_VERSION__', file_version), encoding='utf-8')
    framework = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET'
    compiler = next((path / 'csc.exe' for path in (
        framework / 'Framework64' / 'v4.0.30319',
        framework / 'Framework' / 'v4.0.30319') if (path / 'csc.exe').is_file()), None)
    if not compiler:
        raise RuntimeError('Microsoft .NET Framework compiler is required to build the launcher')
    command = [str(compiler), '/nologo', '/target:winexe', '/optimize+',
               '/out:' + str(output), '/win32icon:' + str(RESOURCES / 'nx.ico'),
               '/r:System.Windows.Forms.dll', '/r:System.Web.Extensions.dll', '/r:System.IO.Compression.dll',
               '/resource:' + str(payload) + ',ChatGPTnx.Core.zip',
               str(ROOT / 'src/update_common.cs'), str(source)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Launcher compilation failed:\n' + result.stdout[-4000:])
    return output


if __name__ == '__main__':
    print('Built ChatGPTnx launcher:', build())
