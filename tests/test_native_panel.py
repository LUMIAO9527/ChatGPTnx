"""Panel regression tests with fake Win32 APIs, not Windows visual acceptance.

Run from a source checkout: python -m unittest discover -s tests -p test_native_panel.py -v
No WebView runtime, real accounts, registry writes or interactive desktop required.
"""
from pathlib import Path
import ctypes
import inspect
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nx import desktop
from nx.design import PANEL_CONFIG
from nx.version import APP_VERSION

HWND = 0x123456789
HRGN = 0x234567890
HMONITOR = 0x345678901


class Function:
    """Callable whose ctypes declaration and arguments can be inspected."""
    def __init__(self, result=1, effect=None):
        self.result, self.effect = result, effect
        self.argtypes = None
        self.restype = None
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.effect(*args) if self.effect else self.result


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.size = (372, 520)
        self.dpi = 96
        self.rect_ok = True

        def rect(_hwnd, out):
            r = out._obj
            r.left, r.top = 20, 30
            r.right, r.bottom = 20 + self.size[0], 30 + self.size[1]
            return self.rect_ok

        def monitor(_handle, out):
            i = out._obj
            i.rcMonitor.left, i.rcMonitor.top = 0, 0
            i.rcMonitor.right, i.rcMonitor.bottom = 1920, 1080
            i.rcWork.left, i.rcWork.top = 0, 0
            i.rcWork.right, i.rcWork.bottom = 1920, 1040
            return True

        self.user = SimpleNamespace(
            FindWindowW=Function(HWND), GetWindowRect=Function(effect=rect),
            GetDpiForWindow=Function(effect=lambda _: self.dpi),
            SetWindowRgn=Function(), MonitorFromRect=Function(HMONITOR),
            MonitorFromPoint=Function(HMONITOR), GetMonitorInfoW=Function(effect=monitor),
            GetCursorPos=Function(), SetWindowPos=Function(), SetForegroundWindow=Function(),
        )
        self.gdi = SimpleNamespace(CreateRoundRectRgn=Function(HRGN), DeleteObject=Function())
        self.dwm = SimpleNamespace(DwmSetWindowAttribute=Function(0))
        self.dlls = SimpleNamespace(user32=self.user, gdi32=self.gdi, dwmapi=self.dwm)
        self.addCleanup(patch.stopall)
        patch.object(ctypes, 'windll', self.dlls, create=True).start()
        self.find = patch.object(desktop, '_find_hwnd', return_value=HWND).start()
        self.host = desktop.Desktop(SimpleNamespace(log=Mock(), listeners=[], operation=None))
        self.host.window = SimpleNamespace(uid='synthetic')
        self.form = Mock()
        self.host._form = Mock(return_value=self.form)
        self.host._post_script = Mock()
        self.host._set_panel_topmost = Mock(return_value=True)
        self.host._dispatch_ui = Mock(side_effect=lambda callback: (callback(), True)[1])

    def test_shape_success_transfers_region_ownership(self):
        self.assertTrue(self.host._apply_native_shape())
        self.assertEqual(self.user.SetWindowRgn.calls, [(HWND, HRGN, True)])
        self.assertEqual(self.gdi.DeleteObject.calls, [])

    def test_shape_disables_system_backdrop(self):
        self.host._apply_native_shape()
        calls = self.dwm.DwmSetWindowAttribute.calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], HWND)
        self.assertEqual(calls[0][1], 38)
        self.assertEqual(calls[0][2]._obj.value, 1)
        self.assertEqual(calls[0][3], ctypes.sizeof(ctypes.c_int))

    def test_shape_also_works_without_dwm_library(self):
        del self.dlls.dwmapi
        self.assertTrue(self.host._apply_native_shape())

    def test_shape_binds_pointer_sized_handles(self):
        self.host._apply_native_shape()
        self.assertEqual(self.user.GetDpiForWindow.argtypes, [ctypes.c_void_p])
        self.assertIs(self.user.GetDpiForWindow.restype, desktop.wt.UINT)
        self.assertEqual(self.user.SetWindowRgn.argtypes[:2], [ctypes.c_void_p] * 2)
        self.assertIs(self.gdi.CreateRoundRectRgn.restype, ctypes.c_void_p)
        self.assertEqual(self.gdi.DeleteObject.argtypes, [ctypes.c_void_p])

    def test_shape_scales_radius_for_each_dpi(self):
        for dpi in (96, 120, 144, 168, 192, 240):
            with self.subTest(dpi=dpi):
                self.dpi = dpi
                self.size = (round(372 * dpi / 96), round(520 * dpi / 96))
                self.assertTrue(self.host._apply_native_shape())
                diameter = round(16 * dpi / 96) * 2
                self.assertEqual(self.gdi.CreateRoundRectRgn.calls[-1],
                                 (0, 0, self.size[0] + 1, self.size[1] + 1, diameter, diameter))

    def test_dpi_zero_falls_back_to_96(self):
        self.dpi = 0
        self.assertTrue(self.host._apply_native_shape())
        self.assertEqual(self.gdi.CreateRoundRectRgn.calls[-1][-2:], (32, 32))

    def test_missing_hwnd_allocates_nothing(self):
        self.find.return_value = None
        self.user.FindWindowW.result = None
        self.assertFalse(self.host._apply_native_shape())
        self.assertEqual(self.gdi.CreateRoundRectRgn.calls, [])

    def test_empty_window_allocates_nothing(self):
        for size in ((0, 520), (372, 0), (-1, 520)):
            with self.subTest(size=size):
                self.size = size
                self.assertFalse(self.host._apply_native_shape())
        self.assertEqual(self.gdi.CreateRoundRectRgn.calls, [])

    def test_rect_failure_is_reported(self):
        self.rect_ok = False
        self.assertFalse(self.host._apply_native_shape())
        self.host.service.log.warning.assert_called_once()
        self.assertEqual(self.gdi.CreateRoundRectRgn.calls, [])

    def test_allocation_failure_is_reported_without_delete(self):
        self.gdi.CreateRoundRectRgn.result = 0
        self.assertFalse(self.host._apply_native_shape())
        self.host.service.log.warning.assert_called_once()
        self.assertEqual(self.gdi.DeleteObject.calls, [])

    def test_failed_assignment_deletes_owned_region(self):
        self.user.SetWindowRgn.result = 0
        self.assertFalse(self.host._apply_native_shape())
        self.assertEqual(self.gdi.DeleteObject.calls, [(HRGN,)])
        self.host.service.log.warning.assert_called_once()

    def test_exception_during_assignment_also_releases_region(self):
        self.user.SetWindowRgn.effect = Mock(side_effect=OSError('synthetic failure'))
        self.assertFalse(self.host._apply_native_shape())
        self.assertEqual(self.gdi.DeleteObject.calls, [(HRGN,)])

    def test_failure_does_not_poison_next_attempt(self):
        self.user.SetWindowRgn.result = 0
        self.assertFalse(self.host._apply_native_shape())
        self.user.SetWindowRgn.result = 1
        self.assertTrue(self.host._apply_native_shape())
        self.assertEqual(len(self.gdi.DeleteObject.calls), 1)

    def test_recreated_handle_and_size_get_fresh_region(self):
        self.assertTrue(self.host._apply_native_shape())
        self.find.return_value = HWND + 8
        self.user.FindWindowW.result = HWND + 8
        self.size, self.dpi = (558, 780), 144
        self.assertTrue(self.host._apply_native_shape())
        self.assertEqual(self.user.SetWindowRgn.calls[-1][0], HWND + 8)
        self.assertEqual(self.gdi.CreateRoundRectRgn.calls[-1], (0, 0, 559, 781, 48, 48))

    def test_physical_size_binds_dpi_function_before_use(self):
        self.dpi = 144
        self.assertEqual(self.host._physical_size(HWND), (558, 780))
        self.assertEqual(self.user.GetDpiForWindow.argtypes, [ctypes.c_void_p])
        self.assertIs(self.user.GetDpiForWindow.restype, desktop.wt.UINT)
        self.assertEqual(self.user.GetDpiForWindow.calls, [(HWND,)])

    def test_monitor_info_preserves_pointer_sized_monitor(self):
        self.assertIsNotNone(self.host._monitor_info((1800, 1040, 1832, 1080)))
        self.assertEqual(self.user.GetMonitorInfoW.calls[-1][0], HMONITOR)
        self.assertIsNotNone(self.user.GetMonitorInfoW.argtypes)
        self.assertEqual(self.user.GetMonitorInfoW.argtypes[0], ctypes.c_void_p)
        self.assertIs(self.user.MonitorFromPoint.restype, ctypes.c_void_p)

    def test_monitor_fallback_point_has_explicit_signature(self):
        self.assertIsNotNone(self.host._monitor_info())
        self.assertEqual(self.user.MonitorFromPoint.argtypes, [desktop.wt.POINT, desktop.wt.DWORD])
        self.assertIs(self.user.MonitorFromPoint.restype, ctypes.c_void_p)

    def test_toggle_first_use_declares_monitor_return_type(self):
        self.host.show = Mock()
        self.host.toggle()
        self.assertEqual(self.host.tray_monitor, HMONITOR)
        self.assertIs(self.user.MonitorFromPoint.restype, ctypes.c_void_p)
        self.host.show.assert_called_once()

    def test_placement_binds_set_window_pos(self):
        self.host._place_at_tray(372, 520)
        self.assertEqual(len(self.user.SetWindowPos.calls), 1)
        self.assertEqual(self.user.SetWindowPos.calls[0][0], HWND)
        self.assertIsNotNone(self.user.SetWindowPos.argtypes)
        self.assertEqual(self.user.SetWindowPos.argtypes[:2], [ctypes.c_void_p] * 2)
        self.assertIs(self.user.SetWindowPos.restype, desktop.wt.BOOL)

    def test_placement_failure_is_reported(self):
        self.user.SetWindowPos.result = 0
        self.host._place_at_tray(372, 520)
        self.host.service.log.warning.assert_called_once_with('panel_position_failed')

    def test_repair_hides_native_window_even_when_logically_hidden(self):
        self.host.visible = False
        self.host.hide(reason='repair')
        self.form.Hide.assert_called_once()
        self.host._set_panel_topmost.assert_called_once_with(False)

    def test_regular_hide_remains_noop_when_already_hidden(self):
        self.host.hide()
        self.form.Hide.assert_not_called()

    def test_hide_preserves_switch_blur_guard(self):
        self.host.visible = True
        self.host.service.operation = {'kind': 'switch'}
        self.host.hide(reason='blur')
        self.assertTrue(self.host.visible)
        self.form.Hide.assert_not_called()

    def prepare_show(self):
        self.host._style_window = Mock(return_value=True)
        self.host._place_at_tray = Mock()
        self.host._physical_size = Mock(return_value=(372, 520))
        self.host._apply_native_shape = Mock(return_value=True)

    def test_failed_shape_is_not_shown(self):
        self.prepare_show()
        self.host._apply_native_shape.return_value = False
        self.host.show()
        self.form.Show.assert_not_called()
        self.assertFalse(self.host.visible)

    def test_shape_failure_during_relay_keeps_retry(self):
        self.prepare_show()
        self.host._apply_native_shape.return_value = False
        self.host._relay_restore = {'id': 'op', 'visible': True}
        self.host._retry_relay_restore = Mock()
        with patch.object(desktop, 'chatgpt_foreground', return_value=True):
            self.host.show(relay_operation_id='op')
        self.form.Show.assert_not_called()
        self.host._retry_relay_restore.assert_called_once_with('op')
        self.assertEqual(self.host._relay_restore['id'], 'op')

    def test_shape_is_applied_before_show(self):
        self.prepare_show()
        events = []
        self.host._apply_native_shape.side_effect = lambda: (events.append('shape'), True)[1]
        self.form.Show.side_effect = lambda: events.append('show')
        self.host.show()
        self.assertEqual(events, ['shape', 'show'])
        self.assertEqual(self.user.SetForegroundWindow.argtypes, [ctypes.c_void_p])

    def test_show_reapplies_shape_if_handle_changes(self):
        self.prepare_show()
        self.find.side_effect = [HWND, HWND + 8]
        self.host.show()
        self.assertEqual(self.host._apply_native_shape.call_count, 2)
        self.assertEqual(self.user.SetForegroundWindow.calls[-1], (HWND + 8,))

    def test_failed_shape_on_recreated_window_hides_it(self):
        self.prepare_show()
        self.find.side_effect = [HWND, HWND + 8]
        self.host._apply_native_shape.side_effect = [True, False]
        self.host.show()
        self.form.Hide.assert_called_once()
        self.form.Activate.assert_not_called()
        self.assertFalse(self.host.visible)

    def test_lost_handle_after_show_hides_without_activating(self):
        self.prepare_show()
        self.find.side_effect = [HWND, None]
        self.host.show()
        self.form.Hide.assert_called_once()
        self.form.Activate.assert_not_called()

    def test_failed_shape_after_layout_hides_it(self):
        self.prepare_show()
        self.host.visible = True
        self.host._apply_native_shape.return_value = False
        self.host._apply_layout()
        self.form.Hide.assert_called_once()
        self.assertFalse(self.host.visible)

    def test_native_shadow_and_transparency_are_explicitly_disabled(self):
        source = inspect.getsource(desktop.Desktop.run)
        self.assertIn('shadow=False', source)
        self.assertIn('transparent=False', source)

    def test_live_outer_css_uses_opaque_fill_and_one_native_outline(self):
        css = (ROOT / 'src/ui/common.css').read_text(encoding='utf-8')
        self.assertIn('body.live { background: var(--bg); }', css)
        rule = css.split('body:not(.demo) #app {', 1)[1].split('}', 1)[0]
        self.assertIn('border-radius: 0;', rule)
        self.assertIn('box-shadow: none;', rule)
        self.assertIn('border-radius: var(--radius-card);', css)
        self.assertIn('border-radius: var(--radius-control);', css)
        self.assertIn('background: var(--bg); border-radius: var(--window-r);', css)

    def test_product_geometry_and_version_stay_unchanged(self):
        self.assertEqual(APP_VERSION, '1.0.0')
        self.assertEqual(PANEL_CONFIG['radius'], 16)
        self.assertEqual(PANEL_CONFIG['sizes'], {'home': [372, 520], 'workspace': [372, 520]})


if __name__ == '__main__':
    unittest.main()
