"""Read-only native corner diagnostic for a visible ChatGPTnx panel.

Checks the owned alpha edges and window region (legacy region on Windows 10). A pass does
not prove the actual antialiasing, backdrop pixels, or absence of shadows.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
import json
import os
import sys


def inspect_panel() -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext.restype = wt.BOOL
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # Per-monitor V2
    user.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user.FindWindowW.restype = wt.HWND
    user.IsWindowVisible.argtypes = [wt.HWND]
    user.IsWindowVisible.restype = wt.BOOL
    user.GetWindowRgn.argtypes = [wt.HWND, wt.HRGN]
    user.GetWindowRgn.restype = ctypes.c_int
    user.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user.GetWindowRect.restype = wt.BOOL
    user.GetDpiForWindow.argtypes = [wt.HWND]
    user.GetDpiForWindow.restype = wt.UINT
    gdi.CreateRectRgn.argtypes = [ctypes.c_int] * 4
    gdi.CreateRectRgn.restype = wt.HRGN
    gdi.PtInRegion.argtypes = [wt.HRGN, ctypes.c_int, ctypes.c_int]
    gdi.PtInRegion.restype = wt.BOOL
    gdi.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi.DeleteObject.restype = wt.BOOL

    hwnd = user.FindWindowW(None, 'ChatGPTnx')
    if not hwnd or not user.IsWindowVisible(hwnd):
        raise RuntimeError('Open the ChatGPTnx panel first')
    rect = wt.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError('GetWindowRect failed')
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError('Window has no visible area')

    region = gdi.CreateRectRgn(0, 0, 0, 0)
    if not region:
        raise RuntimeError('Cannot allocate query region')
    try:
        region_kind = user.GetWindowRgn(hwnd, region)
        build = sys.getwindowsversion().build
        details = {'mode': 'antialiased-region' if build >= 22621 else 'region',
                   'physical_size': [width, height],
                   'dpi': int(user.GetDpiForWindow(hwnd)),
                   'visual_acceptance': 'NOT_TESTED'}
        if build >= 22621:
            dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
            dwm.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD,
                                                   ctypes.c_void_p, wt.DWORD]
            dwm.DwmGetWindowAttribute.restype = ctypes.c_long
            values = {}
            # BORDER_COLOR (34) is set-only on this Windows build.
            for attr in (33, 38):
                value = ctypes.c_uint()
                result = dwm.DwmGetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
                if result:
                    raise RuntimeError(f'DwmGetWindowAttribute({attr}) failed')
                values[attr] = value.value
            details['dwm_attributes'] = values
            user.GetWindow.argtypes = [wt.HWND, wt.UINT]
            user.GetWindow.restype = wt.HWND
            user.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
            user.GetWindowTextW.restype = ctypes.c_int
            user.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
            user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
            edges = []
            order = []
            panel_topmost = bool(user.GetWindowLongPtrW(hwnd, -20) & 8)
            def collect(candidate, _):
                if candidate == hwnd:
                    order.append('panel')
                if user.GetWindow(candidate, 4) != hwnd:
                    return True
                title = ctypes.create_unicode_buffer(128)
                user.GetWindowTextW(candidate, title, len(title))
                if title.value == 'ChatGPTnx Corner Edge':
                    order.append('edge')
                    style = user.GetWindowLongPtrW(candidate, -20)
                    edges.append(bool(user.IsWindowVisible(candidate))
                                 and style & 0x080800A0 == 0x080800A0
                                 and not style & 0x00040000
                                 and bool(style & 8) == panel_topmost)
                return True
            callback = callback_type(collect)
            user.EnumWindows.argtypes = [callback_type, wt.LPARAM]
            user.EnumWindows(callback, 0)
            points = ((0,0),(width-1,0),(0,height-1),(width-1,height-1))
            outside = region_kind != 0 and all(not gdi.PtInRegion(region,*p) for p in points)
            details['alpha_edges'] = len(edges)
            details['edges_visible_nonactivating_input_transparent'] = all(edges) and len(edges) == 4
            details['all_edges_above_panel'] = order == ['edge']*4+['panel']
            details['native_corner_check'] = (values == {33:1,38:1} and outside
                                               and all(edges) and len(edges)==4
                                               and details['all_edges_above_panel'])
        else:
            if region_kind == 0:
                raise RuntimeError('No queryable window region')
            points = ((0, 0), (width - 1, 0), (0, height - 1),
                      (width - 1, height - 1))
            outside = [not bool(gdi.PtInRegion(region, *point)) for point in points]
            center = bool(gdi.PtInRegion(region, width // 2, height // 2))
            details['corners_outside_region'] = outside
            details['center_inside_region'] = center
            details['native_corner_check'] = all(outside) and center
        return details
    finally:
        gdi.DeleteObject(region)


if __name__ == '__main__':
    try:
        result = inspect_panel()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result['native_corner_check'] else 1)
    except (RuntimeError, OSError) as error:
        print(json.dumps({'error': str(error), 'native_corner_check': False},
                         ensure_ascii=False))
        sys.exit(2)
