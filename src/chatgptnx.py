"""ChatGPTnx entry point. Runtime data stays beside the executable."""
from pathlib import Path
import argparse
import ctypes
import json
import os
import sys
import time
from nx.storage import Paths
from nx.core import Service

def main():
    if os.name == 'nt':
        # Explicit AppUserModelID: Explorer binds tray/taskbar identity to it.
        # Tauri apps (Cove) get this from their bundle identifier; without one
        # Windows falls back to exe path + window class, which is less stable.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('nx.chatgptnx.app')
    parser = argparse.ArgumentParser(description='ChatGPTnx')
    parser.add_argument('--once', action='store_true', help='query once and print redacted status')
    parser.add_argument('--home', type=Path, help='application data root; defaults beside executable')
    parser.add_argument('--bridge-selfcheck', metavar='TARGET', help='explicitly send one read-only connection diagnostic to a task')
    parser.add_argument('--source-thread', help='real source task for the explicitly authorized diagnostic')
    parser.add_argument('--selfcheck-report', type=Path, help='new diagnostic journal path (refuses to reuse an existing file)')
    parser.add_argument('--locate-task', metavar='TARGET', help='open an existing task by ID only; never send or start the service')
    parser.add_argument('--acceptance-relay', metavar='THREAD', help='explicit one-relay test; requires exactly this one active task')
    args = parser.parse_args()
    if args.acceptance_relay and (not args.home or not args.selfcheck_report or args.once or args.locate_task or args.bridge_selfcheck):
        parser.error('relay acceptance requires --home and --selfcheck-report, without other actions')
    if args.locate_task:
        if not args.home or not args.selfcheck_report or args.bridge_selfcheck:
            parser.error('location check requires --home and --selfcheck-report; no message selfcheck')
        from nx.desktop_location import locate_task
        from nx.storage import atomic_bytes
        with args.selfcheck_report.open('x', encoding='utf-8') as stream:
            json.dump({'state': 'started', 'sent': False}, stream)
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        state, reason = locate_task(home, args.locate_task, args.home / '_data' / 'state.json')
        atomic_bytes(args.selfcheck_report, json.dumps(
            {'state': state, 'reason': reason, 'sent': False}).encode('utf-8'))
        return
    if args.bridge_selfcheck:
        if not args.source_thread or not args.selfcheck_report:
            parser.error('selfcheck requires --source-thread and --selfcheck-report')
        from nx.app_bridge import explicit_selfcheck
        explicit_selfcheck(args.source_thread, args.bridge_selfcheck, args.selfcheck_report)
        return
    frozen = getattr(sys, 'frozen', False)
    root = args.home or Path(os.environ.get('CHATGPTNX_HOME') or (Path(sys.executable).parent if frozen else Path(__file__).resolve().parents[1]))
    resources = Path(getattr(sys, '_MEIPASS', root / '_wip' / 'build' / 'resources'))
    mutex = None
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        mutex = kernel.CreateMutexW(None, False, 'ChatGPTnx_SingleInstance')
        if not mutex:
            raise OSError('无法创建单实例锁')
        if ctypes.get_last_error() == 183:
            print('ChatGPTnx 已在运行；请通过托盘打开。')
            return
    elif not args.once:
        raise SystemExit('桌面应用需要 Windows + WebView2；浏览器预览请打开 demo.html。')
    paths = Paths(root, resource_root=resources)
    service = Service(paths)
    if args.acceptance_relay:
        from nx.acceptance import relay_once
        relay_once(service, args.acceptance_relay, args.selfcheck_report)
    elif args.once:
        service.refresh()
        while service.operation:
            time.sleep(.1)
        data = service.get_data()
        for account in data['accounts']:
            account['email'] = account['email'].split('@')[0][:2] + '***'
        if data['current']:
            data['current'] = data['current'].split('@')[0][:2] + '***'
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        from nx.desktop import Desktop
        Desktop(service).run()
    if mutex:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)

if __name__ == '__main__':
    main()
