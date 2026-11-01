"""VM-only Polkit GUI bridge tests: no host GDM writes or root Python imports."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_vm_install_bridge_tests', ROOT / 'gui/vm_install_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

CANDIDATE = SimpleNamespace(
    path=Path('/home/veiltest/.cache/veilpaper/login-candidates/prepared-test123/candidate.gresource'),
    digest='a' * 64)


class GuestInstallBridgeTests(unittest.TestCase):
    def test_real_host_preflight_fails_closed_before_policy(self):
        with patch.object(bridge.os, 'geteuid', return_value=0), \
             patch.object(bridge, '_policy_matches') as policy:
            allowed, reason = bridge.guest_install_availability()
        self.assertFalse(allowed)
        self.assertIn('as root', reason)
        policy.assert_not_called()

    def test_preflight_rejects_non_vm_or_container(self):
        with tempfile.TemporaryDirectory() as name:
            release = Path(name) / 'fedora-release'
            release.write_text('Fedora release 44 (Forty Four)\n')
            for codes in ((1, 1), (0, 0)):
                responses = [SimpleNamespace(returncode=c) for c in codes]
                with self.subTest(codes=codes), \
                     patch.object(bridge, 'RELEASE', release), \
                     patch.object(bridge.os, 'geteuid', return_value=1000), \
                     patch.object(bridge.subprocess, 'run', side_effect=responses), \
                     patch.object(bridge, '_root_owned_file', return_value=True), \
                     patch.object(bridge, '_root_owned_directory', return_value=True), \
                     patch.object(bridge, '_policy_matches', return_value=True):
                    allowed, reason = bridge.guest_install_availability()
                self.assertFalse(allowed)
                self.assertIn('full, non-container', reason)

    def test_preflight_requires_root_owned_markers_and_bundle(self):
        with tempfile.TemporaryDirectory() as name:
            release = Path(name) / 'fedora-release'
            release.write_text('Fedora release 44 (Forty Four)\n')
            responses = [SimpleNamespace(returncode=c) for c in (0, 1)]
            with patch.object(bridge, 'RELEASE', release), \
                 patch.object(bridge.os, 'geteuid', return_value=1000), \
                 patch.object(bridge.subprocess, 'run', side_effect=responses), \
                 patch.object(bridge, '_root_owned_file', return_value=False):
                allowed, reason = bridge.guest_install_availability()
            self.assertFalse(allowed)
            self.assertIn('markers', reason)

    def test_preflight_can_pass_only_for_full_vm_with_complete_trusted_install(self):
        with tempfile.TemporaryDirectory() as name:
            release = Path(name) / 'fedora-release'
            release.write_text('Fedora release 44 (Forty Four)\n')
            responses = [SimpleNamespace(returncode=c) for c in (0, 1)]
            with patch.object(bridge, 'RELEASE', release), \
                 patch.object(bridge.os, 'geteuid', return_value=1000), \
                 patch.object(bridge.subprocess, 'run', side_effect=responses), \
                 patch.object(bridge, '_root_owned_file', return_value=True), \
                 patch.object(bridge, '_root_owned_directory', return_value=True), \
                 patch.object(bridge, '_policy_matches', return_value=True):
                allowed, reason = bridge.guest_install_availability()
            self.assertTrue(allowed, reason)

    def test_fixed_root_owned_helper_and_exact_digest_are_passed_directly_to_pkexec(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0,
                                   stdout='VM_REAL_GDM_INSTALLED\nDISPOSABLE VM ONLY\n',
                                   stderr='')
        with patch.object(bridge, 'guest_install_availability',
                          return_value=(True, 'VM markers and helper')):
            outcome = bridge.install_candidate_in_guest(CANDIDATE, runner=runner)
        self.assertIn('disposable Fedora VM', outcome)
        args, kw = calls[0]
        self.assertEqual(args[:2], [str(bridge.PKEXEC), str(bridge.HELPER)])
        self.assertIn(str(CANDIDATE.path), args)
        self.assertIn(CANDIDATE.digest, args)
        self.assertNotIn('shell', kw)
        self.assertTrue(kw['capture_output'])
        self.assertNotIn('gui/veilpaper_gui.py', ' '.join(args))

    def test_host_or_missing_helper_denies_before_running_pkexec(self):
        run = Mock()
        with patch.object(bridge, 'guest_install_availability',
                          return_value=(False, 'not a VM')):
            with self.assertRaisesRegex(bridge.VMInstallUnavailable, 'not a VM'):
                bridge.install_candidate_in_guest(CANDIDATE, runner=run)
        run.assert_not_called()

    def test_malformed_candidate_hash_denied_before_vm_detection(self):
        bad = SimpleNamespace(path=CANDIDATE.path, digest='x' * 64)
        with patch.object(bridge, 'guest_install_availability') as gate:
            with self.assertRaisesRegex(bridge.VMInstallUnavailable, 'SHA-256'):
                bridge.install_candidate_in_guest(bad)
        gate.assert_not_called()

    def test_pkexec_denied_is_not_reported_as_install(self):
        with patch.object(bridge, 'guest_install_availability',
                          return_value=(True, 'VM available')):
            with self.assertRaisesRegex(bridge.VMInstallUnavailable, 'not report'):
                bridge.install_candidate_in_guest(CANDIDATE, runner=lambda *a, **kw:
                    SimpleNamespace(returncode=126, stdout='', stderr='authorization failed'))

    def test_wrong_success_output_denied_even_with_zero_exit(self):
        with patch.object(bridge, 'guest_install_availability',
                          return_value=(True, 'VM available')):
            with self.assertRaisesRegex(bridge.VMInstallUnavailable, 'not report'):
                bridge.install_candidate_in_guest(CANDIDATE, runner=lambda *a, **kw:
                    SimpleNamespace(returncode=0, stdout='incomplete', stderr=''))

    def test_trusted_policy_must_bind_exact_exec_path_and_admin_action(self):
        with tempfile.TemporaryDirectory() as name:
            policy = Path(name) / 'policy'
            policy.write_text(
                '<policyconfig><action id="me.tobiasguta.Veilpaper.Guest">'
                '<defaults><allow_active>auth_admin</allow_active></defaults>'
                '<annotate key="org.freedesktop.policykit.exec.path">'
                + str(bridge.HELPER) + '</annotate></action></policyconfig>')
            with patch.object(bridge, 'POLICY', policy), \
                 patch.object(bridge, '_root_owned_file', return_value=True):
                self.assertTrue(bridge._policy_matches())
                policy.write_text(policy.read_text().replace(str(bridge.HELPER), '/tmp/untrusted'))
                self.assertFalse(bridge._policy_matches())

    def test_symlink_and_group_writable_root_helper_refused(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            target = base / 'target'
            target.write_text('#!/usr/bin/python3')
            target.chmod(0o777)
            alias = base / 'alias'
            alias.symlink_to(target)
            self.assertFalse(bridge._root_owned_file(alias))
            self.assertFalse(bridge._root_owned_file(target, executable=True))


if __name__ == '__main__':
    unittest.main()
