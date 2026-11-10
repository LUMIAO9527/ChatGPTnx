"""Vector checks for nx.totp against RFC 4226 / RFC 6238.

RFC 4226 Appendix D publishes 6 digit HOTP values for the ASCII key
"12345678901234567890"; RFC 6238 Appendix B publishes 8 digit TOTP values for
the same key. This module emits 6 digits, so the RFC 4226 vectors apply
directly and the RFC 6238 time points are checked by prefix.
"""
import unittest

from nx import totp

# "12345678901234567890" in Base32.
KEY = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
# RFC 6238 uses a longer key for SHA-256 / SHA-512; SHA-1 uses the same key.
SHA1_KEY = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'


class CodeTests(unittest.TestCase):
    def test_rfc4226_vectors_at_30s_steps(self):
        expected = ['755224', '287082', '359152', '969429',
                    '338314', '254676', '287922', '162583',
                    '399871', '520489']
        for counter, want in enumerate(expected):
            with self.subTest(counter=counter):
                self.assertEqual(totp.code(KEY, at=counter * 30), want)

    def test_rfc6238_sha1_prefix(self):
        # 8 digit RFC 6238 values for the SHA-1 column. This module emits 6
        # digits, which are the last six of the 8 digit value: TOTP truncates
        # with a modulus, so the low digits are the ones both sizes share.
        cases = {59: '94287082', 1111111109: '07081804',
                 1111111111: '14050471', 1234567890: '89005924',
                 2000000000: '69279037'}
        for moment, eight in cases.items():
            with self.subTest(moment=moment):
                self.assertEqual(totp.code(SHA1_KEY, at=moment), eight[-6:])

    def test_same_window_is_stable(self):
        # 1000 and 1010 both land in window 33 (990..1019).
        self.assertEqual(totp.code(KEY, at=1000), totp.code(KEY, at=1010))
        self.assertNotEqual(totp.code(KEY, at=1000), totp.code(KEY, at=1030))


class RemainingTests(unittest.TestCase):
    def test_window_bounds(self):
        self.assertEqual(totp.remaining(at=0), 30)
        self.assertEqual(totp.remaining(at=1), 29)
        self.assertEqual(totp.remaining(at=29), 1)
        self.assertEqual(totp.remaining(at=30), 30)


class StableCodeTests(unittest.TestCase):
    def test_refuses_short_window(self):
        self.assertIsNone(totp.code_if_stable(KEY, minimum=8, at=29))
        self.assertEqual(totp.code_if_stable(KEY, minimum=8, at=0),
                         totp.code(KEY, at=0))


class NormalizeTests(unittest.TestCase):
    def test_bare_secret(self):
        self.assertEqual(totp.normalize_secret(' gezd gnbv-gy3t qojq gezdgnbvgy3tqojq '),
                         KEY)

    def test_otpauth_uri(self):
        uri = ('otpauth://totp/OpenAI:me@example.com?secret=' + KEY +
               '&issuer=OpenAI&algorithm=SHA1&digits=6&period=30')
        self.assertEqual(totp.normalize_secret(uri), KEY)

    def test_rejects_other_parameters(self):
        for bad in ('otpauth://totp/x?secret=' + KEY + '&digits=8',
                    'otpauth://totp/x?secret=' + KEY + '&period=60',
                    'otpauth://totp/x?secret=' + KEY + '&algorithm=SHA256'):
            with self.subTest(uri=bad):
                with self.assertRaises(totp.TotpError):
                    totp.normalize_secret(bad)

    def test_rejects_short_or_garbage(self):
        for bad in ('', 'ABC', None, 123, '!!!!!!!!!!!!!!!!!!!!'):
            with self.subTest(value=bad):
                with self.assertRaises(totp.TotpError):
                    totp.normalize_secret(bad)

    def test_never_echoes_secret_in_error(self):
        secret = 'A' * 8
        try:
            totp.normalize_secret(secret)
        except totp.TotpError as error:
            self.assertNotIn(secret, str(error))

    def test_looks_like_secret(self):
        self.assertTrue(totp.looks_like_secret(KEY))
        self.assertTrue(totp.looks_like_secret(KEY.lower()))
        self.assertFalse(totp.looks_like_secret('Passw0rd!'))
        self.assertFalse(totp.looks_like_secret('short'))


if __name__ == '__main__':
    unittest.main()