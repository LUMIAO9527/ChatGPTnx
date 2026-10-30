"""An accepted update must still close when tray/hotkey cleanup fails."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.desktop import Desktop


class UpdateShutdownTests(unittest.TestCase):
    def setUp(self):
        self.host = object.__new__(Desktop)
        self.host.service = SimpleNamespace(log=Mock(), stop=threading.Event())
        self.host.closing = False
        self.host.hotkeys = Mock()
        self.host.icon = Mock()
        self.host.window = Mock()
        self.form = Mock()
        self.host._form = Mock(return_value=self.form)
        self.host._dispatch_ui = Mock(side_effect=lambda callback: (callback(), True)[1])

    def test_update_close_survives_hotkey_and_tray_failures(self):
        self.host.hotkeys.close.side_effect = RuntimeError('fixture')
        self.host.icon.stop.side_effect = RuntimeError('fixture')
        self.host.shutdown_for_update()
        self.assertTrue(self.host.service.stop.is_set())
        self.assertTrue(self.host.closing)
        self.host.icon.stop.assert_called_once()
        self.form.Close.assert_called_once()

    def test_missing_native_form_uses_window_close(self):
        self.host._form.return_value = None
        self.host.shutdown_for_update()
        self.host.window.destroy.assert_called_once()

    def test_unavailable_ui_dispatch_still_closes_window(self):
        self.host._dispatch_ui = Mock(return_value=False)
        self.host.shutdown_for_update()
        self.host.window.destroy.assert_called_once()

    def test_closing_flag_is_set_before_close_callback(self):
        self.form.Close.side_effect = lambda: self.assertTrue(self.host.closing)
        self.host.shutdown_for_update()
        self.form.Close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
