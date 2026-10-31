"""RPM baseline checks never modify the machine's theme or backup."""
import contextlib
import hashlib
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'experiments/gdm/rpm_baseline.py'
spec = importlib.util.spec_from_file_location('veilpaper_rpm_baseline', SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class BaselineTests(unittest.TestCase):
    def test_matching_backup_when_active_customized(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            original = b'original package resource data'
            active = folder / 'active.gresource'
            backup = folder / 'original.gresource'
            active.write_bytes(b'customized')
            backup.write_bytes(original)
            record = {'size': len(original), 'digest': hashlib.sha256(original).hexdigest()}
            with patch.object(mod, 'package_record', return_value=(record, None)):
                result = mod.inspect(active, backup)
            self.assertFalse(result['active_matches_rpm'])
            self.assertTrue(result['backup_matches_rpm'])
            self.assertEqual(result['verdict'], 'BACKUP_MATCHES_RPM_DATABASE')
            self.assertEqual(active.read_bytes(), b'customized')
            with contextlib.redirect_stdout(StringIO()) as captured:
                self.assertEqual(mod.show(result), 0)
            self.assertIn('READ-ONLY', captured.getvalue())

    def test_active_matches_without_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            original = b'packaged theme data'
            active = folder / 'theme.gresource'
            active.write_bytes(original)
            record = {'size': len(original), 'digest': hashlib.sha256(original).hexdigest()}
            with patch.object(mod, 'package_record', return_value=(record, None)):
                result = mod.inspect(active, folder / 'no-backup')
            self.assertTrue(result['active_matches_rpm'])
            self.assertEqual(result['verdict'], 'ACTIVE_MATCHES_RPM_DATABASE')

    def test_unknown_package_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            theme = Path(directory) / 'theme.gresource'
            theme.write_bytes(b'data')
            with patch.object(mod, 'package_record', return_value=(None, 'no RPM record')):
                result = mod.inspect(theme, Path(directory) / 'backup')
            self.assertEqual(result['verdict'], 'UNVERIFIED')
            with contextlib.redirect_stdout(StringIO()):
                self.assertEqual(mod.show(result), 1)

    def test_symlink_theme_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'real'
            target.write_bytes(b'data')
            alias = Path(directory) / 'theme'
            alias.symlink_to(target)
            with patch.object(mod, 'package_record') as query:
                result = mod.inspect(alias, Path(directory) / 'backup')
            self.assertTrue(result['issues'])
            query.assert_not_called()

    def test_parser_rejects_non_sha256_rpm_digest(self):
        with patch.object(mod.shutil, 'which', return_value='/usr/bin/rpm'), \
             patch.object(mod.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = str(mod.THEME) + ' 20 1234 0123456789abcdef0123456789abcdef 0100644 root root 0 0 0 X\n'
            run.return_value.stderr = ''
            record, error = mod.package_record(mod.THEME)
            self.assertIsNone(record)
            self.assertIn('not SHA-256', error)

    def test_parser_accepts_exact_path_and_sha256(self):
        digest = 'a' * 64
        with patch.object(mod.shutil, 'which', return_value='/usr/bin/rpm'), \
             patch.object(mod.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = str(mod.THEME) + f' 20 1234 {digest} 0100644 root root 0 0 0 X\n'
            run.return_value.stderr = ''
            record, error = mod.package_record(mod.THEME)
            self.assertIsNone(error)
            self.assertEqual(record, {'digest': digest, 'size': 20})


if __name__ == '__main__':
    unittest.main()
