"""Read-only portable GDM install-review fixture tests."""
import contextlib
from io import StringIO
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_install_review', ROOT / 'experiments/gdm/install_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class InstallReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-install-review-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.theme = self.folder / 'active.gresource'
        self.backup = self.folder / 'original.gresource'
        self.candidate = self.folder / 'candidate.gresource'
        self.state = self.folder / 'manager-state.json'
        self.stock = b'RPM theme archive fixture'
        self.candidate_bytes = b'Veilpaper candidate fixture'
        self.theme.write_bytes(self.stock)
        self.candidate.write_bytes(self.candidate_bytes)
        self.record = {
            'digest': hashlib.sha256(self.stock).hexdigest(),
            'size': len(self.stock),
        }
        self.prefix = review.gdm.PREFIX
        self.asset = self.prefix + 'fedora-login-wallpaper.png'
        self.baseline = {
            self.prefix + 'gnome-shell-light.css': b'#lockDialogGroup { background-color: #222226; }',
            self.prefix + 'gnome-shell-dark.css': b'#lockDialogGroup { background-color: #222226; }',
            self.prefix + 'pad-osd.css': b'untouched-original',
        }
        self.updated = dict(self.baseline)
        for name in (self.prefix + 'gnome-shell-light.css', self.prefix + 'gnome-shell-dark.css'):
            self.updated[name] = review.gdm.patch_css(
                self.baseline[name].decode(), self.asset).encode()
        self.updated[self.asset] = b'\x89PNG\r\n\x1a\n' + b'fixture-image'

    def run_review(self):
        def resources(path):
            if Path(path) == self.theme:
                return sorted(self.baseline)
            if Path(path) == self.candidate:
                return sorted(self.updated)
            raise AssertionError(f'Unexpected resource path: {path}')
        def extract(path, resource):
            return (self.baseline if Path(path) == self.theme else self.updated)[resource]
        with patch.object(review.rpm, 'package_record',
                          return_value=(self.record, None)), \
             patch.object(review.gdm, 'resources', side_effect=resources), \
             patch.object(review.gdm, 'extract', side_effect=extract):
            return review.review(self.candidate, theme=self.theme,
                                 backup=self.backup, state=self.state)

    def test_first_time_clean_theme_qualified_for_review_only(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        report = self.run_review()
        self.assertEqual(report['verdict'], 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW')
        self.assertEqual(report['added_resource'], self.asset)
        self.assertEqual(report['preserved_entries'], 3)
        with contextlib.redirect_stdout(StringIO()) as output:
            self.assertEqual(review.show(report), 0)
        self.assertIn('NO INSTALL AUTHORIZATION', output.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_existing_manager_state_blocks_without_writes(self):
        self.state.write_text('{}')
        report = self.run_review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('Existing manager state' in x for x in report['issues']))
        self.assertEqual(self.state.read_text(), '{}')

    def test_active_theme_customization_is_blocked(self):
        self.theme.write_bytes(b'custom theme')
        self.backup.write_bytes(self.stock)
        report = self.run_review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('differs from installed RPM' in x for x in report['issues']))
        self.assertEqual(self.theme.read_bytes(), b'custom theme')

    def test_untrusted_existing_backup_is_not_replaced(self):
        self.backup.write_bytes(b'other tool backup')
        report = self.run_review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('Existing backup' in x for x in report['issues']))
        self.assertEqual(self.backup.read_bytes(), b'other tool backup')

    def test_unrelated_resource_mutation_rejected(self):
        self.updated[self.prefix + 'pad-osd.css'] = b'tampered'
        result = self.run_review()
        self.assertEqual(result['verdict'], 'BLOCKED')
        self.assertTrue(any('Unrelated packaged resource' in x for x in result['issues']))

    def test_css_mutation_rejected(self):
        self.updated[self.prefix + 'gnome-shell-dark.css'] += b'\n/* unwanted */'
        result = self.run_review()
        self.assertEqual(result['verdict'], 'BLOCKED')
        self.assertTrue(any('Unexpected CSS modification' in x for x in result['issues']))

    def test_mislabeled_image_bytes_rejected(self):
        self.updated[self.asset] = b'RIFFxxxxxxxxWEBPimage'
        result = self.run_review()
        self.assertEqual(result['verdict'], 'BLOCKED')
        self.assertTrue(any('PNG bytes' in x for x in result['issues']))

    def test_additional_resource_rejected(self):
        self.updated[self.prefix + 'unrecognized.txt'] = b'extra'
        result = self.run_review()
        self.assertEqual(result['verdict'], 'BLOCKED')
        self.assertTrue(any('one image' in x for x in result['issues']))

    def test_candidate_symlink_rejected(self):
        self.candidate.unlink()
        self.candidate.symlink_to(self.theme)
        result = self.run_review()
        self.assertEqual(result['verdict'], 'BLOCKED')
        self.assertTrue(any('non-symlink' in x for x in result['issues']))

    def test_missing_rpm_record_rejected(self):
        with patch.object(review.rpm, 'package_record',
                          return_value=(None, 'record not found')):
            report = review.review(self.candidate, theme=self.theme,
                                   backup=self.backup, state=self.state)
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('record not found' in x for x in report['issues']))
        with contextlib.redirect_stdout(StringIO()):
            self.assertEqual(review.show(report), 1)

    def test_no_matching_candidate_bytes_rejected(self):
        self.candidate.write_bytes(self.stock)
        report = self.run_review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('identical to the active' in x for x in report['issues']))


if __name__ == '__main__':
    unittest.main()
