"""Frozen update acceptance fixture with synthetic data and the real updater."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types
import uuid

from nx.updater import UpdateManager, digest_file, startup_ack
from nx.version import APP_VERSION


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--begin', action='store_true')
    parser.add_argument('--home', type=Path)
    parser.add_argument('--launcher-executable', type=Path)
    parser.add_argument('--launcher-pid', type=int)
    parser.add_argument('--update-ack', type=Path)
    parser.add_argument('--update-token')
    args = parser.parse_args()
    root = args.home or Path(sys.executable).resolve().parent
    executable = args.launcher_executable or Path(sys.executable)
    config = json.loads((root / '_wip' / 'fixture.json').read_text(encoding='utf-8'))
    build = (Path(sys._MEIPASS) / 'fixture-build.txt').read_text(encoding='utf-8')
    legacy = None
    if build == 'legacy':
        legacy = types.ModuleType('nx.legacy_updater')
        exec(compile((Path(sys._MEIPASS) / 'legacy_updater.py').read_text(encoding='utf-8'),
                     'legacy_updater.py', 'exec'), legacy.__dict__)
        legacy.APP_VERSION = '1.3.1'
    if args.begin:
        manager_type = legacy.UpdateManager if legacy and config['case'] == 'legacy' else UpdateManager
        manager = manager_type(root, sys._MEIPASS, executable=executable,
                               current='1.3.1' if legacy else APP_VERSION)
        batch = root / '_wip' / 'update' / uuid.uuid4().hex
        batch.mkdir(parents=True)
        stage = batch / 'ChatGPTnx.new.exe'
        shutil.copyfile(config['candidate'], stage)
        manager.batch = batch
        manager.asset = {'version': APP_VERSION, 'sha256': digest_file(stage), 'size': stage.stat().st_size}
        manager.state['status'] = 'ready'
        record = {'batch': str(batch), 'worker_pid': os.getpid(), 'loader_pid': os.getppid(),
                  'old_temporary': os.environ.get('TEMP'), 'legacy': build == 'legacy',
                  'old_runtime': str(sys._MEIPASS), 'old_payload_id': os.environ.get('CHATGPTNX_PAYLOAD_ID', '')}
        def launch(*arguments, **kwargs):
            if config['case'] == 'checksum':
                with stage.open('ab') as stream:
                    stream.write(b'tampered-fixture')
            helper = subprocess.Popen(*arguments, **kwargs)
            record['helper_pid'] = helper.pid
            write(root / '_wip' / 'begin.json', record)
            return helper
        result = manager.install(args.launcher_pid or os.getpid(), popen=launch)
        record['accepted'] = bool(result['ok'])
        write(root / '_wip' / 'begin.json', record)
        if config['case'] == 'checksum':
            assert not result['ok'] and manager.snapshot()['status'] == 'ready'
            time.sleep(.5)
        else:
            assert result['ok'], result
        return
    if args.update_ack:
        if config['case'] in ('rollback', 'compat-rollback') and build == 'new':
            raise SystemExit(17)
        if config['case'] == 'timeout' and build == 'new':
            time.sleep(90)
            raise SystemExit(18)
        if config['case'] == 'stale-ack' and build == 'new':
            write(args.update_ack, {'ready': True, 'token': args.update_token,
                                   'version': '0.0.1', 'pid': os.getpid()})
            time.sleep(.7)
            raise SystemExit(19)
        (legacy.startup_ack if legacy else startup_ack)(root, executable, args.update_ack, args.update_token)
        marker = 'candidate.json' if build == 'new' else 'restored.json'
        write(root / '_wip' / marker, {'build': build, 'runtime': str(sys._MEIPASS),
                                     'temporary': os.environ.get('TEMP'),
                                     'payload_id': os.environ.get('CHATGPTNX_PAYLOAD_ID', '')})
        time.sleep(1)


if __name__ == '__main__':
    main()
