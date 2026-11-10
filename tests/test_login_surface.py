import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LoginSurfaceTests(unittest.TestCase):
    def classify(self, url='https://auth.openai.com/log-in', *, name='Email address', password=False,
                 text='Welcome back', app=False, buttons=None):
        payload = {'url': url, 'edits': [{'name': name, 'password': password}], 'text': text,
                   'app': app, 'buttons': buttons or ['Continue']}
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
            'Bypass', '-File', str(ROOT / 'src/login_fill.ps1'), '-SurfaceFixture'],
            input=json.dumps(payload).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15, creationflags=0x08000000)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace')[-1200:])
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_authentication_domain_and_email_field(self):
        self.assertEqual(self.classify()['step'], 'email')

    def test_password_field_on_authenticated_signin_path(self):
        self.assertEqual(self.classify('https://auth.openai.com/u/login/password', name='Password', password=True)['step'], 'password')

    def test_ordinary_chat_and_other_hosts_have_no_login_stage(self):
        for url in ('https://chatgpt.com/c/123', 'https://example.com/login',
                    'https://auth.openai.com.example.com/log-in',
                    'https://example.com/?auth.openai.com/log-in', 'http://auth.openai.com/log-in',
                    'https://auth.openai.com@evil.example/log-in'):
            with self.subTest(url=url):
                self.assertEqual(self.classify(url)['step'], 'unknown')

    def test_account_creation_and_password_reset_are_separate(self):
        for path in ('/create-account', '/u/signup/password', '/reset-password', '/settings'):
            with self.subTest(path=path):
                self.assertEqual(self.classify('https://auth.openai.com'+path, password=True)['surface'], 'none')

    def test_one_unnamed_edit_is_not_assumed_to_be_email(self):
        self.assertEqual(self.classify(name='Search')['step'], 'unknown')

    def test_app_launch_requires_the_signin_action(self):
        self.assertEqual(self.classify('app://-/index.html', app=True, buttons=['Continue to sign in'])['step'], 'launch')
        self.assertEqual(self.classify('app://-/index.html', app=True, name='Message')['step'], 'unknown')

    def test_totp_page_mentions_account_email_without_becoming_email_challenge(self):
        info = self.classify('https://auth.openai.com/u/mfa-otp-challenge', name='Verification code',
                             text='Enter a code from your authenticator. a@example.com')
        self.assertEqual((info['step'], info['hint']), ('otp', 'authenticator'))

    def test_email_phone_and_human_challenges_are_recognized(self):
        for text, hint in (('We sent a code to your email', 'email_code'), ('验证码已发送到邮箱', 'email_code'),
                           ('Verify your phone number', 'phone'), ('Verify that you are human', 'human_check')):
            with self.subTest(hint=hint):
                self.assertEqual(self.classify(name='Verification code', text=text)['hint'], hint)
