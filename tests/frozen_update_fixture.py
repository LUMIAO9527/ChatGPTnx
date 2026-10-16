"""One-file update fixture. Never opens the product UI or reads real accounts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from nx.updater import UpdateManager, digest_file, startup_ack
from nx.version import APP_VERSION


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def main():
    root = Path(sys.executable).resolve().parent
    config = json.loads((root / '_wip' / 'fixture.json').read_text(encoding='utf-8'))
    parser = argparse.ArgumentParser()
    parser.add_argument('--begin', action='store_true')
    parser.add_argument('--update-ack', type=Path)
    parser.add_argument('--update-token')
    args = parser.parse_args()
    build = (Path(sys._MEIPASS) / 'fixture-build.txt').read_text(encoding='utf-8')
    if args.begin:
        manager = UpdateManager(root, sys._MEIPASS, current=APP_VERSION)
        batch = root / '_wip' / 'update' / uuid.uuid4().hex
        batch.mkdir(parents=True)
        stage = batch / 'ChatGPTnx.new.exe'
        shutil.copyfile(config['candidate'], stage)
        manager.batch = batch
        manager.asset = {'version': APP_VERSION, 'sha256': digest_file(stage),
                         'size': stage.stat().st_size}
        manager.state['status'] = 'ready'
        def launch(*arguments, **kwargs):
            if config['case'] == 'checksum':
                with stage.open('ab') as stream:
                    stream.write(b'tampered-fixture')
            helper = subprocess.Popen(*arguments, **kwargs)
            write(root / '_wip' / 'begin.json', {'batch': str(batch), 'helper_pid': helper.pid,
                  'worker_pid': os.getpid(), 'loader_pid': os.getppid(),
                  'old_runtime': str(sys._MEIPASS)})
            return helper
        if not manager.install(os.getpid(), popen=launch)['ok']:
            raise RuntimeError('fixture_install_failed')
        return
    if args.update_ack:
        if config['case'] == 'rollback' and build == 'new':
            raise SystemExit(17)
        if config['case'] == 'timeout' and build == 'new':
            time.sleep(90)
            raise SystemExit(18)
        startup_ack(root, sys.executable, args.update_ack, args.update_token)
        marker = 'restored.json' if build == 'old' else 'candidate.json'
        write(root / '_wip' / marker, {'build': build, 'runtime': str(sys._MEIPASS)})
        time.sleep(.5)
    else:
        write(root / '_wip' / 'restored.json', {'build': build, 'runtime': str(sys._MEIPASS)})
        time.sleep(.5)


if __name__ == '__main__':
    main()
