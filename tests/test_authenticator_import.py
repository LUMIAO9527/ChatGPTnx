import base64
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

from nx.authenticator_import import parse_uri, combine, read_images, ImportError

KEY = b'12345678901234567890'
SECRET = base64.b32encode(KEY).decode()


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def number(field, value):
    return varint(field << 3) + varint(value)


def blob(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


def transfer_uri(name='OpenAI:a@example.com', *, batch_size=1, batch_index=0,
                 algorithm=1, digits=1, kind=2, secret=KEY, version=1):
    entry = blob(1, secret) + blob(2, name.encode()) + blob(3, b'OpenAI')
    entry += number(4, algorithm) + number(5, digits) + number(6, kind)
    payload = blob(1, entry) + number(2, version) + number(3, batch_size)
    payload += number(4, batch_index) + number(5, 1234)
    return 'otpauth-migration://offline?data=' + quote(base64.b64encode(payload).decode(), safe='')


class AuthenticatorImportTests(unittest.TestCase):
    def test_google_transfer_returns_seed_and_account(self):
        result = parse_uri(transfer_uri())
        self.assertEqual(result.accounts[0].name, 'OpenAI:a@example.com')
        self.assertEqual(result.accounts[0].secret, SECRET)
        self.assertNotIn(SECRET, repr(result))

    def test_version_two_single_qr_without_batch_id_keeps_all_accounts(self):
        names=['OpenAI:first@example.com','OpenAI:second@example.com','OpenAI:third@example.com']
        payload=b''
        for name in names:
            entry=blob(1,KEY)+blob(2,name.encode())+blob(3,b'OpenAI')
            entry+=number(4,1)+number(5,1)+number(6,2)
            payload+=blob(1,entry)
        payload+=number(2,2)+number(3,1)+number(4,0)
        uri='otpauth-migration://offline?data='+quote(base64.b64encode(payload).decode(),safe='')
        transfer=parse_uri(uri)
        self.assertEqual([a.name for a in transfer.accounts],names)
        self.assertTrue(all(a.secret==SECRET for a in transfer.accounts))
        self.assertEqual((transfer.batch_id,transfer.batch_size,transfer.batch_index),(0,1,0))

    def test_version_two_keeps_algorithm_and_batch_validation(self):
        for args in ({'algorithm':2},{'digits':2},{'kind':1},{'batch_index':1}):
            with self.subTest(args=args),self.assertRaises(ImportError):
                parse_uri(transfer_uri(version=2,**args))
        with self.assertRaises(ImportError):
            combine([parse_uri(transfer_uri(version=2,batch_size=2))])

    def test_unknown_transfer_version_is_rejected(self):
        for version in (0,3,99):
            with self.subTest(version=version),self.assertRaises(ImportError):
                parse_uri(transfer_uri(version=version))

    def test_standard_totp_qr(self):
        entry = parse_uri('otpauth://totp/OpenAI%3Aa%40example.com?secret=' + SECRET).accounts[0]
        self.assertEqual(entry.name, 'OpenAI:a@example.com')
        self.assertEqual(entry.secret, SECRET)

    def test_incomplete_multi_qr_export_requires_all_images(self):
        with self.assertRaisesRegex(ImportError, '2'):
            combine([parse_uri(transfer_uri(batch_size=2))])

    def test_multi_qr_order_and_duplicate_image(self):
        a = parse_uri(transfer_uri('a@example.com', batch_size=2, batch_index=0))
        b = parse_uri(transfer_uri('b@example.com', batch_size=2, batch_index=1))
        self.assertEqual([x.name for x in combine([b, a, a])], ['a@example.com', 'b@example.com'])

    def test_unsupported_algorithms_and_hotp_are_not_imported(self):
        for settings in ({'algorithm': 2}, {'digits': 2}, {'kind': 1}, {'secret': b'x'}):
            with self.subTest(settings=settings), self.assertRaises(ImportError):
                parse_uri(transfer_uri(**settings))

    def test_malformed_payload_has_no_material_in_errors(self):
        for raw in ('not-a-uri', 'https://example.com', 'otpauth-migration://offline?data=%ff',
                    'otpauth-migration://offline?data=AAAA&data=AAAA',
                    'otpauth-migration://offline?data=' + quote(base64.b64encode(b'\x0a\xff\x7f').decode())):
            with self.subTest(raw=raw), self.assertRaises(ImportError):
                parse_uri(raw)

    def test_real_image_decoder_reads_generated_transfer_qr(self):
        import zxingcpp
        from PIL import Image
        uri = transfer_uri(version=2)
        bitmap = zxingcpp.create_barcode(uri, zxingcpp.BarcodeFormat.QRCode).to_image(scale=5)
        view = memoryview(bitmap)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.png'
            image = Image.frombytes('L', (view.shape[1], view.shape[0]), bytes(view))
            image.save(path)
            image.close()
            self.assertEqual(read_images([path])[0].secret, SECRET)

    def test_ordinary_qr_is_not_an_authenticator(self):
        import zxingcpp
        from PIL import Image
        bitmap = zxingcpp.create_barcode('https://example.com', zxingcpp.BarcodeFormat.QRCode).to_image(scale=4)
        view = memoryview(bitmap)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ordinary.png'
            image = Image.frombytes('L', (view.shape[1], view.shape[0]), bytes(view))
            image.save(path)
            image.close()
            with self.assertRaises(ImportError):
                read_images([path])
