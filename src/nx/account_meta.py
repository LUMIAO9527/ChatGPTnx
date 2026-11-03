"""The account editor and portable backups share this metadata contract."""
from __future__ import annotations

from datetime import date
import re
import unicodedata

ALIAS_LIMIT = 24
FIELDS = frozenset(('alias', 'subscription_date'))


def validate(changes):
    if not isinstance(changes, dict) or not changes or changes.keys() - FIELDS:
        raise ValueError('账号信息字段不合法')
    result = dict(changes)
    if 'alias' in result:
        alias = result['alias']
        if (not isinstance(alias, str) or len(alias.strip()) > ALIAS_LIMIT
                or any(unicodedata.category(c).startswith('C') for c in alias)):
            raise ValueError(f'昵称最多 {ALIAS_LIMIT} 个可显示字符')
        result['alias'] = alias.strip()
    if 'subscription_date' in result:
        value = result['subscription_date']
        if value not in (None, ''):
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
                raise ValueError('日期格式应为 YYYY-MM-DD')
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ValueError('请输入有效的到期日期') from None
        result['subscription_date'] = value or None
    return result


def restored(raw):
    """Keep each valid field when recovering an older local state document."""
    result = {}
    if isinstance(raw, dict):
        for key in FIELDS & raw.keys():
            try:
                result.update(validate({key: raw[key]}))
            except ValueError:
                pass
    return result
