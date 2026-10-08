"""One schema for persisted settings; invalid data never enables automation."""
from __future__ import annotations
import copy
import re

DEFAULTS = {'appearance': 'system', 'autostart': False,
            'auto_relay': False, 'auto_relay_excluded': [],
            'early_anchor': False, 'early_anchor_accounts': [],
            'task_continuation': True, 'resume_message': '继续',
            'resume_transport': 'desktop_ui',
            'resume_source_thread_id': '',
            'notify_low': False, 'notify_reset_expiry': True, 'notify_credential': True,
            'poll_minutes': 10, 'query_timeout': 45, 'query_workers': 2}
ENUMS = {'appearance': ('system', 'light', 'dark'),
         'resume_transport': ('desktop_bridge', 'desktop_ui')}
RANGES = {'poll_minutes': (1, 1440), 'query_timeout': (5, 180), 'query_workers': (1, 2)}

def valid_setting(key, value):
    if key not in DEFAULTS:
        return False
    if key in ENUMS:
        return type(value) is type(DEFAULTS[key]) and value in ENUMS[key]
    if key in RANGES:
        low, high = RANGES[key]
        return type(value) is int and low <= value <= high
    if isinstance(DEFAULTS[key], bool):
        return type(value) is bool
    if key == 'resume_message':
        return (isinstance(value, str) and value == value.strip()
                and 1 <= len(value) <= 200 and value.isprintable())
    if key == 'resume_source_thread_id':
        return isinstance(value, str) and (value == '' or bool(re.fullmatch(
            r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value)))
    if key in ('auto_relay_excluded', 'early_anchor_accounts'):
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    return False

def normalize_settings(raw):
    settings = copy.deepcopy(DEFAULTS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if valid_setting(key, value):
                settings[key] = copy.deepcopy(value)
            elif key in ('auto_relay', 'task_continuation', 'early_anchor'):
                settings[key] = False
    settings['auto_relay_excluded'] = list(dict.fromkeys(
        x for x in settings['auto_relay_excluded'] if x))[:100]
    settings['early_anchor_accounts'] = list(dict.fromkeys(
        x for x in settings['early_anchor_accounts'] if x))[:100]
    return settings
