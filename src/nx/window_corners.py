"""DPI-scaled, antialiased corners around an opaque WebView2 surface.

The HWND region contains only fully covered pixels. Four tiny owned layered
windows supply the partial edge pixels against the real desktop. They cannot
activate or receive input; their owner controls visibility and lifetime.
All methods must run on the window's UI thread.
"""
import ctypes
from ctypes import wintypes as wt
from functools import lru_cache
import struct


class Blend(ctypes.Structure):
    _fields_ = [('op', wt.BYTE), ('flags', wt.BYTE), ('opacity', wt.BYTE), ('format', wt.BYTE)]


@lru_cache(maxsize=8)
def coverage(radius):
    samples = 8
    rows = []
    for y in range(radius):
        row = []
        for x in range(radius):
            inside = sum((radius - x - (sx + .5) / samples) ** 2
                         + (radius - y - (sy + .5) / samples) ** 2 <= radius ** 2
                         for sy in range(samples) for sx in range(samples))
            row.append(round(inside * 255 / (samples * samples)))
        rows.append(tuple(row))
    return tuple(rows)


class WindowCorners:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateWindowExW': ([wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND,
                                wt.HMENU, wt.HINSTANCE, ctypes.c_void_p], wt.HWND),
            'DestroyWindow': ([wt.HWND], wt.BOOL),
            'IsWindow': ([wt.HWND], wt.BOOL),
            'IsWindowVisible': ([wt.HWND], wt.BOOL),
            'GetWindow': ([wt.HWND, wt.UINT], wt.HWND),
            'GetWindowLongPtrW': ([wt.HWND, ctypes.c_int], ctypes.c_ssize_t),
            'GetWindowRect': ([wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
            'SetWindowRgn': ([wt.HWND, wt.HRGN, wt.BOOL], ctypes.c_int),
            'ShowWindow': ([wt.HWND, ctypes.c_int], wt.BOOL),
            'SetWindowPos': ([wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wt.UINT], wt.BOOL),
            'UpdateLayeredWindow': ([wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
                                    ctypes.POINTER(wt.SIZE), wt.HDC, ctypes.POINTER(wt.POINT),
                                    wt.DWORD, ctypes.POINTER(Blend), wt.DWORD], wt.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user, name); fn.argtypes = args; fn.restype = result
        signatures = {
            'ExtCreateRegion': ([ctypes.c_void_p, wt.DWORD, ctypes.c_void_p], wt.HRGN),
            'CreateCompatibleDC': ([wt.HDC], wt.HDC),
            'DeleteDC': ([wt.HDC], wt.BOOL),
            'CreateDIBSection': ([wt.HDC, ctypes.c_void_p, wt.UINT,
                                  ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD], wt.HBITMAP),
            'SelectObject': ([wt.HDC, wt.HGDIOBJ], wt.HGDIOBJ),
            'DeleteObject': ([wt.HGDIOBJ], wt.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.gdi, name); fn.argtypes = args; fn.restype = result
        self.kernel.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = wt.HMODULE
        self.owner = None
        self.windows = []
        self.key = None

    def close(self):
        for window in self.windows:
            if self.user.IsWindow(window):
                self.user.DestroyWindow(window)
        self.windows = []
        self.owner = None
        self.key = None

    def apply(self, owner, radius, rgb):
        rect = wt.RECT()
        if not self.user.GetWindowRect(owner, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        width, height = rect.right - rect.left, rect.bottom - rect.top
        radius = min(max(1, radius), width // 2, height // 2)
        key = (owner, width, height, radius, tuple(rgb))
        if self.owner != owner:
            self.close()
            self.owner = owner
            for _ in range(4):
                window = self.user.CreateWindowExW(
                    0x00080000 | 0x00000020 | 0x08000000 | 0x00000080,
                    'STATIC', 'ChatGPTnx Corner Edge', 0x80000000,
                    rect.left, rect.top, radius, radius, owner, None,
                    self.kernel.GetModuleHandleW(None), None)
                if not window:
                    self.close()
                    raise ctypes.WinError(ctypes.get_last_error())
                self.windows.append(window)
        if self.key != key:
            matrix = coverage(radius)
            insets = [next((x for x, alpha in enumerate(row) if alpha == 255), radius)
                      for row in matrix]
            rectangles = [(0, radius, width, height - radius)]
            rectangles += [(inset, y, width - inset, y + 1) for y, inset in enumerate(insets)]
            rectangles += [(inset, height - y - 1, width - inset, height - y)
                           for y, inset in enumerate(insets)]
            rectangles.sort(key=lambda r: (r[1], r[0]))
            data = struct.pack('<8I', 32, 1, len(rectangles), len(rectangles) * 16,
                               0, 0, width, height)
            data += b''.join(struct.pack('<4i', *r) for r in rectangles)
            buffer = ctypes.create_string_buffer(data)
            region = self.gdi.ExtCreateRegion(None, len(data), buffer)
            if not region:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                for index, window in enumerate(self.windows):
                    self._paint(window, radius, rgb, matrix, index,
                                rect.left + (width - radius if index % 2 else 0),
                                rect.top + (height - radius if index // 2 else 0))
                if not self.user.SetWindowRgn(owner, region, True):
                    raise ctypes.WinError(ctypes.get_last_error())
                region = None
                self.key = key
            finally:
                if region:
                    self.gdi.DeleteObject(region)
        self.move()

    def _paint(self, window, radius, rgb, matrix, index, left, top):
        pixels = bytearray(radius * radius * 4)
        for y in range(radius):
            for x in range(radius):
                alpha = matrix[radius - y - 1 if index // 2 else y][radius - x - 1 if index % 2 else x]
                # Full pixels are owned by the opaque WebView. Only its omitted
                # partial pixels need compositing against the actual backdrop.
                if 0 < alpha < 255:
                    offset = (y * radius + x) * 4
                    pixels[offset:offset+4] = bytes((round(rgb[2] * alpha / 255),
                                                   round(rgb[1] * alpha / 255),
                                                   round(rgb[0] * alpha / 255), alpha))
        header = struct.pack('<IiiHHIIiiII', 40, radius, -radius, 1, 32, 0,
                             len(pixels), 0, 0, 0, 0)
        info = ctypes.create_string_buffer(header + b'\0' * 4)
        memory = ctypes.c_void_p()
        dc = self.gdi.CreateCompatibleDC(None)
        bitmap = self.gdi.CreateDIBSection(dc, info, 0, ctypes.byref(memory), None, 0)
        previous = None
        try:
            if not dc or not bitmap or not memory:
                raise ctypes.WinError(ctypes.get_last_error())
            previous = self.gdi.SelectObject(dc, bitmap)
            ctypes.memmove(memory, bytes(pixels), len(pixels))
            target, size, origin = wt.POINT(left, top), wt.SIZE(radius, radius), wt.POINT(0, 0)
            blend = Blend(0, 0, 255, 1)
            if not self.user.UpdateLayeredWindow(window, None, ctypes.byref(target),
                                                ctypes.byref(size), dc, ctypes.byref(origin),
                                                0, ctypes.byref(blend), 2):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if previous:
                self.gdi.SelectObject(dc, previous)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            if dc:
                self.gdi.DeleteDC(dc)

    def move(self, visible=None):
        if not self.owner or not self.windows:
            return
        rect = wt.RECT()
        if not self.user.GetWindowRect(self.owner, ctypes.byref(rect)):
            return
        radius = self.key[3] if self.key else 1
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if visible is None:
            visible = bool(self.user.IsWindowVisible(self.owner))
        topmost = bool(self.user.GetWindowLongPtrW(self.owner, -20) & 8)
        above = self.user.GetWindow(self.owner, 3)  # GW_HWNDPREV
        while above in self.windows:
            above = self.user.GetWindow(above, 3)
        if above and not topmost and self.user.GetWindowLongPtrW(above, -20) & 8:
            above = None  # First ordinary window, below the topmost band.
        for index, window in enumerate(self.windows):
            if bool(self.user.GetWindowLongPtrW(window, -20) & 8) != topmost:
                if not self.user.SetWindowPos(window, wt.HWND(-1 if topmost else -2),
                                             0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200):
                    raise ctypes.WinError(ctypes.get_last_error())
            if not self.user.SetWindowPos(window, above,
                                   rect.left + (width - radius if index % 2 else 0),
                                   rect.top + (height - radius if index // 2 else 0),
                                   0, 0, 0x0001 | 0x0010 | 0x0200):
                raise ctypes.WinError(ctypes.get_last_error())
            self.user.ShowWindow(window, 4 if visible else 0)
            above = window
