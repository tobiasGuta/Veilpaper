"""User-only Veilpaper CLI installation tests in temporary home prefixes."""
import contextlib
from io import StringIO
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
script = SOURCE / 'scripts/user_install.py'
spec = importlib.util.spec_from_file_location('veilpaper_user_install', script)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class UserInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-installer-test-')
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / 'user' / '.local'
        self.prefix.mkdir(parents=True)
        self.fake_user = patch.object(installer.os, 'geteuid', return_value=1000)
        self.fake_user.start()
        self.addCleanup(self.fake_user.stop)
        self.app, self.launcher = installer._paths(self.prefix)

    def installed(self):
        with contextlib.redirect_stdout(StringIO()):
            installer.install(self.prefix)

    def test_install_status_and_real_launcher_help(self):
        self.installed()
        self.assertEqual(installer.inspect(self.prefix), ('INSTALLED', []))
        self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o755)
        result = subprocess.run([str(self.launcher), '--help'],
            capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('lock', result.stdout)
        self.assertIn('login', result.stdout)

    def test_uninstall_preserves_wallpaper_files(self):
        data = self.prefix / 'share/veilpaper'
        data.mkdir(parents=True)
        wallpaper = data / 'lock-wallpaper.png'
        wallpaper.write_bytes(b'\x89PNG\r\n\x1a\nuser wallpaper')
        self.installed()
        with contextlib.redirect_stdout(StringIO()):
            installer.uninstall(self.prefix)
        self.assertEqual(installer.inspect(self.prefix), ('NOT_INSTALLED', []))
        self.assertEqual(wallpaper.read_bytes(), b'\x89PNG\r\n\x1a\nuser wallpaper')
        self.assertFalse(self.launcher.exists())

    def test_existing_launcher_is_never_overwritten(self):
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('custom user command')
        with self.assertRaisesRegex(installer.InstallError, 'already exists'):
            installer.install(self.prefix)
        self.assertEqual(self.launcher.read_text(), 'custom user command')

    def test_existing_app_dir_is_never_overwritten(self):
        self.app.mkdir(parents=True)
        marker = self.app / 'leave-me-alone'
        marker.write_text('custom source')
        with self.assertRaisesRegex(installer.InstallError, 'already exists'):
            installer.install(self.prefix)
        self.assertEqual(marker.read_text(), 'custom source')

    def test_modified_install_is_not_uninstalled(self):
        self.installed()
        target = self.app / 'veilpaper.py'
        target.write_text('# changed after installation')
        with self.assertRaisesRegex(installer.InstallError, 'INCONSISTENT'):
            installer.uninstall(self.prefix)
        self.assertTrue(target.exists())
        self.assertTrue(self.launcher.exists())

    def test_extra_file_does_not_get_deleted(self):
        self.installed()
        unknown = self.app / 'extra-file.txt'
        unknown.write_text('user data')
        with self.assertRaisesRegex(installer.InstallError, 'Unexpected file'):
            installer.uninstall(self.prefix)
        self.assertEqual(unknown.read_text(), 'user data')
        self.assertTrue(self.launcher.exists())

    def test_symlink_launcher_is_not_accepted(self):
        self.installed()
        self.launcher.unlink()
        self.launcher.symlink_to(self.app / 'veilpaper.py')
        self.assertEqual(installer.inspect(self.prefix)[0], 'INCONSISTENT')
        with self.assertRaisesRegex(installer.InstallError, 'INCONSISTENT'):
            installer.uninstall(self.prefix)

    def test_symlink_bin_directory_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.prefix / 'bin').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, 'symlink directory'):
            installer.install(self.prefix)
        self.assertEqual(list(outside.iterdir()), [])

    def test_root_cannot_install(self):
        with patch.object(installer.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(installer.InstallError, 'Never run'):
                installer.install(self.prefix)

    def test_no_install_reported(self):
        self.assertEqual(installer.inspect(self.prefix), ('NOT_INSTALLED', []))


if __name__ == '__main__':
    unittest.main()
