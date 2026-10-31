"""Real resource transaction prototype, tested ONLY with temp-package fixtures.

No actual /usr/share/gnome-shell, /etc, or /var/lib writes in unit tests.
Tests run without root privileges; a separately guarded QEMU test exercises
the real root-owned Fedora GDM resource.
"""
import contextlib
from io import StringIO
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_vm_real_transaction', ROOT / 'experiments/gdm/vm_real_transaction.py')
txn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(txn)


class VMRealTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-real-transaction-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.theme = self.root / 'gnome-shell-theme.gresource'
        self.lab = self.root / 'private-lab'
        self.source = self.root / 'candidate.gresource'
        self.old = b'original compiled GNOME theme fixture'
        self.new = b'updated compiled GNOME theme fixture'
        self.theme.write_bytes(self.old)
        self.theme.chmod(0o644)
        self.source.write_bytes(self.new)
        self.mock_theme = patch.object(txn, 'THEME', self.theme)
        self.mock_lab = patch.object(txn, 'LAB', self.lab)
        self.mock_theme.start()
        self.mock_lab.start()
        self.addCleanup(self.mock_theme.stop)
        self.addCleanup(self.mock_lab.stop)

    def _mock_resources(self):
        def review(path, **kwargs):
            return {'verdict': 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW',
                    'active_sha256': txn._sha(self.theme.read_bytes()),
                    'candidate_sha256': txn._sha(self.source.read_bytes()),
                    'added_resource': '/org/gnome/shell/theme/fedora-login-wallpaper.png',
                    'issues': []}
        return SimpleNamespace(review=review)

    @contextlib.contextmanager
    def _fake_root_metadata(self):
        metadata = {'uid': 0, 'gid': 0, 'mode': 0o644, 'xattrs': {}}
        with patch.object(txn, '_metadata', return_value=metadata), \
             patch.object(txn, '_verify_meta'), \
             patch.object(txn.os, 'chown', return_value=None), \
             patch.object(txn, '_load', return_value=self._mock_resources()):
            yield

    def _installed(self):
        with self._fake_root_metadata():
            self.assertEqual(txn.install(self.source), 'VM_REAL_GDM_INSTALLED')

    def test_install_restore_real_atomic_files_on_isolated_path(self):
        self._installed()
        self.assertEqual(self.theme.read_bytes(), self.new)
        self.assertEqual((self.lab / 'original.gresource').read_bytes(), self.old)
        self.assertEqual((self.lab / 'state.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((self.lab / 'state.json').read_text())['phase'], 'installed')
        with self._fake_root_metadata():
            self.assertEqual(txn.restore(), 'VM_REAL_GDM_RESTORED')
        self.assertEqual(self.theme.read_bytes(), self.old)
        self.assertEqual(txn.status(), 'restored: active=original')
        self.assertEqual((self.lab / 'original.gresource').read_bytes(), self.old)

    def test_second_install_is_refused_without_overwriting(self):
        self._installed()
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Existing VM lab transaction'):
                txn.install(self.source)
        self.assertEqual(self.theme.read_bytes(), self.new)

    def test_restore_from_install_prepared_and_swapped_candidate(self):
        self._installed()
        record = json.loads((self.lab / 'state.json').read_text())
        record['phase'] = 'install-prepared'
        txn._write_state(record)
        with self._fake_root_metadata():
            txn.restore()
        self.assertEqual(self.theme.read_bytes(), self.old)

    def test_restore_when_crashed_before_install_swap(self):
        self._installed()
        record = json.loads((self.lab / 'state.json').read_text())
        record['phase'] = 'install-prepared'
        txn._write_state(record)
        self.theme.write_bytes(self.old)
        with self._fake_root_metadata():
            txn.restore()
        self.assertEqual(txn.status(), 'restored: active=original')

    def test_restore_from_restoration_intent_after_swap(self):
        self._installed()
        record = json.loads((self.lab / 'state.json').read_text())
        record['phase'] = 'restore-prepared'
        txn._write_state(record)
        self.theme.write_bytes(self.old)
        with self._fake_root_metadata():
            txn.restore()
        self.assertEqual(txn.status(), 'restored: active=original')

    def test_unrecognized_active_theme_refused(self):
        self._installed()
        self.theme.write_bytes(b'unrelated third party theme')
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Unknown active GDM resource'):
                txn.restore()
        self.assertEqual(self.theme.read_bytes(), b'unrelated third party theme')

    def test_tampered_backup_refuses_restore(self):
        self._installed()
        (self.lab / 'original.gresource').write_bytes(b'tampered')
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Original backup corrupted'):
                txn.restore()
        self.assertEqual(self.theme.read_bytes(), self.new)

    def test_corrupt_journal_blocks(self):
        self._installed()
        (self.lab / 'state.json').write_bytes(b'invalid json')
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Unparseable transaction state'):
                txn.restore()
        self.assertEqual(self.theme.read_bytes(), self.new)

    def test_preexisting_backup_refused(self):
        self.lab.mkdir(mode=0o700)
        (self.lab / 'original.gresource').write_bytes(b'foreign backup')
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Existing VM lab transaction'):
                txn.install(self.source)
        self.assertEqual(self.theme.read_bytes(), self.old)

    def test_symlink_active_theme_is_refused(self):
        dest = self.root / 'original.gresource'
        dest.write_bytes(self.old)
        self.theme.unlink()
        self.theme.symlink_to(dest)
        with self._fake_root_metadata():
            with self.assertRaisesRegex(txn.LabBlocked, 'Theme is a symlink'):
                txn.install(self.source)
        self.assertEqual(dest.read_bytes(), self.old)

    def test_cli_without_vm_authorization_does_not_write(self):
        with patch.object(txn, 'gate') as guard, \
             contextlib.redirect_stderr(StringIO()) as errors:
            code = txn.main(['install', '--candidate', str(self.source), '--confirm', 'yes'])
        self.assertEqual(code, 1)
        self.assertIn('confirmation phrase missing', errors.getvalue())
        guard.assert_not_called()
        self.assertFalse(self.lab.exists())

    def test_root_guard_and_independent_marker_required(self):
        with patch.object(txn, '_load', return_value=SimpleNamespace(guard_vm=lambda: None)), \
             patch.object(txn, '_check_marker', side_effect=txn.LabBlocked('independent marker absent')):
            with self.assertRaisesRegex(txn.LabBlocked, 'independent marker'):
                txn.gate()

    def test_atomic_publication_refuses_symlink(self):
        destination = self.root / 'destination'
        actual = self.root / 'actual'
        actual.write_bytes(b'protect')
        destination.symlink_to(actual)
        with self.assertRaisesRegex(txn.LabBlocked, 'symlink destination'):
            txn._atomic(destination, b'new')
        self.assertEqual(actual.read_bytes(), b'protect')


if __name__ == '__main__':
    unittest.main()
