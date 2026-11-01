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

    def test_blank_or_inactive_display_fails_visible_frame_check(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest('Pillow not installed for pixel validator tests')
        image = Image.new('RGB', (1280, 800), 'black')
        draw = ImageDraw.Draw(image)
        draw.rectangle((515, 392, 745, 396), fill='white')
        path = self.root / 'fake-inactive.png'
        image.save(path)
        with self.assertRaisesRegex(capture.CaptureBlocked, 'blank/inactive'):
            capture._reject_blank_screen(path)

    def test_visible_frame_requires_meaningful_illuminated_display_coverage(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest('Pillow not installed for pixel validator tests')
        image = Image.new('RGB', (1280, 800), 'black')
        draw = ImageDraw.Draw(image)
        draw.rectangle((200, 200, 700, 700), fill=(70, 180, 210))
        path = self.root / 'colored-display.png'
        image.save(path)
        self.assertGreater(capture._reject_blank_screen(path), 0.02)



if __name__=='__main__':
    unittest.main()
