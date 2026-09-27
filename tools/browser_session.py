"""Offline browser fixtures shared by layout tests and preview capture.

set_content avoids file:// policy differences in managed browser installations.
Query parameters are injected into the DEMO copy only; no product code or API
response is patched. The native pywebview bridge is not exercised by this tool.
"""
from contextlib import contextmanager
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def demo_html(query=''):
    source = (ROOT/'_wip/build/resources/demo.html').read_text(encoding='utf-8')
    return source.replace('location.search', json.dumps('?' + query)) if query else source


@contextmanager
def browser_session(executable):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit('Install the optional browser test dependency: python -m pip install playwright') from error
    with sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=str(executable), headless=True,
                                        args=['--no-sandbox', '--disable-extensions'])
        try:
            yield browser
        finally:
            browser.close()
