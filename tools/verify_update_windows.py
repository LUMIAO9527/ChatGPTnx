"""Exercise production updating through real PyInstaller one-file processes.

All programs, accounts and settings here are synthetic and confined to _wip.
Requires the project's existing Windows development dependencies.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = 0x08000000 if os.name == 'nt' else 0


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_json(path, timeout=65):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            time.sleep(.1)
    raise RuntimeError('timed_out_waiting_for_' + path.name)


def clean_own_processes(target, helper_pid):
    # Exact synthetic executable path and helper PID only; never product processes.
    if ROOT / '_wip' not in target.resolve().parents:
        raise RuntimeError('cleanup_outside_fixture_directory')
    quoted = str(target).replace("'", "''")
    script = ("$ErrorActionPreference='Continue'; "
              f"Get-CimInstance Win32_Process | Where-Object {{$_.ExecutablePath -eq '{quoted}'}} "
              "| ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}; "
              f"$helper=Get-CimInstance Win32_Process -Filter 'ProcessId={int(helper_pid or 0)}'; "
              f"if($helper -and $helper.CommandLine -like '*{str(target.parent).replace(chr(39), chr(39)*2)}*')"
              "{Stop-Process -Id $helper.ProcessId -Force -ErrorAction SilentlyContinue}")
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=HIDDEN, timeout=15)


def build_fixture(work, variant, environment):
    data = work / ('resources-' + variant)
    data.mkdir()
    marker = data / 'fixture-build.txt'
    marker.write_text(variant, encoding='utf-8')
    output = work / 'dist' / ('fixture-' + variant + '.exe')
    helper = ROOT / '_wip' / 'build' / 'resources' / 'ChatGPTnx.Update.exe'
    if not helper.is_file():
        raise RuntimeError('independent_updater_missing')
    command = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onefile', '--console', '--name', output.stem,
               '--paths', str(ROOT / 'src'),
               '--add-data', str(marker) + ';.',
               '--add-data', str(helper) + ';.',
               '--distpath', str(output.parent), '--workpath', str(work / ('build-' + variant)),
               '--specpath', str(work / ('spec-' + variant)),
               str(ROOT / 'tests/frozen_update_fixture.py')]
    with (work / ('build-' + variant + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=HIDDEN)
    if result.returncode:
        raise RuntimeError('fixture_build_failed_' + variant)
    print('Built frozen fixture: ' + variant, flush=True)
    return output


def run_case(work, case, old, new, environment):
    app = work / ('case-' + case) / '程序 更新'
    (app / '_wip').mkdir(parents=True)
    target = app / 'ChatGPTnx.exe'
    shutil.copyfile(old, target)
    sentinel = {app / 'accounts.txt': b'synthetic-accounts',
                app / '_data' / 'settings.json': b'{"synthetic":true}'}
    for path, content in sentinel.items():
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    (app / '_wip/fixture.json').write_text(json.dumps({'case': case, 'candidate': str(new)}), encoding='utf-8')
    begin, process = {}, None
    started = time.monotonic()
    try:
        with (app / '_wip/parent.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(target), '--begin'], cwd=app, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=HIDDEN)
            begin = wait_json(app / '_wip/begin.json', timeout=20)
            result = wait_json(Path(begin['batch']) / 'result.json')
            expected = {'success': 'complete', 'rollback': 'rolled_back',
                        'timeout': 'rolled_back', 'checksum': 'failed'}[case]
            assert result['status'] == expected, result
            process.wait(timeout=10)
            if case == 'success':
                candidate = wait_json(app / '_wip/candidate.json', timeout=10)
                assert candidate['build'] == 'new', candidate
                assert candidate['runtime'] != begin['old_runtime'], candidate
                assert digest(target) == digest(new)
            else:
                assert digest(target) == digest(old)
                if case in ('rollback', 'timeout'):
                    restored = wait_json(app / '_wip/restored.json', timeout=10)
                    assert restored['build'] == 'old', restored
                    assert restored['runtime'] != begin['old_runtime'], restored
            for path, content in sentinel.items():
                assert path.read_bytes() == content, path.name
            deadline = time.monotonic() + 10
            while Path(begin['old_runtime']).exists() and time.monotonic() < deadline:
                time.sleep(.1)
            assert not Path(begin['old_runtime']).exists(), 'old_runtime_not_cleaned'
            for runtime in (Path(begin['batch']) / 'runtime-candidate',
                            Path(begin['batch']) / 'runtime-rollback'):
                while list(runtime.glob('_MEI*')) and time.monotonic() < deadline:
                    time.sleep(.1)
                assert not list(runtime.glob('_MEI*')), 'runtime_not_cleaned'
            assert 'Failed to' not in (app / '_wip/parent.log').read_text(encoding='utf-8', errors='replace')
        record = {'case': case, 'status': result['status'], 'data_preserved': True,
                  'fresh_runtime': True, 'elapsed_seconds': round(time.monotonic() - started, 2)}
        print(json.dumps(record), flush=True)
        return record
    finally:
        clean_own_processes(target, begin.get('helper_pid'))
        if process and process.poll() is None:
            process.wait(timeout=10)


def main():
    if os.name != 'nt':
        raise SystemExit('Windows is required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('success', 'rollback', 'timeout', 'checksum'), action='append')
    args = parser.parse_args()
    work = ROOT / '_wip' / 'update-windows' / time.strftime('%Y%m%d-%H%M%S')
    work.mkdir(parents=True)
    scratch = work / 'scratch'
    scratch.mkdir()
    environment = dict(os.environ, TEMP=str(scratch), TMP=str(scratch),
                       PYINSTALLER_CONFIG_DIR=str(work / 'cache'), PYTHONDONTWRITEBYTECODE='1')
    build = subprocess.run([sys.executable, '-B', 'tools/build.py'], cwd=ROOT,
                           env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=HIDDEN, text=True, encoding='utf-8', errors='replace')
    if build.returncode:
        raise RuntimeError('updater_build_failed:\n' + build.stdout[-4000:])
    old = build_fixture(work, 'old', environment)
    new = build_fixture(work, 'new', environment)
    records = [run_case(work, case, old, new, environment)
               for case in (args.case or ('success', 'rollback', 'timeout', 'checksum'))]
    (work / 'results.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Frozen updater regression passed: ' + str(len(records)) + ' cases', flush=True)


if __name__ == '__main__':
    main()
