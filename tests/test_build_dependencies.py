"""Build admission rejects missing or older release dependencies."""
from importlib import metadata
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_build_dependencies import mismatches, requirement_lines


class BuildDependencyTests(unittest.TestCase):
    def test_older_crypto_cannot_enter_a_release(self):
        self.assertEqual(mismatches(['cryptography>=50.0.2,<51'], lambda _: '49.0.0'),
                         ['cryptography: found 49.0.0; requires <51,>=50.0.2'])

    def test_supported_version_and_platform_marker(self):
        self.assertEqual(mismatches(['cryptography>=50.0.2,<51',
                                     'unused>=1; python_version < "1"'],
                                    lambda _: '50.0.2'), [])

    def test_missing_dependency_stops_build(self):
        def missing(name):
            raise metadata.PackageNotFoundError(name)
        self.assertTrue(mismatches(['cryptography>=50.0.2'], missing))

    def test_nested_requirements_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime.txt').write_text('cryptography>=50.0.2\n', encoding='utf-8')
            (root / 'dev.txt').write_text('-r runtime.txt\npyinstaller>=6 # build tool\n', encoding='utf-8')
            self.assertEqual(list(requirement_lines(root / 'dev.txt')),
                             ['cryptography>=50.0.2', 'pyinstaller>=6'])
