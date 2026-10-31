"""QMP screenshot helper guardrails; no display, GDM, or system writes."""
from pathlib import Path
import importlib.util
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('veilpaper_qmp_capture',
      ROOT/'scripts/qemu_capture_greeter.py')
capture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='veilpaper-qmp-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_refuses_non_ci(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'false'}):
            with self.assertRaisesRegex(capture.CaptureBlocked, 'GitHub Actions'):
                capture.capture(self.root/'missing.sock', self.root/'screen.png')

    def test_refuses_relative_paths(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}):
            with self.assertRaisesRegex(capture.CaptureBlocked,'absolute'):
                capture.capture(Path('socket'), self.root/'screen.png')

    def test_refuses_missing_socket_without_creating_output(self):
        dest=self.root/'screen.png'
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}):
            with self.assertRaisesRegex(capture.CaptureBlocked,'socket missing'):
                capture.capture(self.root/'absent.sock',dest)
        self.assertFalse(dest.exists())

    def test_refuses_screenshot_overwrite(self):
        target=self.root/'screen.png'
        target.write_bytes(b'original')
        socketpath=self.root/'qmp.sock'
        srv=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.addCleanup(srv.close)
        srv.bind(str(socketpath))
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'true'}):
            with self.assertRaisesRegex(capture.CaptureBlocked,'overwrite'):
                capture.capture(socketpath,target)
        self.assertEqual(target.read_bytes(),b'original')

    def test_cli_rejects_not_ci(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS':'false'}):
            self.assertEqual(capture.main(['--socket',str(self.root/'qmp'),
                                           '--output',str(self.root/'image.png')]),1)


if __name__=='__main__':
    unittest.main()
