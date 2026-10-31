import contextlib
from pathlib import Path
import io
import os
import tempfile
import unittest
from unittest.mock import patch
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('veilpaper', ROOT / 'veilpaper.py')
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)


class LockCLITests(unittest.TestCase):
    def test_lock_set_and_restore_never_touch_login(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}), patch.object(vp.os, 'geteuid', return_value=1000):
            image = Path(temp) / 'source.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'abc123xyz')
            with contextlib.redirect_stdout(io.StringIO()):
                vp.set_lock(image)
            target = Path(temp) / 'veilpaper/lock-wallpaper.png'
            self.assertEqual(target.read_bytes(), image.read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with contextlib.redirect_stdout(io.StringIO()):
                vp.restore_lock()
            self.assertFalse(target.exists())

    def test_wrong_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(vp.os, 'geteuid', return_value=1000):
            image = Path(temp) / 'fake.png'
            image.write_text('not a png')
            with self.assertRaises(RuntimeError):
                vp.set_lock(image)

    def test_non_png_image_is_converted_to_actual_png(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}), patch.object(vp.os, 'geteuid', return_value=1000):
            source = Path(temp) / 'mislabelled.png'
            source.write_bytes(b'RIFFxxxxWEBP' + b'fake-webp-data')
            def fake_convert(src, dst):
                self.assertEqual(src, source)
                dst.write_bytes(b'\x89PNG\r\n\x1a\n' + b'converted-data')
            with patch.object(vp, 'convert_to_png', side_effect=fake_convert) as convert, contextlib.redirect_stdout(io.StringIO()):
                vp.set_lock(source)
            self.assertEqual(convert.call_count, 1)
            target = Path(temp) / 'veilpaper/lock-wallpaper.png'
            self.assertTrue(target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_failed_conversion_preserves_existing_image(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}), patch.object(vp.os, 'geteuid', return_value=1000):
            data_dir = Path(temp) / 'veilpaper'
            data_dir.mkdir()
            old = data_dir / 'lock-wallpaper.png'
            old.write_bytes(b'\x89PNG\r\n\x1a\nold-wallpaper')
            source = Path(temp) / 'source.webp'
            source.write_bytes(b'RIFFxxxxWEBP' + b'fake-webp-data')
            with patch.object(vp, 'convert_to_png', side_effect=RuntimeError('decoder unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'decoder unavailable'):
                    vp.set_lock(source)
            self.assertEqual(old.read_bytes(), b'\x89PNG\r\n\x1a\nold-wallpaper')
            self.assertEqual(set(p.name for p in data_dir.iterdir()), {'lock-wallpaper.png'})

    def test_root_rejected_for_lock_set(self):
        with patch.object(vp.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'not with sudo'):
                vp.set_lock(Path('any.png'))

    def test_login_preflight_dispatch_does_not_load_writer(self):
        with patch.object(vp, 'preflight_login', return_value=0) as scan, \
             patch.object(vp, 'gdm', side_effect=AssertionError('must not load writer')):
            self.assertEqual(vp.main(['login', 'preflight']), 0)
            scan.assert_called_once_with()

    def test_expected_cli_groups(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as err:
                vp.main(['login', '--help'])
        self.assertEqual(err.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
