"""GUI backend tests: no GTK or real GNOME session required."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('veilpaper_gui_backend', ROOT / 'gui/backend.py')
backend = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


class GUIBackendTests(unittest.TestCase):
    def test_empty_lock_image(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            self.assertIsNone(backend.lock_image())

    def test_existing_png_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            p = Path(temp) / 'veilpaper'
            p.mkdir()
            image = p / 'lock-wallpaper.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\nPNG')
            self.assertEqual(backend.lock_image(), image)

    def test_lock_symlink_does_not_count(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            directory = Path(temp) / 'veilpaper'
            directory.mkdir()
            target = Path(temp) / 'actual.png'
            target.write_bytes(b'\x89PNG\r\n\x1a\nPNG')
            (directory / 'lock-wallpaper.png').symlink_to(target)
            self.assertIsNone(backend.lock_image())

    def test_set_restore_use_existing_cli(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            source = Path(temp) / 'picture.png'
            source.write_bytes(b'\x89PNG\r\n\x1a\n' + b'fixture-PNG-data')
            with patch('os.geteuid', return_value=1000):
                copied = backend.set_lock(source)
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                backend.restore_lock()
                self.assertIsNone(backend.lock_image())

    def test_extension_active_status(self):
        info = '  Enabled: Yes\n  State: ACTIVE\n'
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gnome-extensions'), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0, stdout=info)):
            self.assertEqual(backend.extension_status(), 'Extension active')

    def test_extension_not_installed(self):
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gnome-extensions'), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=1, stdout='')):
            self.assertIn('not installed', backend.extension_status())

    def test_login_custom_status_detected(self):
        inspector = SimpleNamespace(inspect=lambda: {
            'active_matches_rpm': False, 'backup_matches_rpm': True})
        with patch.object(backend, '_load', return_value=inspector):
            self.assertEqual(backend.login_status()[0], 'Custom login theme detected')

    def test_login_status_no_baseline(self):
        inspector = SimpleNamespace(inspect=lambda: {
            'active_matches_rpm': False, 'backup_matches_rpm': False})
        with patch.object(backend, '_load', return_value=inspector):
            self.assertIn('needs attention', backend.login_status()[0])

    def test_login_preview_identifies_resource_without_writes(self):
        png = b'\x89PNG\r\n\x1a\n' + b'preview image'
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gresource'), \
             patch.object(backend.LOGIN_RESOURCE.__class__, 'is_file', return_value=True), \
             patch.object(backend.LOGIN_RESOURCE.__class__, 'is_symlink', return_value=False), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0, stdout=png)):
            self.assertEqual(backend.login_preview(), (png, 'png'))

    def test_view_state_does_not_modify_system(self):
        with patch.object(backend, 'login_status', return_value=('Custom', 'Verified backup')), \
             patch.object(backend, 'extension_status', return_value='Extension active'), \
             patch.object(backend, 'lock_image', return_value=None):
            snapshot = backend.state()
            self.assertEqual(snapshot.login_label, 'Custom')
            self.assertIsNone(snapshot.lock_image)


if __name__ == '__main__':
    unittest.main()
