"""Portable builder tests operate on disposable fixture files, never on /usr/share."""
import contextlib
from io import StringIO
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'experiments/gdm/portable_build.py'
spec = importlib.util.spec_from_file_location('veilpaper_portable_build', SRC)
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class PortableBuildTests(unittest.TestCase):
    def fixture(self, directory, *, customized=True, backup=True):
        directory = Path(directory)
        original = b'pristine rpm theme bytes'
        theme = directory / 'gnome-shell-theme.gresource'
        theme.write_bytes(b'customized theme' if customized else original)
        save = directory / 'original.gresource'
        if backup:
            save.write_bytes(original)
        record = {'digest': hashlib.sha256(original).hexdigest(), 'size': len(original)}
        return theme, save, record

    def test_customized_theme_prefers_rpm_matching_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            theme, backup, record = self.fixture(directory)
            with patch.object(portable.rpm, 'package_record', return_value=(record, None)):
                self.assertEqual(portable.select_baseline(theme, backup), (backup, record['digest']))

    def test_stock_theme_works_without_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            theme, backup, record = self.fixture(directory, customized=False, backup=False)
            with patch.object(portable.rpm, 'package_record', return_value=(record, None)):
                self.assertEqual(portable.select_baseline(theme, backup), (theme, record['digest']))

    def test_unverified_theme_and_backup_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            theme, backup, record = self.fixture(directory)
            backup.write_bytes(b'not from rpm')
            with patch.object(portable.rpm, 'package_record', return_value=(record, None)):
                with self.assertRaisesRegex(RuntimeError, 'Neither'):
                    portable.select_baseline(theme, backup)

    def test_symlink_backup_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            theme, backup, record = self.fixture(directory, backup=False)
            backup.symlink_to(theme)
            with patch.object(portable.rpm, 'package_record', return_value=(record, None)):
                with self.assertRaisesRegex(RuntimeError, 'symlink'):
                    portable.select_baseline(theme, backup)

    def test_no_rpm_record_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            theme, backup, _ = self.fixture(directory)
            with patch.object(portable.rpm, 'package_record', return_value=(None, 'missing')):
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    portable.select_baseline(theme, backup)

    def test_build_preserves_all_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            theme, backup, record = self.fixture(directory)
            original_theme = theme.read_bytes()
            original_backup = backup.read_bytes()
            image = directory / 'image.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'image-pixels')
            output = directory / 'candidate.gresource'
            prefix = portable.gdm.PREFIX
            css_names = [prefix + name for name in portable.gdm.CSS_NAMES]
            original_names = css_names + [prefix + 'pad-osd.css']
            asset = prefix + 'fedora-login-wallpaper.png'
            original_parts = {n: b'#lockDialogGroup { background-color: #222226; }'
                              for n in css_names}
            original_parts[prefix + 'pad-osd.css'] = b'unchanged'
            compiled_parts = {}

            def resources(path):
                return original_names if Path(path) == backup else original_names + [asset]

            def extract(path, name):
                if Path(path) == backup:
                    return original_parts[name]
                return compiled_parts[str(path)][name]

            def compile_fixture(*args):
                manifest = Path(args[1])
                dest = Path(args[args.index('--target') + 1])
                tree = ET.parse(manifest)
                names = [n.text for n in tree.findall('.//file')]
                compiled_parts[str(dest)] = {('/' + n): (manifest.parent / n).read_bytes()
                                              for n in names}
                dest.write_bytes(b'fake compiled resource')
                return ''

            with patch.object(portable.rpm, 'package_record', return_value=(record, None)), \
                 patch.object(portable.gdm, 'resources', side_effect=resources), \
                 patch.object(portable.gdm, 'extract', side_effect=extract), \
                 patch.object(portable.gdm, 'run', side_effect=compile_fixture), \
                 contextlib.redirect_stdout(StringIO()) as captured:
                portable.build(image, output, theme=theme, backup=backup)
            self.assertEqual(output.read_bytes(), b'fake compiled resource')
            self.assertEqual(theme.read_bytes(), original_theme)
            self.assertEqual(backup.read_bytes(), original_backup)
            self.assertIn('BUILD ONLY', captured.getvalue())

    def test_no_clobber_existing_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            theme, backup, record = self.fixture(directory)
            image = directory / 'image.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'example-pixels')
            output = directory / 'existing.gresource'
            output.write_bytes(b'keep')
            with patch.object(portable.rpm, 'package_record', return_value=(record, None)):
                with self.assertRaisesRegex(RuntimeError, 'already exists'):
                    portable.build(image, output, theme=theme, backup=backup)
            self.assertEqual(output.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
