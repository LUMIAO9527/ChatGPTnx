"""Render checks for the first-use view without a browser.

`src/ui/views/onboarding.js` is a pure function from data to an HTML string, so
Node can render it with tiny stubs for the shared UI helpers. This covers the
location screen (card, connection gating, footer actions) and the failed
adoption copy that the Playwright checks only reach with a full browser.
"""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const sandbox = {window: {}};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const onboarding = sandbox.window.NXViews.onboarding;
const esc = value => String(value ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const icon = name => '<svg data-icon="' + name + '"></svg>';
const statusBar = options => '<div class="status-bar" data-tone="' + options.tone + '">'
  + '<span class="status-text">' + esc(options.text) + '</span></div>';
const render = c => onboarding({
  data: c.data,
  ui: c.ui || {},
  config: c.config || {},
  esc,
  icon,
  tool: () => '<button class="settings"></button>',
  busy: !!c.busy,
  statusBar,
  statusRegion: inner => '<div class="status-region">' + inner + '</div>',
  brandMark: () => '<span class="brand-mark"></span>',
  connected: c.connected !== false,
  bridgeError: c.bridgeError || ''
});
const location = {current: 'C:/Users/demo/Downloads/ChatGPTnx',
                  recommended: 'D:/ChatGPTnx', can_relocate: true};
process.stdout.write(JSON.stringify({
  location: render({data: {location, chatgpt_running: true}}),
  disconnected: render({data: {location, chatgpt_running: true}, connected: false}),
  keep_only: render({data: {location: {...location, can_relocate: false}, chatgpt_running: true}}),
  busy: render({data: {location, operation: {kind: 'location', phase: '复制程序'}}, busy: true}),
  failed_protect: render({data: {location: null, pending: null, operation: null,
                                 last_error: {code: 'protect'}, chatgpt_running: true}}),
  failed_credential: render({data: {location: null, pending: null, operation: null,
                                    last_error: {code: 'credential'}, chatgpt_running: false}}),
  ready: render({data: {location: null, pending: 'first@example.com', operation: null,
                        last_error: null, chatgpt_running: true}})
}));
'''


@unittest.skipUnless(NODE, 'Node.js is not available for the JavaScript view check')
class OnboardingViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [NODE, '-e', HARNESS, str(ROOT / 'src/ui/views/onboarding.js')],
            capture_output=True, encoding='utf-8', timeout=60, cwd=str(ROOT))
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.views = json.loads(result.stdout)

    def test_location_screen_offers_the_folder_card_and_both_actions(self):
        view = self.views['location']
        self.assertIn('class="location-row"', view)
        self.assertIn('data-action="location-browse"', view)
        self.assertIn('class="onboarding-foot"', view)
        self.assertIn('data-action="location-keep"', view)
        self.assertIn('data-action="location-install"', view)
        self.assertIn('继续使用当前位置', view)
        self.assertIn('安装到推荐位置', view)
        self.assertIn('D:/ChatGPTnx', view)

    def test_location_screen_requires_the_local_bridge_connection(self):
        connected = self.views['location']
        disconnected = self.views['disconnected']
        self.assertIn('class="onboarding-foot"', connected)
        self.assertNotIn('class="onboarding-foot"', disconnected)
        self.assertNotIn('data-action="location-keep"', disconnected)
        self.assertIn('正在连接本地应用…', disconnected)
        row = disconnected.split('class="location-row"', 1)[1].split('>', 1)[0]
        self.assertIn('disabled', row)

    def test_location_screen_without_relocation_keeps_only_the_tray_action(self):
        view = self.views['keep_only']
        self.assertIn('data-action="location-keep"', view)
        self.assertNotIn('data-action="location-install"', view)
        self.assertIn('onboarding-foot single', view)

    def test_location_screen_reports_install_progress_and_locks_actions(self):
        view = self.views['busy']
        self.assertIn('正在安装…', view)
        self.assertIn('复制程序', view)
        self.assertIn('data-action="location-keep"', view)
        self.assertIn('data-action="location-install"', view)
        self.assertGreaterEqual(view.count(' disabled'), 2)

    def test_failed_adoption_uses_failure_copy_before_any_account_is_pending(self):
        # An unreadable credential fails before data.pending is set; the title,
        # subtitle and status must still describe the failure, not the wait.
        view = self.views['failed_protect']
        self.assertIn('保存未完成', view)
        self.assertIn('当前 Windows 用户无法加密凭据。', view)
        self.assertIn('重启电脑后再试', view)
        self.assertNotIn('等待你完成登录', view)
        self.assertNotIn('在 ChatGPT 桌面端登录', view)
        self.assertIn('保存未完成 · 未加入账号列表', view)

    def test_credential_failure_keeps_the_actionable_failure_copy(self):
        view = self.views['failed_credential']
        self.assertIn('保存未完成', view)
        self.assertIn('登录凭据正在更新。', view)
        self.assertIn('在 ChatGPT 桌面端重新登录', view)
        self.assertNotIn('等待你完成登录', view)

    def test_pending_account_keeps_the_confirmation_flow(self):
        view = self.views['ready']
        self.assertIn('账号已就绪', view)
        self.assertIn('data-action="adopt"', view)
        self.assertIn('确认保存账号', view)
        self.assertNotIn('保存未完成', view)


if __name__ == '__main__':
    unittest.main()