"""Win10 API/dependency failure paths, without changing the host environment."""
import ctypes
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nx import win_compat


class DpiTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace()
        self.gdi = SimpleNamespace()
        self.dlls = SimpleNamespace(user32=self.user, gdi32=self.gdi)
        self.addCleanup(patch.stopall)
        patch.object(ctypes, 'windll', self.dlls, create=True).start()

    def test_older_win10_retains_monitor_dpi_without_get_dpi_for_window(self):
        self.user.MonitorFromWindow = Mock(return_value=0x123456789)
        def dpi(monitor, kind, x, y):
            self.assertEqual(monitor, 0x123456789)
            x._obj.value = y._obj.value = 144
            return 0
        self.dlls.shcore = SimpleNamespace(GetDpiForMonitor=Mock(side_effect=dpi))
        self.assertEqual(win_compat.window_dpi(0x234567890), 144)
        self.assertIs(self.user.MonitorFromWindow.restype, ctypes.wintypes.HMONITOR)

    def test_device_dpi_fallback_releases_its_dc(self):
        self.user.GetDC = Mock(return_value=0x123456789)
        self.user.ReleaseDC = Mock()
        self.gdi.GetDeviceCaps = Mock(return_value=120)
        self.assertEqual(win_compat.window_dpi(42), 120)
        self.user.ReleaseDC.assert_called_once_with(42, 0x123456789)
        self.assertIs(self.user.GetDC.restype, ctypes.wintypes.HDC)

    def test_failed_device_dpi_read_still_releases_its_dc(self):
        self.user.GetDC = Mock(return_value=123)
        self.user.ReleaseDC = Mock()
        self.gdi.GetDeviceCaps = Mock(side_effect=OSError())
        self.assertEqual(win_compat.window_dpi(42), 96)
        self.user.ReleaseDC.assert_called_once_with(42, 123)

    def test_missing_apis_preserve_a_usable_default(self):
        self.assertEqual(win_compat.window_dpi(42), 96)

    def test_layout_and_clipping_both_use_fallback_dpi_on_win10(self):
        from nx import desktop
        host = desktop.Desktop(SimpleNamespace(log=Mock(), listeners=[]))
        self.user.GetDC = Mock(return_value=123)
        self.user.ReleaseDC = Mock()
        self.gdi.GetDeviceCaps = Mock(return_value=144)
        self.user.GetWindowRect = Mock(side_effect=lambda hwnd, out: self.rect(out))
        self.user.SetWindowRgn = Mock(return_value=1)
        self.gdi.CreateRoundRectRgn = Mock(return_value=987)
        self.gdi.DeleteObject = Mock()
        with patch.object(desktop, '_find_hwnd', return_value=42), \
             patch.object(desktop.sys, 'getwindowsversion', return_value=SimpleNamespace(build=10240), create=True):
            self.assertEqual(host._physical_size(42), (490, 687))
            self.assertTrue(host._apply_native_shape())
        self.gdi.CreateRoundRectRgn.assert_called_once_with(0, 0, 491, 688, 48, 48)

    @staticmethod
    def rect(out):
        r = out._obj
        r.left = r.top = 0
        r.right, r.bottom = 490, 687
        return True


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.entries = {}
        self.registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
                                        KEY_WOW64_64KEY=256, KEY_WOW64_32KEY=512, KEY_READ=1)
        # Context-manager special methods must be defined on the type.
        class Key:
            def __init__(self, key): self.key = key
            def __enter__(self): return self.key
            def __exit__(self, *args): pass
        def open_key(hive, path, reserved, access):
            key = (hive, path, access & (256 | 512))
            if key not in self.entries: raise FileNotFoundError()
            return Key(key)
        self.registry.OpenKey = Mock(side_effect=open_key)
        self.registry.QueryValueEx = Mock(side_effect=lambda key, name: (self.entries[key], 1))
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {'winreg': self.registry}).start()
        self.entries[(1, win_compat.NET_KEY, 256)] = 528372

    def test_win10_missing_webview2_gets_actionable_message(self):
        self.assertEqual(win_compat.desktop_runtime_issue(), win_compat.WEBVIEW_HELP)

    def test_per_user_and_machine_installs_in_both_registry_views(self):
        for hive in (1, 2):
            for view in (256, 512):
                with self.subTest(hive=hive, view=view):
                    self.entries[(hive, win_compat.WEBVIEW_KEY, view)] = '130.0.2849.80'
                    self.assertIsNone(win_compat.desktop_runtime_issue())
                    del self.entries[(hive, win_compat.WEBVIEW_KEY, view)]

    def test_missing_or_old_dotnet_is_reported_before_webview(self):
        for release in (None, 393295, '528372'):
            self.entries[(1, win_compat.NET_KEY, 256)] = release
            self.assertEqual(win_compat.desktop_runtime_issue(), win_compat.NET_HELP)

    def test_uninstalled_malformed_or_old_runtime_registration_is_rejected(self):
        for value in ('0.0.0.0', '', 'invalid', '85.0.999.0', None):
            self.entries[(2, win_compat.WEBVIEW_KEY, 256)] = value
            self.assertEqual(win_compat.desktop_runtime_issue(), win_compat.WEBVIEW_HELP)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows entry point')
    def test_missing_dependency_stops_before_credentials_and_service(self):
        import chatgptnx
        user, shell, kernel = Mock(), Mock(), Mock()
        with patch.object(ctypes, 'windll', SimpleNamespace(user32=user, shell32=shell)), \
             patch.object(ctypes, 'WinDLL', return_value=kernel), \
             patch.object(ctypes, 'get_last_error', return_value=0), \
             patch.object(sys, 'argv', ['ChatGPTnx']), \
             patch.object(chatgptnx, 'Paths') as paths, patch.object(chatgptnx, 'Service') as service, \
             patch('nx.credentials.protect_store') as protect:
            with self.assertRaises(SystemExit) as result:
                chatgptnx.main()
        self.assertEqual(result.exception.code, 1)
        user.MessageBoxW.assert_called_once_with(None, win_compat.WEBVIEW_HELP,
                                                'ChatGPTnx · 运行环境', 0x10)
        paths.assert_not_called(); service.assert_not_called(); protect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
