"""Read-only GDM preflight tests; no host system files are touched."""
import contextlib
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / 'experiments/gdm/preflight.py'
spec = importlib.util.spec_from_file_location('veilpaper_gdm_preflight', PRE)
pre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pre)


class GDMPreflightTests(unittest.TestCase):
    def test_missing_resource_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            data = pre.inspect(directory / 'absent', directory / 'no-state', directory / 'no-backup')
            self.assertTrue(data['issues'])
            self.assertIsNone(data['resource_sha256'])

    def test_stock_shape_is_not_claimed_pristine(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            theme = directory / 'theme.gresource'
            theme.write_bytes(b'pretend compiled resource')
            entries = ''.join(pre.PREFIX + css + '\n' for css in pre.CSS_NAMES).encode()
            css = b'#lockDialogGroup { background-color: #222226; }'
            def tool(*args):
                return (entries if args[1] == 'list' else css), None
            with patch.object(pre.shutil, 'which', return_value='/usr/bin/gresource'), \
                 patch.object(pre, '_run', side_effect=tool):
                data = pre.inspect(theme, directory / 'no-state', directory / 'no-backup')
            self.assertEqual(data['issues'], [])
            self.assertEqual(data['resource_count'], 2)
            self.assertEqual(data['resource_sha256'], pre._sha256(theme))
            with contextlib.redirect_stdout(StringIO()) as output:
                self.assertEqual(pre.show(data), 0)
            self.assertIn('NOT VERIFIED PRISTINE', output.getvalue())
            self.assertEqual(theme.read_bytes(), b'pretend compiled resource')

    def test_existing_customization_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            theme = directory / 'theme.gresource'
            theme.write_bytes(b'previously customized resource')
            state = directory / 'state.json'
            state.write_text('{}')
            entries = ''.join(pre.PREFIX + css + '\n' for css in pre.CSS_NAMES).encode()
            css = b'#lockDialogGroup { background-image: url("resource:///wallpaper.png"); }'
            def tool(*args):
                return (entries if args[1] == 'list' else css), None
            with patch.object(pre.shutil, 'which', return_value='/usr/bin/gresource'), \
                 patch.object(pre, '_run', side_effect=tool):
                data = pre.inspect(theme, state, directory / 'no-backup')
            self.assertTrue(data['modified_state_present'])
            self.assertTrue(any('customized' in note for note in data['notes']))
            self.assertTrue(any('pristine' in note for note in data['notes']))

    def test_unsafe_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            target = directory / 'payload'
            target.write_bytes(b'anything')
            link = directory / 'theme.gresource'
            link.symlink_to(target)
            data = pre.inspect(link, directory / 'missing-state', directory / 'missing-backup')
            self.assertTrue(any('symlink' in issue for issue in data['issues']))
            

if __name__ == '__main__':
    unittest.main()
