"""Optional desktop blur for WebView2, with an opaque failure path on Win10/11.

The native WebView background is either transparent or opaque (never partial
alpha). Tint belongs to the HTML. A WinRT host-backdrop brush has its own
16px geometric clip; whole-window DWM blur can escape an HWND region.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as wt
import sys
from pathlib import Path
from .design import PANEL_CONFIG
from .win_compat import window_dpi


class Margins(ctypes.Structure):
    _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                ('top', ctypes.c_int), ('bottom', ctypes.c_int)]


class AccentPolicy(ctypes.Structure):
    _fields_ = [('state', ctypes.c_int), ('flags', ctypes.c_int),
                ('color', wt.DWORD), ('animation', ctypes.c_int)]


class CompositionAttribute(ctypes.Structure):
    _fields_ = [('attribute', ctypes.c_int), ('data', ctypes.c_void_p),
                ('size', ctypes.c_size_t)]


class HighContrast(ctypes.Structure):
    _fields_ = [('size', wt.UINT), ('flags', wt.DWORD), ('scheme', wt.LPWSTR)]


class PowerStatus(ctypes.Structure):
    _fields_ = [('ac', wt.BYTE), ('battery', wt.BYTE), ('percent', wt.BYTE),
                ('saving', wt.BYTE), ('remaining', wt.DWORD), ('full', wt.DWORD)]


def edge_color(dark):
    """Premultiplied corner coverage adds the same subtle lip as the glass skin."""
    return (226,237,255,59) if dark else (255,255,255,196)


def transparency_allowed():
    """Read Windows policy; never change registry or power/accessibility settings."""
    try:
        user = ctypes.windll.user32
        high = HighContrast(ctypes.sizeof(HighContrast), 0, None)
        user.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
        user.SystemParametersInfoW.restype = wt.BOOL
        if not user.SystemParametersInfoW(0x42, high.size, ctypes.byref(high), 0) or high.flags & 1:
            return False
        dwm = ctypes.windll.dwmapi
        dwm.DwmIsCompositionEnabled.argtypes = [ctypes.POINTER(wt.BOOL)]
        dwm.DwmIsCompositionEnabled.restype = ctypes.c_long
        enabled = wt.BOOL()
        if dwm.DwmIsCompositionEnabled(ctypes.byref(enabled)) or not enabled.value:
            return False
        power = PowerStatus()
        kernel = ctypes.windll.kernel32
        kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(PowerStatus)]
        kernel.GetSystemPowerStatus.restype = wt.BOOL
        if kernel.GetSystemPowerStatus(ctypes.byref(power)) and power.saving:
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                if winreg.QueryValueEx(key, 'EnableTransparency')[0] == 0:
                    return False
        except FileNotFoundError:
            pass
        return True
    except (AttributeError, OSError, ImportError, TypeError, ValueError):
        return False


class WindowMaterial:
    """Apply on the owning WinForms UI thread, before making a panel visible."""
    def __init__(self, log=None, resources=None):
        self.log = log
        self.mode = 'solid'
        self._key = None
        self._bound = None
        self._callbacks = None
        self.resources = Path(resources or (sys._MEIPASS if getattr(sys,'frozen',False)
                               else Path(__file__).resolve().parents[2]/'_wip/build/resources'))
        self._backdrop = None
        self._clip_owner = None
        self.outline = None
        self.last_error = None

    def _dwm(self, hwnd, attribute, value):
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        set_attribute.restype = ctypes.c_long
        setting = ctypes.c_int(value)
        return set_attribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting)) == 0

    def _extend(self, hwnd, enabled):
        extend = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
        extend.argtypes = [wt.HWND, ctypes.POINTER(Margins)]
        extend.restype = ctypes.c_long
        margins = Margins(*([-1] * 4 if enabled else [0] * 4))
        return extend(hwnd, ctypes.byref(margins)) == 0

    def _accent(self, hwnd, state):
        # State 5 registers host-backdrop sampling; it does not paint a rectangle.
        apply = ctypes.windll.user32.SetWindowCompositionAttribute
        apply.argtypes = [wt.HWND, ctypes.POINTER(CompositionAttribute)]
        apply.restype = wt.BOOL
        policy = AccentPolicy(state, 0, 0, 0)
        data = CompositionAttribute(19, ctypes.addressof(policy), ctypes.sizeof(policy))
        return bool(apply(hwnd, ctypes.byref(data)))

    def _geometry(self, hwnd):
        user=ctypes.windll.user32
        user.GetClientRect.argtypes=[wt.HWND,ctypes.POINTER(wt.RECT)]
        user.GetClientRect.restype=wt.BOOL
        rect=wt.RECT()
        if not user.GetClientRect(hwnd,ctypes.byref(rect)) or rect.right<=0 or rect.bottom<=0:
            raise OSError('Cannot measure the material surface')
        return rect.right,rect.bottom,max(1,round(PANEL_CONFIG['radius']*window_dpi(hwnd)/96))

    def _create_clip(self, hwnd):
        import clr
        clr.AddReference(str(self.resources/'ChatGPTnx.Backdrop.dll'))
        from ChatGPTnx.Native import ClippedBackdrop
        from System import IntPtr
        return ClippedBackdrop(IntPtr(hwnd))

    def _register_host(self, hwnd, build):
        try:
            self._accent(hwnd,0)
        except (AttributeError,OSError):
            pass
        if build>=22000:
            self._dwm(hwnd,33,1)
            self._dwm(hwnd,34,-2)
            if build>=22621:
                self._dwm(hwnd,38,1)
            return self._dwm(hwnd,17,1)
        return self._accent(hwnd,5)

    def close(self):
        try:
            if self._backdrop is not None:
                self._backdrop.Dispose()
        finally:
            self._backdrop=None
            self._clip_owner=None
            self.outline=None
            self._key=None

    @staticmethod
    def _surface(form, transparent, dark):
        from System.Drawing import Color
        webview = form.browser.webview
        color = Color.FromArgb(255, 29, 29, 29) if dark else Color.FromArgb(255, 255, 255, 255)
        form.BackColor = Color.Black if transparent else color
        webview.DefaultBackgroundColor = Color.Transparent if transparent else color
        form.Invalidate(True)

    def _restore(self, form, hwnd, dark, build):
        # Cover the surface first, even if a native disable API is unavailable.
        self._surface(form, False, dark)
        if self._backdrop is not None:
            self._backdrop.SetVisible(False)
        self.outline=None
        for action in (lambda: self._accent(hwnd, 0),
                       lambda: self._dwm(hwnd,17,0) if build>=22000 else None,
                       lambda: self._dwm(hwnd, 38, 1) if build >= 22621 else None,
                       lambda: self._extend(hwnd, False)):
            try:
                action()
            except (AttributeError, OSError):
                pass
        self.mode = 'solid'

    def apply(self, form, hwnd, *, dark=False, requested=True, backend='auto'):
        build = getattr(getattr(sys, 'getwindowsversion', lambda: None)(), 'build', 0)
        allowed = requested and backend != 'solid' and build >= 17134 and transparency_allowed()
        try:
            geometry=self._geometry(hwnd) if allowed else None
        except (AttributeError,OSError):
            allowed=False
            geometry=None
        key = (hwnd, build, dark, bool(allowed), backend, geometry)
        if key == self._key:
            return self.mode
        self._key = None
        try:
            self.last_error = None
            if not allowed:
                self._restore(form, hwnd, dark, build)
                self._key = key
                return self.mode
            self._surface(form, True, dark)
            if not self._extend(hwnd, True):
                raise OSError('Frame extension failed')
            if not self._register_host(hwnd,build):
                raise OSError('Host backdrop is unavailable')
            if self._clip_owner!=hwnd:
                self.close()
                self._backdrop=self._create_clip(hwnd)
                self._clip_owner=hwnd
            self._backdrop.Resize(*geometry)
            self._backdrop.SetVisible(True)
            self.outline={'width':geometry[0],'height':geometry[1],'radius':geometry[2]}
            self.mode='blur'
            self._key=key
            return self.mode
        except Exception as error:
            self.last_error = type(error).__name__ + ': ' + str(error)[:400]
            if self.log:
                self.log.warning('window_material_fallback type=%s', type(error).__name__)
            try:
                self._restore(form, hwnd, dark, build)
            except Exception:
                self.mode = 'solid'
            return self.mode

    def bind_policy_changes(self, form, refresh):
        if self._bound is form:
            return
        from Microsoft.Win32 import SystemEvents
        def changed(*_):
            self._key = None
            refresh()
        def closed(*_):
            SystemEvents.UserPreferenceChanged -= changed
            SystemEvents.PowerModeChanged -= changed
            self._bound = None
            self._callbacks = None
            self.close()
        SystemEvents.UserPreferenceChanged += changed
        SystemEvents.PowerModeChanged += changed
        form.HandleDestroyed += closed
        self._bound = form
        self._callbacks = (changed, closed)
