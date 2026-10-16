"""Build the native public launcher around the PyInstaller core payload."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / '_wip' / 'build' / 'resources'
DIST = ROOT / '_wip' / 'build' / 'dist'
sys.path.insert(0, str(ROOT / 'src'))
from nx.version import APP_VERSION


def build() -> Path:
    core = DIST / 'ChatGPTnx.Core.exe'
    if not core.is_file():
        raise RuntimeError('Build ChatGPTnx.Core.exe before the launcher')
    sha = hashlib.sha256(core.read_bytes()).hexdigest()
    template = (ROOT / 'src' / 'update_wrapper.cs').read_text(encoding='utf-8')
    source = (ROOT / '_wip' / 'build' / 'update_wrapper.generated.cs')
    source.write_text(template.replace('__PAYLOAD_VERSION__', APP_VERSION)
                      .replace('__PAYLOAD_SHA256__', sha), encoding='utf-8')
    framework = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET'
    compiler = next((path / 'csc.exe' for path in (
        framework / 'Framework64' / 'v4.0.30319',
        framework / 'Framework' / 'v4.0.30319') if (path / 'csc.exe').is_file()), None)
    if not compiler:
        raise RuntimeError('Microsoft .NET Framework compiler is required to build the launcher')
    output = DIST / 'ChatGPTnx.exe'
    command = [str(compiler), '/nologo', '/target:winexe', '/optimize+',
               '/out:' + str(output), '/win32icon:' + str(RESOURCES / 'nx.ico'),
               '/r:System.Windows.Forms.dll', '/resource:' + str(core) + ',ChatGPTnx.Core.exe',
               str(source)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Launcher compilation failed:\n' + result.stdout[-4000:])
    return output


if __name__ == '__main__':
    print('Built ChatGPTnx launcher:', build())
