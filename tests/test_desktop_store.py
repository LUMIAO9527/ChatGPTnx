"""Filesystem checks for nx.desktop_store against a synthetic profile tree.

No real ChatGPT installation is touched: the profile root is a temporary
directory with the same relative layout. The process-level helpers
(chatgpt_running / stop_app / launch_chatgpt) are replaced so the tests never
stop or start anything.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nx import desktop_store


def build_profile(root: Path) -> None:
    """Create the same relative paths a real Chromium profile carries."""
    files = [
        'Network/Cookies',
        'Network/Cookies-journal',
        'Local Storage/leveldb/000005.ldb',
        'Local Storage/leveldb/CURRENT',
        'Session Storage/000003.log',
        'IndexedDB/https_chatgpt.com_0.indexeddb.leveldb/000001.log',
        'Cache/Cache_Data/data_1',
        'Code Cache/js/index',
        'GPUCache/data_0',
        'Service Worker/CacheStorage/abc/index',
        'Preferences',
        'Local State',
        'Partitions/codex-browser-app/Network/Cookies',
        'Partitions/codex-browser-app/Local Storage/leveldb/000010.ldb',
        'Partitions/codex-browser-app/Preferences',
    ]
    for name in files:
        path = root / Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 32)


class ClearTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name) / 'Default'
        self.root.mkdir(parents=True)
        build_profile(self.root)
        patches = [
            mock.patch.object(desktop_store, 'chatgpt_running', return_value=False),
            mock.patch.object(desktop_store, 'stop_app', return_value=True),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.dir.cleanup()

    def test_removes_cookies_storage_and_cache(self):
        result = desktop_store.clear(roots=[self.root], restart=False)
        self.assertTrue(result['ok'], result)
        for gone in ('Network/Cookies', 'Network/Cookies-journal',
                     'Local Storage', 'Session Storage', 'IndexedDB',
                     'Cache', 'Code Cache', 'GPUCache',
                     'Service Worker/CacheStorage'):
            self.assertFalse((self.root / Path(gone)).exists(), gone)
        self.assertGreater(result['removed_files'], 0)
        self.assertGreater(result['freed_bytes'], 0)

    def test_keeps_settings_unless_deep(self):
        desktop_store.clear(roots=[self.root], restart=False)
        self.assertTrue((self.root / 'Preferences').is_file())
        self.assertTrue((self.root / 'Local State').is_file())

    def test_deep_also_removes_settings(self):
        desktop_store.clear(roots=[self.root], deep=True, restart=False)
        self.assertFalse((self.root / 'Preferences').exists())
        self.assertFalse((self.root / 'Local State').exists())

    def test_partition_copies_are_cleared(self):
        desktop_store.clear(roots=[self.root], restart=False)
        partition = self.root / 'Partitions' / 'codex-browser-app'
        self.assertFalse((partition / 'Network' / 'Cookies').exists())
        self.assertFalse((partition / 'Local Storage').exists())
        # The partition's own Preferences is settings, not storage.
        self.assertTrue((partition / 'Preferences').is_file())

    def test_single_group(self):
        desktop_store.clear(groups=('cookies',), roots=[self.root], restart=False)
        self.assertFalse((self.root / 'Network' / 'Cookies').exists())
        self.assertTrue((self.root / 'Local Storage' / 'leveldb' / 'CURRENT').is_file())

    def test_idempotent(self):
        desktop_store.clear(roots=[self.root], restart=False)
        second = desktop_store.clear(roots=[self.root], restart=False)
        self.assertTrue(second['ok'])
        self.assertEqual(second['removed_files'], 0)
        self.assertEqual(second['freed_bytes'], 0)

    def test_rejects_unknown_group(self):
        with self.assertRaises(desktop_store.StoreError):
            desktop_store.clear(groups=('everything',), roots=[self.root], restart=False)

    def test_reports_missing_root(self):
        result = desktop_store.clear(roots=[Path(self.dir.name) / 'nope'], restart=False)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], '没有找到 ChatGPT 桌面端的数据目录')

    def test_no_root_at_all(self):
        with mock.patch.object(desktop_store, 'profile_roots', return_value=[]):
            result = desktop_store.clear(restart=False)
        self.assertFalse(result['ok'])
        self.assertIn('没有找到', result['error'])

    def test_running_app_blocks_cleanup_when_it_will_not_stop(self):
        with mock.patch.object(desktop_store, 'chatgpt_running', return_value=True), \
             mock.patch.object(desktop_store, 'stop_app', return_value=False):
            result = desktop_store.clear(roots=[self.root], restart=False)
        self.assertFalse(result['ok'])
        self.assertIn('没有退出', result['error'])
        self.assertTrue((self.root / 'Network' / 'Cookies').exists())

    def test_restart_is_requested_only_when_it_was_running(self):
        with mock.patch.object(desktop_store, 'chatgpt_running', return_value=True), \
             mock.patch.object(desktop_store, 'stop_app', return_value=True), \
             mock.patch('nx.desktop.launch_chatgpt') as launch:
            desktop_store.clear(roots=[self.root], restart=True)
        launch.assert_called_once()

    def test_no_restart_when_it_was_not_running(self):
        with mock.patch('nx.desktop.launch_chatgpt') as launch:
            desktop_store.clear(roots=[self.root], restart=True)
        launch.assert_not_called()


class RootDiscoveryTests(unittest.TestCase):
    def test_finds_package_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            packages = Path(tmp) / 'Packages'
            profile = (packages / 'OpenAI.Codex_2p2nqsd0c76g0' / 'LocalCache' / 'Roaming'
                       / 'Codex' / 'web' / 'Codex' / 'Default')
            profile.mkdir(parents=True)
            with mock.patch.dict('os.environ', {'LOCALAPPDATA': tmp, 'APPDATA': ''}):
                roots = desktop_store.profile_roots()
            self.assertIn(profile, roots)

    def test_ignores_other_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            packages = Path(tmp) / 'Packages'
            (packages / 'Other.App_x' / 'LocalCache').mkdir(parents=True)
            with mock.patch.dict('os.environ', {'LOCALAPPDATA': tmp, 'APPDATA': ''}):
                self.assertEqual(desktop_store.profile_roots(), [])


if __name__ == '__main__':
    unittest.main()