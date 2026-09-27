"""Minimal native Win32 tray icon and intentionally small system menu."""
from __future__ import annotations
import ctypes
import struct
import threading
import time
from ctypes import wintypes as wt

WM_APP = 0x8000
WM_TRAYCALLBACK, WM_STOP = WM_APP + 1, WM_APP + 2
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SET_VERSION = 0x0, 0x1, 0x2, 0x4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
WM_LBUTTONUP, WM_LBUTTONCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
WM_DESTROY = 0x0002
WM_NULL = 0x0000
MF_STRING, MF_GRAYED, MF_CHECKED = 0x0000, 0x0001, 0x0008
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
CLASS_NAME = 'ChatGPTnxTrayWnd'


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [('cbSize', wt.UINT), ('hWnd', wt.HWND), ('uID', wt.UINT),
                ('uFlags', wt.UINT), ('uCallbackMessage', wt.UINT), ('hIcon', wt.HICON),
                ('szTip', wt.WCHAR * 128), ('dwState', wt.DWORD), ('dwStateMask', wt.DWORD),
                ('szInfo', wt.WCHAR * 256), ('uVersion', wt.UINT),
                ('szInfoTitle', wt.WCHAR * 64), ('dwInfoFlags', wt.DWORD),
                ('guidItem', ctypes.c_byte * 16), ('hBalloonIcon', wt.HICON)]


class GUID(ctypes.Structure):
    _fields_ = [('Data1', wt.DWORD), ('Data2', wt.WORD), ('Data3', wt.WORD),
                ('Data4', ctypes.c_byte * 8)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('hWnd', wt.HWND), ('uID', wt.UINT),
                ('guidItem', GUID)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [('style', wt.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wt.HINSTANCE), ('hIcon', wt.HICON),
                ('hCursor', ctypes.c_void_p), ('hbrBackground', wt.HBRUSH),
                ('lpszMenuName', wt.LPCWSTR), ('lpszClassName', wt.LPCWSTR)]


def _load_hicon(path, target):
    data = open(path, 'rb').read()
    _, _, count = struct.unpack_from('<HHH', data, 0)
    best = None
    for index in range(count):
        width, _, _, _, _, _, size, offset = struct.unpack_from('<BBBBHHII', data, 6 + index * 16)
        width = 256 if width == 0 else width
        if best is None or abs(width - target) < abs(best[0] - target):
            best = (width, offset, size)
    if not best:
        return None
    _, offset, size = best
    user32 = ctypes.windll.user32
    user32.CreateIconFromResourceEx.restype = ctypes.c_void_p
    user32.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wt.DWORD, wt.BOOL, wt.DWORD,
                                                ctypes.c_int, ctypes.c_int, wt.UINT]
    return user32.CreateIconFromResourceEx(ctypes.c_char_p(data[offset:offset + size]), size,
                                           True, 0x00030000, target, target, 0)


