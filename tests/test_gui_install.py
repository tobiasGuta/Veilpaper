"""Veilpaper GUI Applications-menu installer: user-only, no-overwrite tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO
import contextlib
import os
import json
import hashlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('veilpaper_gui_installer', ROOT / 'scripts/gui_install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class GUIInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-gui-test-')
        self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name) / '.local'
        self.prefix.mkdir()
        self.user = patch.object(installer.os, 'geteuid', return_value=1000)
        self.user.start()
        self.addCleanup(self.user.stop)
        self.app, self.launcher, self.desktop = installer._paths(self.prefix)

    def _install(self):
        with contextlib.redirect_stdout(StringIO()):
            installer.install(self.prefix)

    def test_installer_writes_user_launcher_and_app_menu_entry(self):
        self._install()
        self.assertEqual(installer.check(self.prefix), ('INSTALLED', []))
        self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o755)
        text = self.desktop.read_text()
        self.assertIn('Name=Veilpaper', text)
        self.assertIn('Terminal=false', text)
        self.assertIn('Exec=', text)
        self.assertIn(str(self.launcher), text)
        self.assertIn('gui/veilpaper_gui.py', self.launcher.read_text())
        icon = self.app / installer.ICON_BUNDLE_PATH
        self.assertTrue(icon.is_file())
        self.assertIn(f'Icon={icon}', text)
        self.assertEqual(ET.parse(icon).getroot().tag,
                         '{http://www.w3.org/2000/svg}svg')
        self.assertTrue((self.app / 'veilpaper.py').exists())

    def test_existing_v1_bundle_can_still_be_uninstalled_for_upgrade(self):
        self._install()
        icon = self.app / installer.ICON_BUNDLE_PATH
        icon.unlink()
        icon.parent.rmdir()
        desktop = self.desktop.read_text()
        lines = ['Icon=preferences-desktop-wallpaper' if line.startswith('Icon=')
                 else line for line in desktop.splitlines()]
        self.desktop.write_text('\n'.join(lines) + '\n')
        manifest = self.app / installer.MANIFEST
        record = json.loads(manifest.read_text())
        record['format'] = 1
        del record['files'][installer.ICON_BUNDLE_PATH]
        record['desktop'] = hashlib.sha256(self.desktop.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(record))
        self.assertEqual(installer.check(self.prefix), ('INSTALLED', []))
        with contextlib.redirect_stdout(StringIO()):
            installer.uninstall(self.prefix)
        self.assertEqual(installer.check(self.prefix), ('NOT_INSTALLED', []))

    def test_custom_icon_modification_prevents_uninstall(self):
        self._install()
        icon = self.app / installer.ICON_BUNDLE_PATH
        icon.write_text('changed icon')
        with self.assertRaisesRegex(installer.GUIInstallError, 'INCONSISTENT'):
            installer.uninstall(self.prefix)
        self.assertTrue(self.desktop.exists())

    def test_uninstall_preserves_existing_cli_and_wallpaper(self):
        other_cli = self.prefix / 'bin/veilpaper'
        other_cli.parent.mkdir()
        other_cli.write_text('previous CLI')
        wallpaper = self.prefix / 'share/veilpaper/lock-wallpaper.png'
        wallpaper.parent.mkdir(parents=True)
        wallpaper.write_bytes(b'user image')
        self._install()
        with contextlib.redirect_stdout(StringIO()):
            installer.uninstall(self.prefix)
        self.assertEqual(installer.check(self.prefix), ('NOT_INSTALLED', []))
        self.assertEqual(other_cli.read_text(), 'previous CLI')
        self.assertEqual(wallpaper.read_bytes(), b'user image')

    def test_second_install_is_refused(self):
        self._install()
        with self.assertRaisesRegex(installer.GUIInstallError, 'no overwrite'):
            installer.install(self.prefix)
        self.assertEqual(installer.check(self.prefix), ('INSTALLED', []))

    def test_foreign_desktop_entry_not_overwritten(self):
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text('foreign entry')
        with self.assertRaisesRegex(installer.GUIInstallError, 'no overwrite'):
            installer.install(self.prefix)
        self.assertEqual(self.desktop.read_text(), 'foreign entry')

    def test_existing_gui_launcher_not_overwritten(self):
        self.launcher.parent.mkdir()
        self.launcher.write_text('foreign launcher')
        with self.assertRaisesRegex(installer.GUIInstallError, 'no overwrite'):
            installer.install(self.prefix)
        self.assertEqual(self.launcher.read_text(), 'foreign launcher')

    def test_tampered_source_refuses_uninstall(self):
        self._install()
        (self.app / 'gui/backend.py').write_text('edited')
        with self.assertRaisesRegex(installer.GUIInstallError, 'INCONSISTENT'):
            installer.uninstall(self.prefix)
        self.assertTrue(self.launcher.is_file())
        self.assertTrue(self.desktop.is_file())

    def test_extra_source_refuses_uninstall(self):
        self._install()
        (self.app / 'extra').write_text('do not delete me')
        with self.assertRaisesRegex(installer.GUIInstallError, 'INCONSISTENT'):
            installer.uninstall(self.prefix)
        self.assertTrue((self.app / 'extra').is_file())

    def test_symlinked_bin_directory_is_blocked(self):
        external = Path(self.temp.name) / 'other'
        external.mkdir()
        (self.prefix / 'bin').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(installer.GUIInstallError, 'Unsafe install directory'):
            installer.install(self.prefix)
        self.assertEqual(list(external.iterdir()), [])

    def test_root_install_is_blocked(self):
        with patch.object(installer.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(installer.GUIInstallError, 'never with sudo'):
                installer.install(self.prefix)

    def test_status_before_install(self):
        self.assertEqual(installer.check(self.prefix), ('NOT_INSTALLED', []))


if __name__ == '__main__':
    unittest.main()
