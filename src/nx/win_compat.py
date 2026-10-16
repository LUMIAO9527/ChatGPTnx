"""Read-only Windows runtime checks and DPI fallbacks for older Windows 10."""
import ctypes
from ctypes import wintypes as wt
import re


NET_KEY = r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full'
WEBVIEW_KEY = r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
NET_HELP = ('需要 Microsoft .NET Framework 4.6.2 或更高版本。\n'
            '请安装后重新启动 ChatGPTnx。\n'
            '官方下载：https://dotnet.microsoft.com/download/dotnet-framework')
WEBVIEW_HELP = ('需要 Microsoft Edge WebView2 Runtime。\n'
                '请安装 Evergreen 独立安装程序（x64）后重新启动 ChatGPTnx。\n'
                '官方下载：https://developer.microsoft.com/microsoft-edge/webview2/')


def desktop_runtime_issue():
    """Do not let missing Win10 prerequisites silently select the IE engine."""
    import winreg

    def values(hives, path, name):
        for hive in hives:
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
                        yield winreg.QueryValueEx(key, name)[0]
                except OSError:
                    continue

    if not any(type(value) is int and value >= 394802
               for value in values((winreg.HKEY_LOCAL_MACHINE,), NET_KEY, 'Release')):
        return NET_HELP
    for value in values((winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE), WEBVIEW_KEY, 'pv'):
        if (isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+\.\d+', value)
                and tuple(map(int, value.split('.'))) >= (86, 0, 622, 0)):
            return None
    return WEBVIEW_HELP


def window_dpi(hwnd):
    user = ctypes.windll.user32
    try:
        get_dpi = user.GetDpiForWindow
        get_dpi.argtypes = [wt.HWND]
        get_dpi.restype = wt.UINT
        return int(get_dpi(hwnd) or 96)
    except (AttributeError, OSError):
        # GetDpiForWindow was introduced in Windows 10 1607.
        pass
    try:
        monitor = user.MonitorFromWindow
        monitor.argtypes = [wt.HWND, wt.DWORD]
        monitor.restype = wt.HMONITOR
        get_dpi = ctypes.windll.shcore.GetDpiForMonitor
        get_dpi.argtypes = [wt.HMONITOR, ctypes.c_int, ctypes.POINTER(wt.UINT), ctypes.POINTER(wt.UINT)]
        get_dpi.restype = ctypes.c_long
        x, y = wt.UINT(), wt.UINT()
        if get_dpi(monitor(hwnd, 2), 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
            return x.value
    except (AttributeError, OSError):
        pass
    dc = None
    try:
        user.GetDC.argtypes = [wt.HWND]
        user.GetDC.restype = wt.HDC
        user.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        user.ReleaseDC.restype = ctypes.c_int
        caps = ctypes.windll.gdi32.GetDeviceCaps
        caps.argtypes = [wt.HDC, ctypes.c_int]
        caps.restype = ctypes.c_int
        dc = user.GetDC(hwnd)
        if dc:
            return int(caps(dc, 88) or 96)  # LOGPIXELSX
    except (AttributeError, OSError):
        pass
    finally:
        if dc:
            user.ReleaseDC(hwnd, dc)
    return 96
