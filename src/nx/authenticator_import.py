"""Read authenticator transfer QR images locally and return account material.

Supports otpauth TOTP enrolment and Google Authenticator's version 1 and 2 transfer
payload. No image, URI or seed is written by this module.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .totp import normalize_secret

MAX_PAYLOAD = 131072
MAX_ACCOUNTS = 200


class ImportError(ValueError):
    """A message that can be displayed without including account material."""


@dataclass(frozen=True)
class Account:
    name: str
    issuer: str
    secret: str = field(repr=False)


@dataclass(frozen=True)
class Transfer:
    accounts: tuple[Account, ...] = field(repr=False)
    batch_id: int = 0
    batch_size: int = 1
    batch_index: int = 0


def _varint(data, at):
    value = 0
    for shift in range(0, 70, 7):
        if at >= len(data):
            raise ImportError('验证器导出内容不完整')
        byte = data[at]
        at += 1
        if shift == 63 and byte > 1:
            raise ImportError('验证器导出内容无法识别')
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, at
    raise ImportError('验证器导出内容无法识别')


def _fields(data):
    at = 0
    while at < len(data):
        key, at = _varint(data, at)
        number, wire = key >> 3, key & 7
        if not number:
            raise ImportError('验证器导出内容无法识别')
        if wire == 0:
            value, at = _varint(data, at)
        elif wire == 2:
            size, at = _varint(data, at)
            if size > MAX_PAYLOAD or at + size > len(data):
                raise ImportError('验证器导出内容不完整')
            value, at = data[at:at + size], at + size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if at + size > len(data):
                raise ImportError('验证器导出内容不完整')
            value, at = data[at:at + size], at + size
        else:
            raise ImportError('验证器导出内容无法识别')
        yield number, wire, value


def _otp(data):
    values = {}
    for number, wire, value in _fields(data):
        if number in values:
            raise ImportError('验证器导出条目存在重复字段')
        values[number] = (wire, value)
    for number, expected in ((4, 1), (5, 1), (6, 2)):
        if values.get(number) != (0, expected):
            raise ImportError('请选择使用 SHA-1、6 位和 30 秒周期的验证器账号')
    try:
        if values[1][0] != 2:
            raise ValueError()
        secret = normalize_secret(base64.b32encode(values[1][1]).decode('ascii'))
        name = values.get(2, (2, b''))[1].decode('utf-8')
        issuer = values.get(3, (2, b''))[1].decode('utf-8')
        if len(name) > 512 or len(issuer) > 128:
            raise ValueError()
    except (KeyError, ValueError, AttributeError, UnicodeError):
        raise ImportError('验证器导出条目无法识别') from None
    return Account(name, issuer, secret)


def parse_uri(text):
    if not isinstance(text, str) or len(text) > MAX_PAYLOAD:
        raise ImportError('验证器导出内容过长')
    try:
        uri = urlparse(text.strip())
        query = parse_qs(uri.query)
        if uri.scheme.lower() == 'otpauth' and uri.netloc.lower() == 'totp':
            name = unquote(uri.path.lstrip('/'))
            return Transfer((Account(name, (query.get('issuer') or [''])[0], normalize_secret(text)),))
        if uri.scheme.lower() != 'otpauth-migration' or uri.netloc.lower() != 'offline':
            raise ValueError()
        encoded = query.get('data', [])
        if len(encoded) != 1:
            raise ValueError()
        raw = encoded[0].replace(' ', '+')
        payload = base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True)
        if len(payload) > MAX_PAYLOAD:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ImportError('请选择验证器的导出二维码或 TOTP 密钥二维码') from None
    accounts, metadata = [], {}
    for number, wire, value in _fields(payload):
        if number == 1:
            if wire != 2 or len(accounts) >= MAX_ACCOUNTS:
                raise ImportError('验证器导出条目过多或格式不正确')
            accounts.append(_otp(value))
        elif number in (2, 3, 4, 5):
            if wire != 0 or number in metadata:
                raise ImportError('验证器导出分组无法识别')
            metadata[number] = value
    size, index = metadata.get(3, 1), metadata.get(4, 0)
    if metadata.get(2, 1) not in (1, 2) or not accounts or not 1 <= size <= 50 or not 0 <= index < size:
        raise ImportError('验证器导出版本或分组不受支持')
    return Transfer(tuple(accounts), metadata.get(5, 0), size, index)


def combine(transfers):
    groups, accounts = {}, []
    for transfer in transfers:
        if transfer.batch_size > 1:
            key = (transfer.batch_id, transfer.batch_size)
            group = groups.setdefault(key, {})
            old = group.get(transfer.batch_index)
            if old is not None:
                if old.accounts != transfer.accounts:
                    raise ImportError('同一组验证器导出内容不一致')
                continue
            group[transfer.batch_index] = transfer
        else:
            accounts.extend(transfer.accounts)
    for (_, size), group in groups.items():
        if len(group) != size:
            raise ImportError(f'这组导出共有 {size} 张二维码，请一次选择全部图片')
        for index in range(size):
            accounts.extend(group[index].accounts)
    unique = list(dict.fromkeys(accounts))
    if not unique or len(unique) > MAX_ACCOUNTS:
        raise ImportError('验证器导出条目为空或过多')
    return unique


def read_images(paths):
    from PIL import Image, UnidentifiedImageError
    import zxingcpp

    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= 50:
        raise ImportError('请选择验证器导出图片')
    transfers = []
    for value in paths:
        path = Path(value)
        try:
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp') or path.stat().st_size > 20 * 1024 * 1024:
                raise ImportError('请选择小于 20 MB 的二维码图片')
            with Image.open(path) as original:
                if original.width * original.height > 24000000:
                    raise ImportError('二维码图片尺寸过大，请裁取二维码后重试')
                image = original.convert('RGB')
                try:
                    codes = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
                    if not codes:
                        raise ImportError('图片中没有识别到二维码，请使用清晰的原图')
                    for barcode in codes:
                        transfers.append(parse_uri(barcode.text))
                finally:
                    image.close()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
            raise ImportError('无法读取二维码图片，请重新选择') from None
    return combine(transfers)
