"""Guest-only GDM installer controller: exact-action, no physical host access."""
from io import StringIO
import contextlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_guest_installer_controller',
    ROOT / 'scripts/gdm_guest_installer.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
SHA = 'a' * 64
CONFIRM = controller.CONFIRM
CANDIDATE = Path('/guest/veilpaper/candidate.gresource')


class GuestInstallerTests(unittest.TestCase):
    def test_install_invokes_qualified_engine_with_exact_digest(self):
        order = []
        engine = SimpleNamespace(
            gate=lambda: order.append('gate'),
            install=lambda path, *, expected_candidate_sha256: (
                order.append((path, expected_candidate_sha256)),
                'VM_REAL_GDM_INSTALLED')[1])
        with patch.object(controller, '_engine', return_value=engine):
            result = controller.execute(
                'install', candidate=CANDIDATE, expected_sha256=SHA,
                confirm=CONFIRM)
        self.assertEqual(result, 'VM_REAL_GDM_INSTALLED')
        self.assertEqual(order, ['gate', (CANDIDATE, SHA)])

    def test_restore_invokes_qualified_engine_with_exact_active_sha(self):
        order = []
        engine = SimpleNamespace(
            gate=lambda: order.append('gate'),
            restore=lambda *, expected_active_sha256: (
                order.append(expected_active_sha256),
                'VM_REAL_GDM_RESTORED')[1])
        with patch.object(controller, '_engine', return_value=engine):
            result = controller.execute(
                'restore', expected_sha256=SHA, confirm=CONFIRM)
        self.assertEqual(result, 'VM_REAL_GDM_RESTORED')
        self.assertEqual(order, ['gate', SHA])

    def test_wrong_or_missing_confirmation_blocks_before_loading_engine(self):
        for bad in ('', 'yes', 'I AUTHORIZE HOST GDM WRITES'):
            with self.subTest(bad=bad), patch.object(
                    controller, '_engine', side_effect=AssertionError('must not import')):
                with self.assertRaisesRegex(controller.GuestInstallBlocked, 'authorization'):
                    controller.execute(
                        'install', candidate=CANDIDATE, expected_sha256=SHA,
                        confirm=bad)

    def test_invalid_expected_hash_never_imports_engine(self):
        for bad in ('b'*63, 'X'*64, '', None):
            with self.subTest(bad=bad), patch.object(
                    controller, '_engine', side_effect=AssertionError('must not import')):
                with self.assertRaisesRegex(controller.GuestInstallBlocked, 'SHA-256'):
                    controller.execute(
                        'install', candidate=CANDIDATE, expected_sha256=bad,
                        confirm=CONFIRM)

    def test_action_requires_correct_candidate_shape_before_engine(self):
        with patch.object(controller, '_engine', side_effect=AssertionError('must not import')):
            with self.assertRaisesRegex(controller.GuestInstallBlocked, 'requires'):
                controller.execute('install', expected_sha256=SHA, confirm=CONFIRM)
            with self.assertRaisesRegex(controller.GuestInstallBlocked, 'must not supply'):
                controller.execute(
                    'restore', candidate=CANDIDATE,
                    expected_sha256=SHA, confirm=CONFIRM)
            with self.assertRaisesRegex(controller.GuestInstallBlocked, 'Unsupported'):
                controller.execute('erase', expected_sha256=SHA, confirm=CONFIRM)

    def test_failed_vm_gate_prevents_installer_and_restore(self):
        engine = SimpleNamespace(
            gate=Mock(side_effect=RuntimeError('Not a disposable full VM')),
            install=Mock(), restore=Mock())
        with patch.object(controller, '_engine', return_value=engine):
            with self.assertRaisesRegex(RuntimeError, 'Not a disposable'):
                controller.execute(
                    'install', candidate=CANDIDATE,
                    expected_sha256=SHA, confirm=CONFIRM)
            with self.assertRaisesRegex(RuntimeError, 'Not a disposable'):
                controller.execute(
                    'restore', expected_sha256=SHA, confirm=CONFIRM)
        engine.install.assert_not_called()
        engine.restore.assert_not_called()

    def test_wrong_engine_result_is_blocked(self):
        engine = SimpleNamespace(
            gate=Mock(), install=Mock(return_value='OTHER'),
            restore=Mock(return_value='OTHER'))
        with patch.object(controller, '_engine', return_value=engine):
            with self.assertRaisesRegex(controller.GuestInstallBlocked, 'Unexpected installation'):
                controller.execute('install', candidate=CANDIDATE, expected_sha256=SHA,
                                   confirm=CONFIRM)
            with self.assertRaisesRegex(controller.GuestInstallBlocked, 'Unexpected restore'):
                controller.execute('restore', expected_sha256=SHA, confirm=CONFIRM)

    def test_controller_runs_real_install_and_restore_against_private_fixture(self):
        """Call the existing transaction writer through this controller.

        The only writable paths are in TemporaryDirectory. A mocked gate here
        is a unit-test substitute, never a real VM authorization or release
        acceptance result.
        """
        import tempfile
        import os
        import hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='veilpaper-installer-integration-') as temp:
            root = Path(temp)
            theme = root / 'theme.gresource'
            candidate = root / 'candidate.gresource'
            lab = root / 'lab'
            original = b'private original resource fixture'
            replacement = b'private candidate resource fixture'
            theme.write_bytes(original)
            candidate.write_bytes(replacement)
            theme.chmod(0o644)
            mtime = 1700000000123456789
            os.utime(theme, ns=(mtime, mtime))
            digest = lambda data: hashlib.sha256(data).hexdigest()
            txn = controller._engine()
            meta = {'uid': 0, 'gid': 0, 'mode': 0o644,
                    'mtime_ns': mtime, 'xattrs': {}}

            def review(path, **kwargs):
                self.assertEqual(path, candidate)
                self.assertEqual(kwargs['theme'], theme)
                return {
                    'verdict': 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW',
                    'active_sha256': digest(theme.read_bytes()),
                    'candidate_sha256': digest(candidate.read_bytes()),
                    'added_resource': '/org/gnome/shell/theme/fedora-login-wallpaper.png',
                    'issues': [],
                }
            fake_reviewer = SimpleNamespace(review=review)
            # No live system paths and no VM markers are created.
            with patch.object(controller, '_engine', return_value=txn), \
                 patch.object(txn, 'gate'), \
                 patch.object(txn, 'THEME', theme), \
                 patch.object(txn, 'LAB', lab), \
                 patch.object(txn, '_lab', side_effect=lambda: lab.mkdir(mode=0o700, exist_ok=True)), \
                 patch.object(txn, '_metadata', return_value=meta), \
                 patch.object(txn, '_verify_meta'), \
                 patch.object(txn.os, 'chown', return_value=None), \
                 patch.object(txn, '_load', return_value=fake_reviewer):
                self.assertEqual(controller.execute(
                    'install', candidate=candidate,
                    expected_sha256=digest(replacement),
                    confirm=CONFIRM), 'VM_REAL_GDM_INSTALLED')
                self.assertEqual(theme.read_bytes(), replacement)
                self.assertEqual((lab / 'original.gresource').read_bytes(), original)
                self.assertEqual(controller.execute(
                    'restore', expected_sha256=digest(replacement),
                    confirm=CONFIRM), 'VM_REAL_GDM_RESTORED')
                self.assertEqual(theme.read_bytes(), original)
                self.assertEqual((lab / 'original.gresource').read_bytes(), original)
                self.assertTrue((lab / 'state.json').exists())
                self.assertEqual(theme.stat().st_mtime_ns, mtime)

    def test_cli_bad_auth_returns_failure_without_importing_transaction(self):
        with patch.object(controller, '_engine', side_effect=AssertionError('should not load')), \
             contextlib.redirect_stderr(StringIO()) as err:
            rc = controller.main(
                ['install', '--candidate', str(CANDIDATE),
                 '--sha256', SHA, '--confirm', 'wrong'])
        self.assertEqual(rc, 1)
        self.assertIn('BLOCKED', err.getvalue())


if __name__ == '__main__':
    unittest.main()
