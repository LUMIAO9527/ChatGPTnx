"""Explorer icon loss and recovery with isolated Win32 APIs."""
from pathlib import Path
import ctypes
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
with patch.object(ctypes, 'WINFUNCTYPE', getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE), create=True):
    from nx import trayicon as tray

HWND, HICON, TASKBAR_CREATED = 0x123456789, 0x234567890, 0xC137


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.available, self.present = True, False
        self.records = []
        self.user, self.kernel = Mock(), Mock()
        self.user.SetTimer.return_value = tray.ICON_RETRY_TIMER
        self.user.RegisterWindowMessageW.return_value = TASKBAR_CREATED
        self.user.GetDpiForSystem.return_value = 96
        self.user.RegisterClassW.return_value = 1
        self.user.CreateWindowExW.return_value = HWND
        self.user.DefWindowProcW.return_value = 41
        self.kernel.GetModuleHandleW.return_value = HICON

        def notify(command, pointer):
            data = pointer._obj
            self.records.append((command, data.hWnd, data.uID, data.uFlags,
                                 data.uCallbackMessage, data.hIcon, data.szTip, data.uVersion))
            if command == tray.NIM_DELETE:
                self.present = False
                return True
            if not self.available:
                return False
            if command == tray.NIM_ADD:
                if self.present:
                    return False
                self.present = True
                return True
            return self.present

        self.shell = SimpleNamespace(Shell_NotifyIconW=Mock(side_effect=notify))
        self.addCleanup(patch.stopall)
        patch.object(ctypes, 'windll', SimpleNamespace(
            user32=self.user, shell32=self.shell, kernel32=self.kernel), create=True).start()
        self.clicked, self.log = Mock(), Mock()
        self.icon = tray.TrayIcon('unused.ico', 'ChatGPTnx', self.clicked, lambda: [], log=self.log)
        self.icon._hwnd, self.icon._hicon = HWND, HICON
        self.icon._taskbar_created = TASKBAR_CREATED

    def test_explorer_loss_restores_current_tooltip_icon_and_click_callback(self):
        self.assertTrue(self.icon._register_icon('startup'))
        self.present = False
        self.icon.title = 'ChatGPTnx updated'
        self.icon._wndproc(HWND, TASKBAR_CREATED, 0, 0)
        self.assertTrue(self.present)
        added = self.records[-2]
        self.assertEqual(added[:3], (tray.NIM_ADD, HWND, 1))
        self.assertEqual(added[3:7], (tray.NIF_MESSAGE | tray.NIF_ICON | tray.NIF_TIP,
                                     tray.WM_TRAYCALLBACK, HICON, 'ChatGPTnx updated'))
        self.assertEqual(self.records[-1][0], tray.NIM_SET_VERSION)
        self.assertEqual(self.records[-1][-1], 4)
        self.icon._wndproc(HWND, tray.WM_TRAYCALLBACK, 1 << 16, tray.WM_LBUTTONUP)
        self.clicked.assert_called_once_with()

    def test_temporarily_unavailable_shell_retries_and_cancels_timer_on_success(self):
        self.available = False
        self.assertFalse(self.icon._register_icon('taskbar'))
        self.assertTrue(self.icon._retrying)
        self.user.SetTimer.assert_called_once_with(HWND, tray.ICON_RETRY_TIMER, tray.ICON_RETRY_MS, None)
        self.icon._wndproc(HWND, tray.WM_TIMER, tray.ICON_RETRY_TIMER, 0)
        self.user.SetTimer.assert_called_once()
        self.log.warning.assert_called_once()
        self.available = True
        self.icon._wndproc(HWND, tray.WM_TIMER, tray.ICON_RETRY_TIMER, 0)
        self.assertTrue(self.present)
        self.assertFalse(self.icon._retrying)
        self.user.KillTimer.assert_called_once_with(HWND, tray.ICON_RETRY_TIMER)

    def test_repeated_taskbar_notification_preserves_one_icon(self):
        self.assertTrue(self.icon._register_icon('startup'))
        self.icon._wndproc(HWND, TASKBAR_CREATED, 0, 0)
        self.assertTrue(self.present)
        self.assertEqual([r[0] for r in self.records[-3:]],
                         [tray.NIM_ADD, tray.NIM_MODIFY, tray.NIM_SET_VERSION])
        self.assertFalse(self.icon._retrying)

    def test_unavailable_shell_at_startup_does_not_end_message_pump(self):
        self.available = False
        def get_message(pointer, *_):
            if self.user.GetMessageW.call_count == 1:
                self.available = True
                pointer._obj.message = tray.WM_TIMER
                pointer._obj.wParam = tray.ICON_RETRY_TIMER
                return 1
            return 0
        self.user.GetMessageW.side_effect = get_message
        self.user.DispatchMessageW.side_effect = lambda p: self.icon._wndproc(
            HWND, p._obj.message, p._obj.wParam, p._obj.lParam)
        with patch.object(tray, '_load_hicon', return_value=HICON):
            self.icon._loop()
        self.assertTrue(self.icon._ready.is_set())
        self.assertTrue(self.present)
        self.assertEqual(self.user.GetMessageW.call_count, 2)
        self.user.RegisterWindowMessageW.assert_called_once_with('TaskbarCreated')

    def test_shutdown_removes_retry_and_icon_and_ignores_late_recovery(self):
        self.icon._register_icon('startup')
        self.icon._retrying = True
        self.icon._wndproc(HWND, tray.WM_DESTROY, 0, 0)
        self.assertFalse(self.present)
        self.assertFalse(self.icon._retrying)
        self.assertIsNone(self.icon._hwnd)
        self.assertIsNone(self.icon._hicon)
        self.user.DestroyIcon.assert_called_once_with(HICON)
        self.user.PostQuitMessage.assert_called_once_with(0)
        count = len(self.records)
        self.icon._wndproc(HWND, TASKBAR_CREATED, 0, 0)
        self.assertEqual(len(self.records), count)

    def test_other_messages_are_forwarded(self):
        self.assertEqual(self.icon._wndproc(HWND, tray.WM_NULL, 0, 0), 41)
        self.assertEqual(self.icon._wndproc(HWND, tray.WM_TIMER, 42, 0), 41)


if __name__ == '__main__':
    unittest.main()
