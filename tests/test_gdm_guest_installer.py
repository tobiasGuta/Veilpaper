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
