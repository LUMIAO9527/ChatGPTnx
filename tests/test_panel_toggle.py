"""Tray blur/click ordering with fake timers and isolated Win32 APIs."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from nx.desktop import Desktop


class PanelToggleTests(unittest.TestCase):
    def setUp(self):
        self.service = SimpleNamespace(listeners=[], operation=None, log=Mock())
        self.panel = Desktop(self.service)
        self.panel.window = object()
        self.panel.icon = Mock()
        self.panel.icon.rect.return_value = (10, 10, 30, 30)
        self.user = Mock()
        self.user.GetForegroundWindow.return_value = 999
        self.cursor = (20, 20)
        def cursor(pointer):
            pointer._obj.x, pointer._obj.y = self.cursor
            return True
        self.user.GetCursorPos.side_effect = cursor
        self.addCleanup(patch.stopall)
        patch.object(ctypes, 'windll', SimpleNamespace(user32=self.user), create=True).start()
        patch('nx.desktop._find_hwnd', return_value=123).start()
        self.timer = patch('nx.desktop.threading.Timer').start()
        self.form = Mock()
        patch.object(self.panel, '_form', return_value=self.form).start()
        patch.object(self.panel, '_dispatch_ui', side_effect=lambda action: action() or True).start()
        for name in ('_style_window', '_place_at_tray', '_post_script'):
            patch.object(self.panel, name).start()
        patch.object(self.panel, '_physical_size', return_value=(372, 520)).start()
        patch.object(self.panel, '_apply_native_shape', return_value=True).start()
        patch.object(self.panel, '_set_panel_topmost', return_value=True).start()

    def test_second_click_closes_even_when_blur_arrives_first(self):
        self.panel.toggle()
        self.assertTrue(self.panel.visible)
        self.panel.hide(reason='blur')
        blur = self.timer.call_args.args[1]
        blur()  # Cursor is on the icon: do not close before its release.
        self.assertTrue(self.panel.visible)
        self.panel.toggle()
        blur()  # A late duplicate cannot reopen the panel.
        self.assertFalse(self.panel.visible)
        self.form.Show.assert_called_once()
        self.form.Hide.assert_called_once()

    def test_click_outside_closes_after_focus_settles(self):
        self.panel.show()
        self.cursor = (200, 200)
        self.panel.hide(reason='focus')
        self.assertTrue(self.panel.visible)
        self.timer.call_args.args[1]()
        self.assertFalse(self.panel.visible)
        self.form.Hide.assert_called_once()

    def test_returned_panel_focus_cancels_blur_close(self):
        self.panel.show()
        self.cursor = (200, 200)
        self.panel.hide(reason='blur')
        self.user.GetForegroundWindow.return_value = 123
        self.timer.call_args.args[1]()
        self.assertTrue(self.panel.visible)
        self.form.Hide.assert_not_called()

    def test_blur_before_queued_show_does_not_cancel_opening(self):
        queued = []
        self.panel._dispatch_ui = lambda action: queued.append(action) or True
        self.panel.toggle()
        self.panel.hide(reason='blur')
        queued[0]()
        self.timer.call_args.args[1]()
        self.assertTrue(self.panel.visible)
        self.form.Show.assert_called_once()

    def test_out_of_order_show_and_hide_callbacks_follow_latest_click(self):
        queued = []
        self.panel._dispatch_ui = lambda action: queued.append(action) or True
        self.panel.toggle()
        self.panel.toggle()
        queued[1]()
        queued[0]()
        self.assertFalse(self.panel.visible)
        self.form.Show.assert_not_called()
        self.panel.toggle()
        latest = queued[-1]
        queued[1]()  # Old hide callback must not hide the latest show.
        latest()
        self.assertTrue(self.panel.visible)
        self.form.Show.assert_called_once()


if __name__ == '__main__':
    unittest.main()
