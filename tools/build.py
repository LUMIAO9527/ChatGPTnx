"""Build the single Relay application from source.

This project deliberately ships one product language, not runtime themes.
The builder never reads or overwrites accounts.txt, snapshots/ or _data/.
"""
from pathlib import Path
import json
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'src' / 'ui'
RESOURCES = ROOT / '_wip' / 'build' / 'resources'
sys.path.insert(0, str(ROOT / 'src'))
from nx.design import PANEL_CONFIG as CONFIG
from nx.version import APP_VERSION
from nx.resume_policy import ATTENTION_REASONS, RETRYABLE_REASONS
from screen_catalog import CASES

STYLES = ('tokens.css', 'common.css', 'feedback.css')
SCRIPTS = ('usage.js', 'components.js', 'runtime.js', 'preferences.js', 'feedback.js', 'views/accounts.js', 'views/resume.js', 'views/usage.js', 'views/settings.js', 'views/editors.js', 'views/onboarding.js', 'app.js')


def ui_source_digest():
    """One fingerprint for capture and gallery, including injected native policy."""
    sources = sorted((ROOT / 'src/ui').rglob('*')) + [
        ROOT/'tools/screen_catalog.py', ROOT/'src/nx/design.py',
        ROOT/'src/nx/version.py', ROOT/'src/nx/resume_policy.py',
        ROOT/'src/assets/nx-mark.svg', ROOT/'tools/build.py']
    return hashlib.sha256(b''.join(p.read_bytes() for p in sources if p.is_file())).hexdigest()


def panel(*, demo=False, proposal=None):
    cfg = {**CONFIG, 'demo': demo, 'version': APP_VERSION}
    if proposal: raise ValueError('Only the maintained product layout is supported')
    css = '\n'.join((UI / name).read_text(encoding='utf-8') for name in STYLES)
    files = (['demo.js'] if demo else []) + list(SCRIPTS) + (['preview.js'] if demo else [])
    js = '\n'.join((UI / f).read_text(encoding='utf-8') for f in files)
    if not demo and ('@example.com' in js or 'function seed(' in js):
        raise RuntimeError('demonstration data leaked into production panel')
    brand = 'window.NX_BRAND_MARK='+json.dumps((ROOT/'src/assets/nx-mark.svg').read_text(encoding='utf-8').strip())+';\n'
    policy='window.NX_RESUME_POLICY='+json.dumps({'attention':sorted(ATTENTION_REASONS),'retryable':sorted(RETRYABLE_REASONS)})+';\n'
    catalog = 'window.NX_CATALOG='+json.dumps(CASES,ensure_ascii=False)+';\n' if demo else ''
    body_class = 'demo' if demo else 'live'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>n× · ChatGPTnx</title><style>{css}</style></head>
<body class="{body_class}"><div id="app"></div><script>window.NX_CONFIG=Object.freeze({json.dumps(cfg, ensure_ascii=False)});\n{brand}{policy}{catalog}{js}</script></body></html>'''


def build():
    RESOURCES.mkdir(parents=True, exist_ok=True)
    (RESOURCES / 'panel.html').write_text(panel(demo=False), encoding='utf-8')
    (RESOURCES / 'demo.html').write_text(panel(demo=True), encoding='utf-8')
    (RESOURCES / 'nx.ico').write_bytes((ROOT / 'src' / 'assets' / 'nx.ico').read_bytes())
    (RESOURCES / 'switch_account.ps1').write_bytes((ROOT / 'src' / 'switch_account.ps1').read_bytes())
    (RESOURCES / 'continue_in_desktop.ps1').write_bytes((ROOT / 'src' / 'continue_in_desktop.ps1').read_bytes())
    print('Built ChatGPTnx resources')


if __name__ == '__main__':
    build()
