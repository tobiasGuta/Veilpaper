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

    def test_root_rejected_for_lock_set(self):
        with patch.object(vp.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'not with sudo'):
                vp.set_lock(Path('any.png'))

    def test_expected_cli_groups(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as err:
                vp.main(['login', '--help'])
        self.assertEqual(err.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
