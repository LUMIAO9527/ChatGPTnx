"""Read-only HRGN diagnostic. Run on Windows with the nx panel visible.

This inspects the actual HWND; it does not launch, resize or restyle it.
A pass is NOT proof of DWM/WebView2 visual appearance or shadow absence.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
import json
import os
import sys


def inspect_panel() -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows is required; no native acceptance performed')
    user, gdi = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('gdi32', use_last_error=True)
    user.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user.FindWindowW.restype = wt.HWND
    user.IsWindowVisible.argtypes = [wt.HWND]
    user.IsWindowVisible.restype = wt.BOOL
    user.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user.GetWindowRect.restype = wt.BOOL
    user.GetWindowRgn.argtypes = [wt.HWND, wt.HRGN]
    user.GetWindowRgn.restype = ctypes.c_int
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
        # This region is owned by this diagnostic, not transferred to Windows.
        kind = user.GetWindowRgn(hwnd, region)
        if kind == 0:
            raise RuntimeError('No queryable window region (or query failed)')
        points = {'top_left': (0, 0), 'top_right': (width - 1, 0),
                  'bottom_left': (0, height - 1), 'bottom_right': (width - 1, height - 1)}
        outside = {key: not bool(gdi.PtInRegion(region, *point)) for key, point in points.items()}
        center = bool(gdi.PtInRegion(region, width // 2, height // 2))
        return {'native_region_check': all(outside.values()) and center,
                'physical_size': [width, height], 'dpi': int(user.GetDpiForWindow(hwnd)),
                'corners_outside_region': outside, 'center_inside_region': center,
                'visual_acceptance': 'NOT_TESTED; inspect light/dark backgrounds and shadows manually'}
    finally:
        gdi.DeleteObject(region)


if __name__ == '__main__':
    try:
        result = inspect_panel()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result['native_region_check'] else 1)
    except (RuntimeError, OSError) as error:
        print(json.dumps({'error': str(error), 'native_region_check': False}, ensure_ascii=False))
        sys.exit(2)
