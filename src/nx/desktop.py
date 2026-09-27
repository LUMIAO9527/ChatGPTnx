"""Windows tray, native hotkeys and one reusable WebView2 window."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from .design import PANEL_CONFIG as DEFAULT_CONFIG

CHATGPT_DEFAULT_AUMID = 'OpenAI.Codex_2p2nqsd0c76g0!App'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def system_prefers_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return int(winreg.QueryValueEx(key, 'AppsUseLightTheme')[0]) == 0
    except (OSError, ValueError, TypeError, ImportError):
        return False


def chatgpt_running() -> bool:
    """True while the ChatGPT desktop app (ChatGPT.exe) is running.

    Toolhelp snapshot walk, cached for a few seconds: get_data() is polled.
    """
    now = time.time()
    cached = getattr(chatgpt_running, '_cache', None)
    if cached and now - cached[0] < 4:
        return cached[1]
    found = False
    try:
        if os.name == 'nt':
            k32 = ctypes.windll.kernel32
            TH32CS_SNAPPROCESS = 0x02
            class PE32(ctypes.Structure):
                _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                            ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)), ('th32ModuleID', wt.DWORD),
                            ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', wt.LONG),
                            ('dwFlags', wt.DWORD), ('szExeFile', wt.WCHAR * 260)]
            # HANDLE is pointer-sized on Win64; ctypes otherwise truncates it.
            k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
            k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
            k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PE32)]
            k32.Process32FirstW.restype = wt.BOOL
            k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PE32)]
            k32.Process32NextW.restype = wt.BOOL
            k32.CloseHandle.argtypes = [wt.HANDLE]
            snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snap and snap != ctypes.c_void_p(-1).value:
                entry = PE32()
                entry.dwSize = ctypes.sizeof(PE32)
                ok = k32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    if entry.szExeFile.lower() == 'chatgpt.exe':
                        found = True
                        break
                    ok = k32.Process32NextW(snap, ctypes.byref(entry))
                k32.CloseHandle(snap)
    except Exception:
        found = False
    chatgpt_running._cache = (now, found)
    return found


def chatgpt_foreground() -> bool:
    """Only reclaim focus when the desktop app itself took the foreground."""
    if os.name != 'nt':
        return False
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    u32.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return False
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = wt.DWORD(len(name))
        k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD,
                                                     wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wt.BOOL
        if not k32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            return False
        return Path(name.value).name.lower() == 'chatgpt.exe'
    finally:
        k32.CloseHandle(handle)


def launch_chatgpt():
    """Ask the Windows shell to activate ChatGPT as an independent application."""
    neutral_cwd = os.environ.get('WINDIR') or os.environ.get('SystemRoot')
    aumid = getattr(launch_chatgpt, '_aumid', None)
    if not aumid:
        aumid = CHATGPT_DEFAULT_AUMID
        try:
            result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-ExecutionPolicy', 'Bypass', '-Command',
                                     "(Get-StartApps | Where-Object { $_.Name -eq 'ChatGPT' } "
                                     "| Select-Object -First 1).AppID"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=20, creationflags=0x08000000, cwd=neutral_cwd)
            found = result.stdout.decode('utf-8', errors='replace').strip()
            if found:
                aumid = found
                launch_chatgpt._aumid = aumid
        except Exception:
            pass
    subprocess.Popen(['explorer.exe', f'shell:AppsFolder\\{aumid}'],
                     creationflags=0x08000000, cwd=neutral_cwd)  # shell owns the app lifetime
    return {'ok': True}


def set_autostart(enable: bool):
    """Register/unregister HKCU Run. Command always targets the frozen exe when
    deployed; source runs register pythonw with the entry script."""
    import winreg
    try:
        if enable:
            if getattr(sys, 'frozen', False):
                command = f'"{Path(sys.executable)}"'
            else:
                script = Path(__file__).resolve().parents[1] / 'chatgptnx.py'
                pythonw = Path(sys.executable).with_name('pythonw.exe')
                command = f'"{pythonw}" "{script}"'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, 'ChatGPTnx', 0, winreg.REG_SZ, command)
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, 'ChatGPTnx')
    except OSError as error:
        return {'ok': False, 'error': f'开机自启设置失败：{type(error).__name__}'}
    return {'ok': True}


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT),
                ('dwFlags', wt.DWORD), ('szDevice', wt.WCHAR * 32)]


def popup_position(icon, work, monitor, size, gap=8, margin=8):
    """Place a popup next to a tray icon, independent of taskbar edge.

    All inputs and the returned coordinates are physical pixels. Keeping this
    calculation pure makes multi-monitor/DPI edge cases testable without a
    live Explorer process.
    """
    il, it, ir, ib = icon
    wl, wt_, wr, wb = work
    ml, mt, mr, mb = monitor
    width, height = size
    if wb < mb:
        edge = 'bottom'
    elif wt_ > mt:
        edge = 'top'
    elif wl > ml:
        edge = 'left'
    elif wr < mr:
        edge = 'right'
    else:
        cx, cy = (il + ir) / 2, (it + ib) / 2
        edge = min({'left': abs(cx - ml), 'right': abs(mr - cx),
                    'top': abs(cy - mt), 'bottom': abs(mb - cy)}, key=lambda key: {
                        'left': abs(cx - ml), 'right': abs(mr - cx),
                        'top': abs(cy - mt), 'bottom': abs(mb - cy)}[key])
    if edge == 'bottom':
        x, y = round((il + ir - width) / 2), it - gap - height
    elif edge == 'top':
        x, y = round((il + ir - width) / 2), ib + gap
    elif edge == 'left':
        x, y = ir + gap, round((it + ib - height) / 2)
    else:
        x, y = il - gap - width, round((it + ib - height) / 2)
    x = max(wl + margin, min(x, wr - width - margin))
    y = max(wt_ + margin, min(y, wb - height - margin))
    return x, y


def promote_tray_icon():
    """Win11 keeps per-exe tray placement under HKCU\\...NotifyIconSettings; a
    new executable defaults to the hidden overflow area. Self-promote our entry
    to the visible tray (IsPromoted=1), retrying while Explorer registers the
    freshly created icon. Same mechanism Cove uses."""
    if not getattr(sys, 'frozen', False):
        return  # source runs share python.exe; never touch other tools' entries
    import winreg
    my_exe = str(Path(sys.executable).resolve()).lower()

    def attempt() -> int:
        found = 0
        try:
            parent = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Control Panel\NotifyIconSettings')
        except OSError:
            return 0
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(parent, index)
                index += 1
            except OSError:
                break
            try:
                with winreg.OpenKey(parent, sub, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    try:
                        exe = str(winreg.QueryValueEx(key, 'ExecutablePath')[0]).lower()
                    except OSError:
                        continue
                    if exe != my_exe:
                        continue
                    try:
                        current = int(winreg.QueryValueEx(key, 'IsPromoted')[0] or 0)
                    except OSError:
                        current = 0
                    if not current:
                        winreg.SetValueEx(key, 'IsPromoted', 0, winreg.REG_DWORD, 1)
                    found += 1
            except OSError:
                continue
        return found

    for delay in (2, 4, 8, 15):
        time.sleep(delay)
        if attempt():
            return


def _find_hwnd():
    """Return the ChatGPTnx HWND without truncating it on 64-bit Windows."""
    if os.name != 'nt':
        return None
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    return user32.FindWindowW(None, 'ChatGPTnx')

class Hotkeys:
    def __init__(self, callback, report):
        self.callback, self.report = callback, report
        self.thread = None
        self.thread_id = None
        self.signature = None
        self.lock = threading.Lock()
        self.ready = threading.Event()

    def configure(self, assignments):
        signature = tuple((email, shortcut) for email, shortcut in assignments if shortcut)
        with self.lock:
            if signature == self.signature:
                return
            if self.thread and self.thread.is_alive():
                self.ready.wait(2)
                if self.thread_id:
                    ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
                self.thread.join(2)
                if self.thread.is_alive():
                    return
            self.signature = signature
            self.ready.clear()
            self.thread = threading.Thread(target=self._loop, args=(signature,), daemon=True)
            self.thread.start()

    def _loop(self, assignments):
        user = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self.ready.set()
        registered = {}
        try:
            for ident, (email, shortcut) in enumerate(assignments, 1):
                parts = shortcut.split('+')
                modifier = 0x4000 | sum({'alt': 1, 'ctrl': 2, 'shift': 4}[part] for part in parts[:-1])
                if user.RegisterHotKey(None, ident, modifier, ord(parts[-1])):
                    registered[ident] = email
            self.report({email: ident in registered for ident, (email, _) in enumerate(assignments, 1)})
            while user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312 and int(msg.wParam) in registered:
                    self.callback(registered[int(msg.wParam)])
        finally:
            for ident in registered:
                user.UnregisterHotKey(None, ident)

    def close(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)

class Bridge:
    def __init__(self, service, host):
        self._service, self._host = service, host
    def get_data(self): return self._service.get_data()
    def dismiss_error(self, error_id): return self._service.dismiss_error(error_id)
    def get_resume_details(self): return self._service.get_resume_details()
    def clear_resume_history(self): return self._service.clear_resume_history()
    def mark_resume_seen(self, session_id): return self._service.mark_resume_seen(session_id)
    def retry_resume_task(self, session_id, thread_id):
        return self._service.retry_resume_task(session_id, thread_id)
    def open_resume_task(self, thread_id):
        from .desktop_resume import THREAD_ID, navigate_existing_task
        if not THREAD_ID.fullmatch(str(thread_id)):
            return {'ok': False, 'error': '任务编号不合法'}
        if not any(item['thread_id'] == thread_id for session in self._service.get_resume_details()
                   for item in session['items']):
            return {'ok': False, 'error': '任务记录已过期'}
        if not self._service.desktop_gate.acquire(blocking=False):
            return {'ok': False, 'error': '正在切换或接续，请稍后打开'}
        try:
            return navigate_existing_task(self._service.paths.home,
                                          self._service.paths.desktop_resume_ps1, thread_id,
                                          self._service.paths.data / 'state.json')
        finally:
            self._service.desktop_gate.release()
    def refresh(self): return self._service.refresh()
    def refresh_one(self, email): return self._service.refresh(email)
    def switch(self, email): return self._service.switch(email)
    def relay(self, email=None): return self._service.relay(email)
    def remove(self, email): return self._service.remove(email)
    def add_start(self): return self._service.add_start()
    def adopt_current(self): return self._service.adopt_current()
    def add_cancel(self): return self._service.add_cancel()
    def add_finish(self): return self._service.add_finish()
    def reauth_start(self, email): return self._service.reauth_start(email)
    def reauth_cancel(self): return self._service.reauth_cancel()
    def reauth_finish(self): return self._service.reauth_finish()
    def set_account_hotkey(self, email, shortcut=None): return self._service.set_account_hotkey(email, shortcut)
    def set_relay_pick(self, email=None): return self._service.set_relay_pick(email)
    def set_auto_relay_account(self, email, enabled): return self._service.set_auto_relay_account(email, enabled)
    def set_preferences(self, changes):
        if not isinstance(changes, dict):
            return {'ok': False, 'error': '设置格式不合法'}
        changes = dict(changes)
        autostart = changes.pop('autostart', None)
        if autostart is not None and type(autostart) is not bool:
            return {'ok': False, 'error': '开机自启需要布尔值'}
        result = self._service.set_preferences(changes)
        if not result.get('ok'):
            return result
        if autostart is not None:
            result = set_autostart(bool(autostart))
            if result.get('ok'):
                self._service.state.setting(autostart=bool(autostart))
                self._service.notify()
        return result
    def launch_chatgpt(self):
        return launch_chatgpt()
    def chatgpt_status(self):
        return {'running': chatgpt_running()}
    def update_account_meta(self, email, changes):
        return self._service.update_account_meta(email, changes)

    def set_account_meta(self, email, alias='', subscription_date=None):
        return self._service.set_account_meta(email, alias, subscription_date)
    def get_usage(self, email, force=False): return self._service.get_usage(email, force)
    def read_usage(self, email): return self._service.read_usage(email)
    def get_archives(self): return self._service.get_archives()
    def restore(self, key): return self._service.restore(key)
    def get_usage_all(self, force=False): return self._service.get_usage_all(force)
    def read_usage_all(self, days=30): return self._service.read_usage_all(days)
    def get_subscription(self, email, force=False): return self._service.get_subscription(email, force)
    def resize_panel(self, view='home'):
        if view not in ('home', 'workspace'):
            return {'ok': False, 'error': '窗口状态不合法'}
        self._host.view = view
        self._host.layout()
        return {'ok': True}
    def hide(self, reason='user'):
        self._host.hide(reason=reason)
        return {'ok': True}
    def quit(self):
        self._host.quit()
        return {'ok': True}

class Desktop:
    def __init__(self, service):
        self.service = service
        self.window = None
        self.icon = None
        self.visible = False
        self.view = 'home'
        self._shown_at = 0.0
        self.config = DEFAULT_CONFIG
        self.closing = False
        self.ready = threading.Event()
        self.last_layout = None
        self.last_notice = None
        self.last_auto_relay = None
        self.noticed = set()  # dedupe keys for one-shot balloon notices
        self._add_ready_seen = False
        self._hide_token = 0  # show() invalidates pending blur-confirm timers
        self._relay_restore = None
        self._relay_pinned = False
        self.tray_monitor = None  # HMONITOR remembered from the last tray click
        self.changed = threading.Event()
        self.hotkeys = Hotkeys(self.hotkey_switch, self.registered)
        self.service.listeners.append(self._on_service_change)

    def _on_service_change(self):
        self.changed.set()
        operation = self.service.operation
        if (operation and operation.get('kind') == 'switch' and self.visible
                and not self._relay_restore):
            self._relay_restore = {'id': operation['id'], 'visible': True,
                                   'scheduled': False, 'pinned': False}
        guard = self._relay_restore
        if not guard:
            return
        if operation and operation.get('id') == guard['id']:
            return
        result = self.service.last_result
        if result and result.get('id') == guard['id']:
            guard['result_ok'] = result.get('ok')
            guard['session_id'] = result.get('resume_session_id')
        if guard.get('result_ok'):
            session_id = guard.get('session_id')
            if not session_id:
                self.hide(reason='complete')
                return
            with self.service.resumer.lock:
                session = next((item for item in self.service.resumer.sessions
                                if item['id'] == session_id), None)
                phase = session.get('phase') if session else None
            if phase == 'done' or session is None:
                self.hide(reason='complete')
                return
        if guard['scheduled']:
            return
        guard['scheduled'] = True
        guard['deadline'] = time.monotonic() + 8
        timer = threading.Timer(1.8, self._restore_after_relay, args=(guard['id'],))
        timer.daemon = True
        timer.start()

    def registered(self, status):
        self.service.hotkey_status = status
        self.service.notify()

    def hotkey_switch(self, email):
        if self.service.operation or self.service.state.get('adding') or self.service.state.get('reauth'):
            if self.icon:
                self.icon.notify('请先完成当前操作。', 'ChatGPTnx')
            return
        result = self.service.switch(email)
        if not result.get('ok') and self.icon:
            self.icon.notify(result.get('error', '暂时无法切换'), 'ChatGPTnx')

    def layout(self):
        if not self.window or not self.ready.is_set() or not self.visible:
            return
        width, height = self.config['sizes'].get(self.view, self.config['sizes']['home'])
        key = (width, height)
        if key == self.last_layout:
            return
        self.last_layout = key
        self._dispatch_ui(self._apply_layout)

    def _dispatch_ui(self, callback):
        """Queue Python work onto WinForms without waiting for it.

        pywebview's public window methods use synchronous Control.Invoke. A
        tray/query thread can then hold the GIL while the UI thread waits for
        it, freezing both sides. BeginInvoke returns immediately and removes
        that circular wait.
        """
        try:
            from System import Action
            from webview.platforms.winforms import BrowserView
            form = BrowserView.instances.get(self.window.uid) if self.window else None
            if not form or form.IsDisposed:
                return False
            def guarded():
                try:
                    callback()
                except Exception as error:
                    self.service.log.warning('ui_dispatch_failed type=%s', type(error).__name__)
            form.BeginInvoke(Action(guarded))
            return True
        except Exception as error:
            self.service.log.warning('ui_dispatch_queue_failed type=%s', type(error).__name__)
            return False

    def _form(self):
        from webview.platforms.winforms import BrowserView
        return BrowserView.instances.get(self.window.uid) if self.window else None

    def _post_script(self, script):
        form = self._form()
        if form and getattr(form, 'browser', None) and getattr(form.browser, 'webview', None):
            form.browser.webview.ExecuteScriptAsync(script)

    def _physical_size(self, hwnd):
        width, height = self.config['sizes'].get(self.view, self.config['sizes']['home'])
        dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd) or 96)
        return round(width * dpi / 96), round(height * dpi / 96)

    def _apply_layout(self):
        hwnd = _find_hwnd()
        if not hwnd or not self.visible:
            return
        width, height = self._physical_size(hwnd)
        self._place_at_tray(width, height)
        self._apply_native_shape()

    def _apply_native_shape(self):
        """Give the frameless WebView a real Windows window shape.

        CSS border-radius only rounds the page; the HWND remains rectangular and
        exposes WebView's background in the four corners.  DWM supplies the
        smooth Win11 corner/shadow and SetWindowRgn is the hard clip fallback
        (also fixes Win10 and frameless cases where DWM does not infer corners).
        Radius is scaled from logical CSS px to the window DPI.
        """
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            # ctypes defaults to 32-bit int return values. HWND/HRGN are pointer
            # sized, so leaving the defaults here can truncate handles on x64
            # Windows and produce the exact rectangular/black-corner artefact.
            user32.FindWindowW.restype = ctypes.c_void_p
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
            user32.GetWindowRect.restype = ctypes.c_bool
            user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
            user32.SetWindowRgn.restype = ctypes.c_int
            gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
            gdi32.DeleteObject.restype = ctypes.c_bool
            hwnd = user32.FindWindowW(None, 'ChatGPTnx')
        except Exception:
            return
        if not hwnd:
            return
        try:
            preference = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference))
            border_color = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color))
        except Exception:
            pass
        try:
            rect = wt.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
            dpi = 96
            try:
                value = int(user32.GetDpiForWindow(hwnd) or 96)
                dpi = value if value > 0 else 96
            except Exception:
                pass
            radius = max(1, round(float(self.config.get('radius', 16)) * dpi / 96))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1,
                                               radius * 2, radius * 2)
            if region:
                # Windows owns the region after a successful SetWindowRgn call.
                if not user32.SetWindowRgn(hwnd, region, True):
                    gdi32.DeleteObject(region)
        except Exception as error:
            self.service.log.warning('window_shape failed: %s', type(error).__name__)

    def _remove_from_taskbar(self):
        """The panel belongs to the tray icon: no taskbar button, no Alt+Tab.
        WS_EX_APPWINDOW wins over WS_EX_TOOLWINDOW, so the former must be
        cleared too. Win32-only (thread-safe): this also runs on the tray
        thread; the Form.ShowInTaskbar property is touched only from the UI
        thread in _style_window(), because pythonnet rejects cross-thread
        control access."""
        hwnd = _find_hwnd()
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongPtrW.restype = ctypes.c_longlong
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.SetWindowLongPtrW.restype = ctypes.c_longlong
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
            style = user32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
            user32.SetWindowLongPtrW(hwnd, -20, (style | 0x80) & ~0x40000)
        except Exception as error:
            self.service.log.warning('taskbar_style set failed: %s', type(error).__name__)

    def _monitor_info(self, icon_rect=None):
        """Monitor and work area containing the tray icon."""
        user32 = ctypes.windll.user32
        user32.MonitorFromRect.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD]
        user32.MonitorFromRect.restype = ctypes.c_void_p
        hmon = None
        if icon_rect:
            box = wt.RECT(icon_rect[0], icon_rect[1], icon_rect[2], icon_rect[3])
            hmon = user32.MonitorFromRect(ctypes.byref(box), 2)  # MONITOR_DEFAULTTONEAREST
        if not hmon:
            hmon = self.tray_monitor
        if not hmon:
            pt = wt.POINT()
            if user32.GetCursorPos(ctypes.byref(pt)):
                hmon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
        if not hmon:
            hmon = user32.MonitorFromPoint(wt.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        return info

    def _place_at_tray(self, width, height):
        """Anchor the panel to the actual notification icon rectangle."""
        try:
            icon = self.icon.rect() if self.icon else None
            info = self._monitor_info(icon)
            if info is None:
                return
            hwnd = _find_hwnd()
            if not hwnd:
                return
            if not icon:
                pt = wt.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                icon = (pt.x - 8, pt.y - 8, pt.x + 8, pt.y + 8)
            work = (info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
            monitor = (info.rcMonitor.left, info.rcMonitor.top,
                       info.rcMonitor.right, info.rcMonitor.bottom)
            x, y = popup_position(icon, work, monitor, (width, height))
            flags = 0x0004 | 0x0010  # NOZORDER | NOACTIVATE
            ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, width, height, flags)
        except Exception:
            pass

    def _style_window(self):
        """Apply the no-taskbar style and native shape. Win32-only, so it is
        safe from any thread (never touches the .NET Form object)."""
        self._remove_from_taskbar()
        self._apply_native_shape()

    def _style_at_birth(self):
        """Root fix for the blank-taskbar-window bug: the panel HWND is born
        with WinForms defaults (APPWINDOW). ready() runs before the window
        exists, so this one-shot thread waits for the handle to appear and
        styles it in the first instant of its life - before anything can show
        it. No repair loops afterwards; the watchdog stays only as a fuse."""
        for _ in range(150):  # ~15 s, one-shot wait, then give up
            if self.closing:
                return
            hwnd = _find_hwnd()
            if hwnd:
                self._style_window()
                self.service.log.info('panel_style_set_at_birth')
                return
            time.sleep(0.1)

    def _account_switch_active(self):
        operation = self.service.operation
        return bool(operation and operation.get('kind') == 'switch')

    def _set_panel_topmost(self, enabled, hwnd=None):
        """Keep a visible relay panel above ChatGPT without taking keyboard focus."""
        hwnd = hwnd or _find_hwnd()
        if not hwnd or os.name != 'nt':
            return False
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wt.UINT]
        user32.SetWindowPos.restype = wt.BOOL
        # NOMOVE | NOSIZE | NOACTIVATE | NOOWNERZORDER. Do change Z order.
        flags = 0x0002 | 0x0001 | 0x0010 | 0x0200
        if not user32.SetWindowPos(hwnd, ctypes.c_void_p(-1 if enabled else -2),
                                    0, 0, 0, 0, flags):
            return False
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        return bool(user32.GetWindowLongPtrW(hwnd, -20) & 0x00000008) == enabled

    def hide(self, *args, reason='user'):
        if reason in ('blur', 'focus'):
            if self._account_switch_active():
                return
            if self._relay_restore and chatgpt_foreground():
                return
        if reason in ('user', 'blur', 'focus', 'complete'):
            self._relay_restore = None
        if not self.window or not self.visible:
            return
        self.visible = False
        self._shown_at = 0.0
        def apply():
            form = self._form()
            if form:
                form.Hide()
            cleared = self._set_panel_topmost(False)
            if self._relay_pinned and not cleared:
                self.service.log.warning('panel_topmost_clear_unverified')
            self._relay_pinned = False
            self._post_script('window.nxHidden && window.nxHidden()')
        self._dispatch_ui(apply)

    def show(self, *args, relay_operation_id=None):
        # A single presentation, including upgrades from old compact settings.
        self._show_view('home', "window.nxShown && window.nxShown()",
                        relay_operation_id=relay_operation_id)

    def tray_menu(self):
        data = self.service.get_data()
        candidate = next((a for a in data['accounts'] if a['email'] == data.get('relay_email')), None)
        label = '下一棒' + (f" · {candidate.get('alias') or candidate['email'].split('@')[0]}" if candidate else '')
        return [
            {'label': label, 'enabled': bool(candidate) and not self.service.operation,
             'action': lambda: self.service.relay(candidate['email']) if candidate else None},
            {'label': '开机自启', 'checked': bool(data['settings'].get('autostart')),
             'action': self.toggle_autostart},
            {'label': '退出 ChatGPTnx', 'action': self.quit},
        ]

    def toggle_autostart(self):
        enabled = not bool(self.service.state.get('settings').get('autostart'))
        result = set_autostart(enabled)
        if result.get('ok'):
            self.service.state.setting(autostart=enabled)
            self.service.notify()
        elif self.icon:
            self.icon.notify(result.get('error', '开机自启设置失败'), 'ChatGPTnx')

    def _show_view(self, view, script, relay_operation_id=None):
        if not self.window:
            return
        self.visible = True
        self._shown_at = time.time()
        self._hide_token += 1  # cancel any blur confirmation still pending
        self.view = view
        self.last_layout = None
        def apply():
            if (relay_operation_id and
                    (not self._relay_restore or self._relay_restore['id'] != relay_operation_id)):
                return
            if relay_operation_id and not chatgpt_foreground():
                # The user switched elsewhere while this UI work was queued.
                self._relay_restore = None
                ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
                if ctypes.windll.user32.GetForegroundWindow() != _find_hwnd():
                    self.hide(reason='focus')
                return
            self._style_window()
            hwnd = _find_hwnd()
            form = self._form()
            if not hwnd or not form:
                if relay_operation_id:
                    self._retry_relay_restore(relay_operation_id)
                return
            if not relay_operation_id:
                self._set_panel_topmost(True, hwnd)
                self._relay_pinned = False
            width, height = self._physical_size(hwnd)
            self._place_at_tray(width, height)
            self._apply_native_shape()
            form.Show()
            form.Activate()
            self._post_script(script)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            if relay_operation_id:
                # Show() may recreate the HWND; pin the current visible handle.
                hwnd = _find_hwnd() or hwnd
                pinned = self._set_panel_topmost(True, hwnd)
                self._relay_pinned = pinned
                guard = self._relay_restore
                if guard and guard['id'] == relay_operation_id:
                    guard['pinned'] = pinned
                ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
                foreground = ctypes.windll.user32.GetForegroundWindow() == hwnd
                self.service.log.info('panel_reclaimed_after_relay visible=%s foreground=%s topmost=%s',
                                      bool(ctypes.windll.user32.IsWindowVisible(hwnd)),
                                      foreground, pinned)
                if not pinned and not foreground:
                    self.service.log.warning('panel_reclaim_unverified')
                if not pinned:
                    self._retry_relay_restore(relay_operation_id)
            self.service.log.info('panel_shown view=%s', view)
        if not self._dispatch_ui(apply):
            self.service.log.warning('panel_show_not_queued')
            if relay_operation_id:
                self._retry_relay_restore(relay_operation_id)

    def _retry_relay_restore(self, operation_id):
        guard = self._relay_restore
        if not guard or guard['id'] != operation_id or guard.get('pinned'):
            return
        if time.monotonic() >= guard.get('deadline', 0):
            self._relay_restore = None
            if self.visible and not chatgpt_foreground():
                self.hide(reason='focus')
            return
        timer = threading.Timer(.6, self._restore_after_relay, args=(operation_id,))
        timer.daemon = True
        timer.start()

    def _restore_after_relay(self, operation_id):
        guard = self._relay_restore
        if not guard or guard['id'] != operation_id:
            return
        if self.closing or not guard['visible']:
            self._relay_restore = None
            return
        if guard.get('pinned'):
            return
        if chatgpt_foreground():
            self.show(relay_operation_id=operation_id)
        elif time.monotonic() < guard.get('deadline', 0):
            self._retry_relay_restore(operation_id)
        else:
            self._relay_restore = None
            if self.visible:
                self.hide(reason='focus')

    def watch_focus(self):
        """Event-driven blur fallback, zero idle cost. The WebView 'blur' DOM
        event is unreliable under WinForms (taskbar/desktop clicks often fire
        nothing). SetWinEventHook(EVENT_SYSTEM_FOREGROUND) calls back only when
        the OS foreground actually changes. Confirmation and style repair run
        on plain threading.Timer objects: in this process WM_TIMER never gets
        delivered out of the pump thread's GetMessageW loop (observed: the
        hook callback fires while GetMessageW never returns), so nothing may
        depend on timer messages here."""
        if os.name != 'nt':
            return
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.SetWinEventHook.restype = ctypes.c_void_p
        user32.SetWinEventHook.argtypes = [wt.UINT, wt.UINT, wt.HINSTANCE,
                                           ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD]
        EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT = 0x0003, 0

        def ours():
            panel = _find_hwnd()
            tray = user32.FindWindowW('ChatGPTnxTrayWnd', None)
            return panel, tray

        def confirm_hide(token):
            if token != self._hide_token:
                return  # a show() happened after this confirmation was armed
            if not self.visible or not self.window:
                return
            foreground = user32.GetForegroundWindow()
            panel, tray = ours()
            if foreground and foreground not in (panel, tray):
                self.hide(reason='focus')

        def reassert_style():
            """WinForms may recreate the panel HWND and revert the taskbar
            style / visibility; repair on every foreground change."""
            hwnd = _find_hwnd()
            if not hwnd:
                return
            user32.GetWindowLongPtrW.restype = ctypes.c_longlong
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.SetWindowLongPtrW.restype = ctypes.c_longlong
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
            ex = user32.GetWindowLongPtrW(hwnd, -20)
            if not (ex & 0x80) or (ex & 0x40000):
                self.service.log.info('panel_style_reasserted')
                user32.SetWindowLongPtrW(hwnd, -20, (ex | 0x80) & ~0x40000)
            if not self.visible and user32.IsWindowVisible(hwnd):
                self.service.log.info('panel_visibility_reasserted')
                self.hide(reason='repair')

        def on_foreground(_hook, event, hwnd, _ido, _idc, _tid, _time):
            try:
                if not self.window:
                    return
                reassert_style()
                if not self.visible:
                    return
                panel, tray = ours()
                if not hwnd or hwnd in (panel, tray):
                    return
                token = self._hide_token
                confirm_hide(token)
            except Exception:
                pass

        WINEVENTPROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                          wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)
        proc = WINEVENTPROC(on_foreground)
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # force a message queue
        hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None,
                                      proc, 0, 0, WINEVENT_OUTOFCONTEXT)
        if not hook:
            self.service.log.warning('foreground_hook_failed')
            return
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWinEvent(hook)
    def toggle(self, *args):
        """Tray default action: click opens, click again hides."""
        icon_rect = self.icon.rect() if self.icon else None
        pt = wt.POINT()
        if icon_rect:
            pt.x = (icon_rect[0] + icon_rect[2]) // 2
            pt.y = (icon_rect[1] + icon_rect[3]) // 2
        if icon_rect or ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            monitor = ctypes.windll.user32.MonitorFromPoint(pt, 2)
            self.tray_monitor = monitor or None
        if self.visible:
            self.hide()
            return
        self.show()

    def _appearance_dark(self, settings):
        mode = (settings or {}).get('appearance', 'system')
        return mode == 'dark' or (mode == 'system' and system_prefers_dark())

    def update(self):
        while not self.service.stop.is_set():
            # State changes wake this immediately; otherwise update the tray
            # summary only every 60 s.  The old 1 s loop repeatedly reparsed all
            # credential snapshots even while the panel was hidden.
            self.changed.wait(60)
            self.changed.clear()
            data = self.service.get_data()
            add_ready = data.get('add_login_status') == 'ready'
            if add_ready and not self._add_ready_seen:
                self._add_ready_seen = True
                if self.icon:
                    self.icon.notify('登录已完成，确认保存这个账号。', 'ChatGPTnx')
                self.show()
            elif not data.get('adding'):
                self._add_ready_seen = False
            settings = data['settings']
            self.hotkeys.configure([(item['email'], item['shortcut']) for item in data['hotkeys']])
            account = next((a for a in data['accounts'] if a['email'] == data['current']), None)
            title = 'ChatGPTnx'
            low = False
            if account:
                title += ' · ' + (account.get('alias') or account['email'].split('@')[0])
                if account.get('ok'):
                    title += ' | ' + ' · '.join(f"{w['label']} 剩{100-w['used']:g}%" for w in account.get('windows', []))
                    fresh = time.time() - (account.get('fetched_at') or 0) <= 600
                    valid = all(w['resets_at'] > time.time() for w in account.get('windows', []))
                    threshold = 100 - int(settings.get('notify_low_threshold', 20))
                    low = bool(fresh and valid and any(w['used'] >= threshold for w in account.get('windows', [])))
            self.icon.title = title[:127]
            key = (data['current'], tuple((w['label'], w['resets_at']) for w in (account or {}).get('windows', [])))
            if settings.get('notify_low') and low and key != self.last_notice:
                self.icon.notify('当前账号有窗口剩余额度不足。打开面板查看下一棒。', 'ChatGPTnx')
                self.last_notice = key
            if settings.get('notify_credential', True):
                self._notify_stale_credentials(data)
            if settings.get('auto_relay'):
                result = self.service.auto_relay_if_needed()
                key = result.get('exhaustion_key')
                if result.get('accepted') and key != self.last_auto_relay:
                    self.last_auto_relay = key
                    if self.icon:
                        self.icon.notify('当前账号额度已用完，正在自动接力。', 'ChatGPTnx')
            if data.get('last_error'):
                self.icon.title = ('ChatGPTnx · 操作未完成 · ' + data['last_error']['message'])[:127]

    def _notify_stale_credentials(self, data):
        """Balloon once per account when a refresh was rejected as 401/403."""
        fresh = time.time() - (data.get('updated') or 0) <= 1800
        if not fresh:
            return
        for account in data['accounts']:
            code = account.get('error_code')
            if code not in (401, 403):
                continue
            who = account.get('alias') or account['email'].split('@')[0]
            note_key = ('credential', account['email'], code)
            if note_key in self.noticed:
                continue
            self.noticed.add(note_key)
            self.icon.notify(f'账号 {who} 的登录凭据已失效，请重新登录后刷新。', 'ChatGPTnx')
            self.service.log.info('credential_stale_notified account_index=%d', data['accounts'].index(account))

    def quit(self, *args):
        if self.service.operation or self.service.state.get('adding'):
            self.icon.notify('请先完成当前操作，或取消添加以恢复原账号。', 'ChatGPTnx')
            return
        self.service.log.info('shutdown_requested source=tray')
        self.service.stop.set()
        self.hotkeys.close()
        self.icon.stop()
        self.closing = True
        def close_window():
            form = self._form()
            if form:
                form.Close()
        self._dispatch_ui(close_window)

    def on_closing(self):
        if self.closing:
            return True
        self.hide()
        return False

    def run(self):
        import webview
        settings = self.service.state.get('settings')
        panel = (self.service.paths.resources / 'panel.html').read_text(encoding='utf-8')
        size = self.config['sizes']['home']
        dark = settings.get('appearance', 'system') == 'dark' or (
            settings.get('appearance', 'system') == 'system' and system_prefers_dark())
        background = '#1c1c1c' if dark else self.config['background']
        # HTML injection instead of serving the app folder; snapshots are never
        # exposed through a local file server.
        self.window = webview.create_window('ChatGPTnx', html=panel, js_api=Bridge(self.service, self),
                                            width=size[0], height=size[1], min_size=(300, 96),
                                            frameless=True, easy_drag=False, shadow=False,
                                            hidden=True, resizable=False,
                                            on_top=True,
                                            background_color=background)
        self.window.events.closing += self.on_closing
        if os.environ.get('CHATGPTNX_SHOW'):
            self.window.events.loaded += self.show
        # No events.shown hook: its Python callback needs the GIL on the UI
        # thread during Show(), which deadlocks with the tray thread's
        # cross-thread Invoke. First-show styling is handled by show() itself
        # plus the foreground-event repair in watch_focus().
        from .trayicon import TrayIcon
        self.icon = TrayIcon(str(self.service.paths.resources / 'nx.ico'), 'ChatGPTnx',
                             self.toggle, self.tray_menu)
        self.icon.run_detached()
        self.service.start_poll()
        # Style the panel the instant its HWND exists (ready() is too early).
        threading.Thread(target=self._style_at_birth, daemon=True).start()
        def ready():
            self.ready.set()
            self._remove_from_taskbar()
            self._apply_native_shape()
            threading.Thread(target=promote_tray_icon, daemon=True).start()
            self.layout()
            threading.Thread(target=self.update, daemon=True).start()
            threading.Thread(target=self.watch_focus, daemon=True).start()
            self.changed.set()
        try:
            webview.start(ready, gui='edgechromium', debug=False, private_mode=True)
        finally:
            self.service.log.info('desktop_loop_ended closing=%s', bool(self.closing))