class TrayIcon:
    def __init__(self, icon_path, title, default_action, menu_provider):
        self._user32 = ctypes.windll.user32
        self._shell = ctypes.windll.shell32
        self._icon_path, self._tip = icon_path, title
        self._default_action, self._menu_provider = default_action, menu_provider
        self._hwnd = self._hicon = None
        self._uID = 1
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._wndproc_keepalive = None
        self._thread = threading.Thread(target=self._loop, daemon=True, name='nx-tray')

    @property
    def title(self):
        return self._tip

    @title.setter
    def title(self, value):
        self._tip = str(value)[:127]
        data = self._base_nid()
        if data:
            data.uFlags = NIF_TIP | NIF_SHOWTIP
            with self._lock:
                self._shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def notify(self, message, title='ChatGPTnx'):
        data = self._base_nid()
        if not data:
            return
        data.uFlags = NIF_INFO | NIF_SHOWTIP
        data.szInfoTitle = str(title)[:63]
        data.szInfo = str(message)[:255]
        with self._lock:
            self._shell.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def run_detached(self):
        self._thread.start()
        self._ready.wait(5)

    def stop(self):
        if self._hwnd and self._thread.is_alive():
            self._user32.PostMessageW(self._hwnd, WM_STOP, 0, 0)
            if threading.current_thread() is not self._thread:
                self._thread.join(1.5)

    def rect(self):
        if not self._hwnd:
            return None
        identifier = NOTIFYICONIDENTIFIER()
        identifier.cbSize, identifier.hWnd, identifier.uID = ctypes.sizeof(identifier), self._hwnd, self._uID
        rect = wt.RECT()
        try:
            fn = self._shell.Shell_NotifyIconGetRect
            fn.restype = ctypes.c_long
            fn.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wt.RECT)]
            if fn(ctypes.byref(identifier), ctypes.byref(rect)) == 0:
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
        return None

    def _base_nid(self):
        if not self._hwnd:
            return None
        data = NOTIFYICONDATAW()
        data.cbSize, data.hWnd, data.uID = ctypes.sizeof(data), self._hwnd, self._uID
        data.hIcon, data.szTip = self._hicon, self._tip
        return data

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == WM_TRAYCALLBACK:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONCLK):
                self._default_action()
            elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu(hwnd)
            return 0
        if message == WM_STOP:
            self._user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            data = self._base_nid()
            if data:
                self._shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            if self._hicon:
                self._user32.DestroyIcon(self._hicon)
                self._hicon = None
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self, hwnd):
        """Use the Windows menu surface for three tray-level commands only."""
        items = list(self._menu_provider() or [])
        menu = self._user32.CreatePopupMenu()
        if not menu:
            return
        actions = {}
        try:
            for command, item in enumerate(items, 1):
                flags = MF_STRING
                if item.get('enabled', True) is False:
                    flags |= MF_GRAYED
                if item.get('checked'):
                    flags |= MF_CHECKED
                self._user32.AppendMenuW(menu, flags, command, str(item.get('label', '')))
                actions[command] = item.get('action')
            point = wt.POINT()
            self._user32.GetCursorPos(ctypes.byref(point))
            self._user32.SetForegroundWindow(hwnd)
            command = self._user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, 0, hwnd, None)
            self._user32.PostMessageW(hwnd, WM_NULL, 0, 0)
            action = actions.get(command)
            if action:
                action()
        finally:
            self._user32.DestroyMenu(menu)

    def _loop(self):
        user32, shell, kernel32 = self._user32, self._shell, ctypes.windll.kernel32
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
        user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.CreatePopupMenu.restype = wt.HMENU
        user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
        user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wt.HWND, ctypes.c_void_p]
        user32.DestroyMenu.argtypes = [wt.HMENU]
        wc = WNDCLASSW()
        wc.lpfnWndProc = WNDPROC(self._wndproc)
        self._wndproc_keepalive = wc.lpfnWndProc
        wc.lpszClassName = CLASS_NAME
        wc.hInstance = kernel32.GetModuleHandleW(None)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._ready.set()
            return
        try:
            dpi = user32.GetDpiForSystem() or 96
        except Exception:
            dpi = 96
        self._hicon = _load_hicon(self._icon_path, max(16, round(16 * dpi / 96)))
        self._hwnd = user32.CreateWindowExW(0, CLASS_NAME, 'ChatGPTnx Tray', 0x80000000,
                                            0, 0, 0, 0, None, None, wc.hInstance, None)
        if not self._hwnd:
            self._ready.set()
            return
        data = self._base_nid()
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYCALLBACK
        if not shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            time.sleep(2)
            if not shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
                self._ready.set()
                return
        version = NOTIFYICONDATAW()
        version.cbSize, version.hWnd, version.uID, version.uVersion = ctypes.sizeof(version), self._hwnd, self._uID, 4
        shell.Shell_NotifyIconW(NIM_SET_VERSION, ctypes.byref(version))
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
