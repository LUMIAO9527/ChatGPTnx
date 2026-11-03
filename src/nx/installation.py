"""Windows Apps registration and the application's own uninstall confirmation."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .credentials import assert_safe_path,secure_path
from .storage import atomic_bytes
from .version import APP_VERSION

APP_KEY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ChatGPTnx'
REQUEST='uninstall-request.json'

def register_application(executable):
    import winreg
    executable=Path(executable).resolve()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,APP_KEY) as key:
        for name,value in {'DisplayName':'ChatGPTnx','DisplayVersion':APP_VERSION,'Publisher':'LUMIAO9527',
                           'InstallLocation':str(executable.parent),'DisplayIcon':str(executable),
                           'UninstallString':f'"{executable}" --uninstall',
                           'URLInfoAbout':'https://github.com/LUMIAO9527/ChatGPTnx'}.items():
            winreg.SetValueEx(key,name,0,winreg.REG_SZ,value)
        for name in ('NoModify','NoRepair'):winreg.SetValueEx(key,name,0,winreg.REG_DWORD,1)

def request_uninstall(root):
    root=assert_safe_path(Path(root).resolve())
    if not (root/'_data').is_dir():return False
    atomic_bytes(root/'_data'/REQUEST,b'{}')
    return True

def plain_tree(path):
    assert_safe_path(path)
    if path.is_dir():
        for child in path.iterdir():plain_tree(child)

def uninstall_plan(service,keep):
    if type(keep) is not bool:raise ValueError('请选择是否保留账号与数据')
    root=service.paths.root.resolve();executable=Path(service.executable or '').resolve()
    if root.parent==root or executable.parent!=root or executable.name.lower()!='chatgptnx.exe' or not executable.is_file():
        raise ValueError('请从安装的 ChatGPTnx 程序中卸载')
    targets=[executable,root/'_wip'/'runtime',root/'_wip'/'run',root/'_wip'/'update']
    if not keep:targets.extend((root/'snapshots',root/'_data',root/'accounts.txt',root/'.chatgptnx-location'))
    for target in targets:
        if not target.is_relative_to(root):raise ValueError('应用清理目录不合法')
        if target.exists():plain_tree(target)
    return {'schema':1,'root':str(root),'executable':str(executable),'keep':keep,'token':uuid.uuid4().hex,
            'sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'targets':[str(t) for t in targets],'pids':[os.getpid()]+([service.update_parent_pid] if service.update_parent_pid else [])}

def start_uninstall(service,keep,*,ready_timeout=15):
    if not getattr(sys,'frozen',False):raise ValueError('请从安装的 ChatGPTnx 程序中卸载')
    if not service.gate.acquire(blocking=False):raise ValueError('请先完成当前操作')
    desktop=False;committed=False;process=None
    try:
        if service.state.get('adding') or service.state.get('reauth') or service.updater.snapshot()['status'] in ('downloading','installing'):
            raise ValueError('请先完成当前的登录或更新')
        if (service.resumer.summary() or {}).get('phase') in ('switching','resuming') or service.stop.is_set():
            raise ValueError('请先完成当前接续')
        desktop=service.desktop_gate.acquire(blocking=False)
        if not desktop:raise ValueError('请先完成当前接续')
        plan=uninstall_plan(service,keep)
        batch=service.paths.root/'_wip'/'uninstall'/uuid.uuid4().hex
        assert_safe_path(batch);batch.mkdir(parents=True);secure_path(batch)
        worker=batch/'uninstall.ps1';document=batch/'plan.json'
        atomic_bytes(worker,(service.paths.resources/'uninstall.ps1').read_bytes(),private=True)
        atomic_bytes(document,json.dumps(plan,ensure_ascii=False).encode('utf-8'),private=True)
        command=[str(Path(os.environ.get('WINDIR',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                 '-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(worker),'-Plan',str(document)]
        process=subprocess.Popen(command,cwd=str(batch),creationflags=0x08000000,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+ready_timeout;prepared=False
        while time.monotonic()<deadline:
            if process.poll() is not None:break
            try:
                ready=json.loads(assert_safe_path(batch/'prepared.json').read_text(encoding='utf-8-sig'))
                if ready.get('token')==plan['token'] and ready.get('pid')==process.pid:
                    prepared=True
                    break
            except (OSError,ValueError,TypeError,AttributeError):pass
            time.sleep(.05)
        if not prepared or process.poll() is not None:
            raise ValueError('卸载组件未能就绪，请重试')
        atomic_bytes(batch/'commit.json',json.dumps({'token':plan['token']}).encode('utf-8'),private=True)
        service.stop.set()
        committed=True
        return {'ok':True}
    finally:
        if not committed:
            try:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            finally:
                if desktop:service.desktop_gate.release()
                service.gate.release()
