"""Exercise the public launcher, PyInstaller core and independent updater.

Uses synthetic accounts/settings under _wip; never starts the installed app.
Legacy migration uses the unmodified v1.3.1 updater from Git or its source ZIP.
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
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = 0x08000000 if os.name == 'nt' else 0
sys.path.insert(0, str(ROOT / 'tools'))
from build_wrapper import build as build_wrapper


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def wait_json(path, timeout=70):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            time.sleep(.1)
    raise RuntimeError('timed_out_waiting_for_' + path.name)


def wait_gone(path, timeout=12):
    deadline = time.monotonic() + timeout
    while path.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    assert not path.exists(), 'not_cleaned: ' + str(path)


def clean_own_processes(app):
    # Resolve the owner before matching any process. Executables and helpers
    # beneath this synthetic case only; no name-based product process kill.
    app = app.resolve()
    if ROOT / '_wip' not in app.parents:
        raise RuntimeError('cleanup_outside_fixture_directory')
    prefix = (str(app) + '\\').replace("'", "''")
    script = ("$ErrorActionPreference='Continue'; Get-CimInstance Win32_Process | "
              f"Where-Object {{$_.ExecutablePath -and $_.ExecutablePath.StartsWith('{prefix}', [StringComparison]::OrdinalIgnoreCase)}} | "
              "ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}")
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN, timeout=15)


def legacy_source(name, source_zip):
    if source_zip:
        with ZipFile(source_zip) as archive:
            return archive.read(name)
    return subprocess.check_output(['git', 'show', 'v1.3.1:' + name], cwd=ROOT, creationflags=HIDDEN)


def build_fixture(work, variant, environment, source_zip):
    data = work / ('resources-' + variant)
    data.mkdir()
    marker = data / 'fixture-build.txt'
    marker.write_text(variant, encoding='utf-8')
    output = (work / 'dist' / 'fixture-legacy.exe' if variant == 'legacy'
              else work / ('dist-' + variant) / 'ChatGPTnx.Core' / 'ChatGPTnx.Core.exe')
    helper = ROOT / '_wip/build/resources/ChatGPTnx.Update.exe'
    command = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onefile' if variant == 'legacy' else '--onedir', '--console', '--name', output.stem, '--paths', str(ROOT / 'src'),
               '--add-data', str(marker) + ';.', '--add-data', str(helper) + ';.',
               '--distpath', str(output.parent if variant == 'legacy' else output.parent.parent), '--workpath', str(work / ('build-' + variant)),
               '--specpath', str(work / ('spec-' + variant))]
    if variant == 'legacy':
        for source, name in (('src/nx/updater.py', 'legacy_updater.py'), ('src/update_app.ps1', 'update_app.ps1')):
            path = data / name
            path.write_bytes(legacy_source(source, source_zip))
            command.extend(['--add-data', str(path) + ';.'])
    command.append(str(ROOT / 'tests/frozen_update_fixture.py'))
    with (work / ('build-' + variant + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=HIDDEN)
    if result.returncode:
        raise RuntimeError('fixture_build_failed_' + variant)
    if variant != 'legacy':
        output = build_wrapper(output.parent, work / 'dist' / ('launcher-' + variant + '.exe'))
    print('Built frozen fixture: ' + variant, flush=True)
    return output


def seed_cleanup(app):
    updates = app / '_wip/update'
    cases = {'completed': ('1'*32, 'complete', 2), 'failed': ('2'*32, 'recovery_needed', 2),
             'legacy': ('3'*32, 'complete', 1), 'unknown': ('4'*32, 'complete', 2)}
    paths = {}
    for name, (folder, status, schema) in cases.items():
        batch = updates / folder
        batch.mkdir(parents=True)
        write(batch / 'plan.json', {'root': str(app), 'executable': str(app/'ChatGPTnx.exe')})
        write(batch / 'result.json', {'schema': schema, 'status': status})
        (batch / 'previous.exe').write_bytes(b'synthetic-backup')
        if name == 'unknown':
            (batch / 'user-file.txt').write_bytes(b'user-owned')
        paths[name] = batch
    obsolete_cache = app / '_wip/runtime/0.9.0-aaaaaaaaaaaaaaaa'
    obsolete_cache.mkdir(parents=True)
    write(obsolete_cache / 'owner.json', {'schema': 1, 'payload_id': obsolete_cache.name})
    (obsolete_cache / 'ChatGPTnx.Core.exe').write_bytes(b'synthetic-core')
    paths['obsolete_cache'] = obsolete_cache
    return paths


def verify_product(work, executable, environment):
    """Run the actual release payload without the tray or account service."""
    from win32api import GetFileVersionInfo
    from nx.version import APP_VERSION
    app = work / 'product-check' / '程序 更新'
    (app / '_wip').mkdir(parents=True)
    target = app / 'nx 重命名.exe'
    shutil.copyfile(executable, target)
    report = app / '_wip/runtime-check.json'
    old = app / '_wip/retired-runtime'
    old.mkdir()
    inherited = dict(environment, _PYI_APPLICATION_HOME_DIR=str(old),
                     _PYI_ARCHIVE_FILE=str(old / 'retired.exe'), _PYI_PARENT_PROCESS_LEVEL='1',
                     _MEIPASS2=str(old), PYINSTALLER_RESET_ENVIRONMENT='0')
    try:
        result = subprocess.run([str(target), '--runtime-check-report', str(report)],
                                cwd=app, env=inherited, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=HIDDEN, timeout=40)
        assert result.returncode == 0, 'product_start_failed'
        check = wait_json(report, timeout=2)
        assert check['version'] == APP_VERSION and check['dependencies_ready'] is True
        assert Path(check['launcher']) == target
        runtime = Path(check['runtime'])
        assert app / '_wip/runtime' in runtime.parents and runtime != old
        assert not (app / '_data').exists() and not (app / 'accounts.txt').exists()
        assert runtime.name == '_internal' and runtime.is_dir(), 'core_is_not_in_a_stable_version_directory'
        wait_gone(Path(check['temporary']))
        info = GetFileVersionInfo(str(target), '\\')
        actual = (info['FileVersionMS'] >> 16, info['FileVersionMS'] & 65535,
                  info['FileVersionLS'] >> 16, info['FileVersionLS'] & 65535)
        assert actual == tuple(map(int, APP_VERSION.split('.'))) + (0,)
        record = {'case': 'release-payload', 'version': APP_VERSION,
                  'dependencies_ready': True, 'fresh_runtime': True, 'temporary_files_cleaned': True}
        write(work / 'product-results.json', record)
        print(json.dumps(record), flush=True)
        return record
    finally:
        clean_own_processes(app)


def run_case(work, case, old, new, environment):
    app = work / ('case-' + case) / '程序 更新'
    (app / '_wip').mkdir(parents=True)
    target = app / 'ChatGPTnx.exe'
    shutil.copyfile(old, target)
    sentinel = {app / 'accounts.txt': b'synthetic-accounts', app / '_data/settings.json': b'{"synthetic":true}'}
    for path, content in sentinel.items():
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    write(app / '_wip/fixture.json', {'case': case, 'candidate': str(new)})
    cleanup = seed_cleanup(app) if case == 'cleanup' else {}
    begin, process = {}, None
    started = time.monotonic()
    try:
        with (app / '_wip/parent.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(target), '--begin'], cwd=app, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=HIDDEN)
            begin = wait_json(app / '_wip/begin.json', timeout=25)
            batch = Path(begin['batch'])
            result = wait_json(batch / 'result.json')
            successful = case in ('success', 'legacy', 'cleanup')
            expected = 'complete' if successful else ('failed' if case == 'checksum' else 'rolled_back')
            assert result['status'] == expected, result
            process.wait(timeout=10)
            begin = wait_json(app / '_wip/begin.json')
            assert begin['accepted'] == (case != 'checksum'), begin['accepted']
            if successful:
                candidate = wait_json(app / '_wip/candidate.json', timeout=10)
                assert candidate['build'] == 'new' and candidate['runtime'] != begin['old_runtime']
                assert digest(target) == digest(new)
                assert (batch / 'previous.exe').read_bytes() == old.read_bytes()
                # Launcher cache and interpreter extraction both live under _wip.
                assert app / '_wip' in Path(candidate['runtime']).parents
                assert Path(candidate['runtime']).is_dir(), 'versioned_core_was_removed'
                wait_gone(Path(candidate['temporary']))
            else:
                assert digest(target) == digest(old)
                if case != 'checksum':
                    restored = wait_json(app / '_wip/restored.json', timeout=10)
                    assert restored['build'] in ('old', 'legacy')
                    assert restored['temporary'] != begin['old_temporary'], 'rollback_reused_old_temporary_directory'
                    if restored['build'] == 'old':
                        assert restored['runtime'] == begin['old_runtime'], 'rollback_did_not_reuse_verified_core'
                    else:
                        assert restored['runtime'] != begin['old_runtime']
                    recovery = Path(result['recovery_batch'])
                    assert recovery != batch
                    original_plan = wait_json(batch / 'plan.json')
                    recovery_plan = wait_json(recovery / 'plan.json')
                    assert original_plan['token'] != recovery_plan['token']
                    assert original_plan['sha256'] == digest(new), 'candidate_plan_was_mutated'
                    assert (batch / 'failed.exe').is_file()
                    if restored['build'] == 'legacy':
                        wait_gone(Path(restored['runtime']))
                    else:
                        wait_gone(Path(restored['temporary']))
            for path, content in sentinel.items():
                assert path.read_bytes() == content, path.name
            wait_gone(Path(begin['old_runtime']) if begin['legacy'] else Path(begin['old_temporary']))
            if case in ('rollback', 'timeout', 'stale-ack', 'compat-rollback'):
                wait_gone(batch / 'runtime-candidate')
            if cleanup:
                wait_gone(cleanup['completed'])
                wait_gone(cleanup['obsolete_cache'])
                for name in ('failed', 'legacy', 'unknown'):
                    assert (cleanup[name] / 'previous.exe').read_bytes() == b'synthetic-backup'
                assert (cleanup['unknown'] / 'user-file.txt').read_bytes() == b'user-owned'
                current_cache = app / '_wip/runtime' / candidate['payload_id']
                old_cache = app / '_wip/runtime' / begin['old_payload_id']
                assert current_cache.is_dir() and old_cache.is_dir(), 'current_or_previous_cache_removed'
            assert 'Failed to' not in (app / '_wip/parent.log').read_text(encoding='utf-8', errors='replace')
        record = {'case': case, 'status': result['status'], 'data_preserved': True,
                  'fresh_runtime': True, 'elapsed_seconds': round(time.monotonic() - started, 2)}
        print(json.dumps(record), flush=True)
        return record
    finally:
        clean_own_processes(app)
        if process and process.poll() is None:
            process.wait(timeout=10)


def main():
    if os.name != 'nt':
        raise SystemExit('Windows is required')
    cases = ('success', 'legacy', 'rollback', 'compat-rollback', 'timeout', 'checksum', 'stale-ack', 'cleanup')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=cases, action='append')
    parser.add_argument('--legacy-source', type=Path, help='v1.3.1 source ZIP when Git history is unavailable')
    parser.add_argument('--product', type=Path, help='also check the built release EXE with an inherited old runtime')
    parser.add_argument('--fixtures-from', type=Path, help='reuse an already built fixture batch under this project/_wip')
    args = parser.parse_args()
    work = ROOT / '_wip/update-windows' / time.strftime('%Y%m%d-%H%M%S')
    work.mkdir(parents=True)
    scratch = work / 'scratch'
    scratch.mkdir()
    environment = dict(os.environ, TEMP=str(scratch), TMP=str(scratch),
                       PYINSTALLER_CONFIG_DIR=str(work / 'cache'), PYTHONDONTWRITEBYTECODE='1')
    for key in list(environment):
        if key.startswith('CHATGPTNX_') or key.startswith('_PYI_') or key == '_MEIPASS2':
            del environment[key]
    build = subprocess.run([sys.executable, '-B', 'tools/build.py'], cwd=ROOT, env=environment,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=HIDDEN,
                           text=True, encoding='utf-8', errors='replace')
    if build.returncode:
        raise RuntimeError('updater_build_failed:\n' + build.stdout[-4000:])
    if args.fixtures_from:
        previous = args.fixtures_from.resolve()
        if ROOT / '_wip' not in previous.parents:
            raise RuntimeError('fixtures_outside_project_work_directory')
        old, new, legacy = (previous / 'dist' / name for name in
                            ('launcher-old.exe', 'launcher-new.exe', 'fixture-legacy.exe'))
        if not all(path.is_file() for path in (old, new, legacy)):
            raise RuntimeError('fixture_batch_is_incomplete')
    else:
        old = build_fixture(work, 'old', environment, args.legacy_source)
        new = build_fixture(work, 'new', environment, args.legacy_source)
        legacy = build_fixture(work, 'legacy', environment, args.legacy_source)
    records = [run_case(work, case, legacy if case in ('legacy', 'compat-rollback') else old, new, environment)
               for case in (args.case or cases)]
    write(work / 'results.json', records)
    if args.product:
        verify_product(work, args.product, environment)
    print('Frozen updater regression passed: ' + str(len(records)) + ' cases', flush=True)


if __name__ == '__main__':
    main()
