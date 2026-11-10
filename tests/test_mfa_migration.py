"""Checks for nx.mfa_migration: issuing, displaying and confirming a new secret."""
import unittest

from nx import mfa_migration as migration
from nx import totp

KNOWN = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'


class GenerateTests(unittest.TestCase):
    def test_shape(self):
        secret = migration.generate_secret()
        self.assertEqual(len(secret), 32)
        self.assertTrue(all(ch in totp.ALPHABET for ch in secret))
        self.assertNotIn('=', secret)

    def test_distinct(self):
        self.assertNotEqual(migration.generate_secret(), migration.generate_secret())

    def test_usable(self):
        secret = migration.generate_secret()
        self.assertEqual(len(totp.code(secret, at=1000)), 6)


class DisplayTests(unittest.TestCase):
    def test_grouped(self):
        self.assertEqual(migration.format_secret(KNOWN), 'GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ')

    def test_grouped_accepts_spaces_and_case(self):
        self.assertEqual(migration.format_secret(' gezd gnbv gy3t qojq gezd gnbv gy3t qojq '),
                         'GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ')

    def test_mask(self):
        masked = migration.mask_secret(KNOWN)
        self.assertTrue(masked.startswith('GEZD'))
        self.assertTrue(masked.endswith('QOJQ'))
        self.assertNotIn(KNOWN[8:24], masked)

    def test_rejects_bad_group(self):
        with self.assertRaises(totp.TotpError):
            migration.format_secret(KNOWN, group=0)


class VerifyTests(unittest.TestCase):
    def test_accepts_the_same_window(self):
        moment = 1000
        entered = totp.code(KNOWN, at=moment)
        self.assertTrue(migration.verify_entered(KNOWN, entered, at=moment))

    def test_accepts_one_step_either_side(self):
        moment = 1000
        previous = totp.code(KNOWN, at=moment - 30)
        following = totp.code(KNOWN, at=moment + 30)
        self.assertTrue(migration.verify_entered(KNOWN, previous, at=moment))
        self.assertTrue(migration.verify_entered(KNOWN, following, at=moment))

    def test_rejects_two_steps_away(self):
        moment = 1000
        stale = totp.code(KNOWN, at=moment - 90)
        self.assertFalse(migration.verify_entered(KNOWN, stale, at=moment))

    def test_rejects_wrong_shape(self):
        for bad in ('', '12345', '1234567', 'abcdef', None, '12 34 5x'):
            with self.subTest(value=bad):
                self.assertFalse(migration.verify_entered(KNOWN, bad, at=1000))

    def test_tolerates_spaces_in_entry(self):
        moment = 1000
        entered = totp.code(KNOWN, at=moment)
        spaced = f'{entered[:3]} {entered[3:]}'
        self.assertTrue(migration.verify_entered(KNOWN, spaced, at=moment))

    def test_wrong_key_is_rejected(self):
        moment = 1000
        other = migration.generate_secret()
        entered = totp.code(KNOWN, at=moment)
        self.assertFalse(migration.verify_entered(other, entered, at=moment))


class CurrentCodeTests(unittest.TestCase):
    def test_returns_code_and_remaining(self):
        code, remaining = migration.current_code(KNOWN, at=1000)
        self.assertEqual(len(code), 6)
        self.assertTrue(1 <= remaining <= 30)


if __name__ == '__main__':
    unittest.main()