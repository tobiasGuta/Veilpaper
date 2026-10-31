"""VM-only GDM qualification gate tests; no host GDM writes."""
import contextlib
import hashlib
import importlib.util
from io import StringIO
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_vm_gate', REPO / 'experiments/gdm/vm_gate.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


class VMGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-vm-gate-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.release = self.folder / 'fedora-release'
        self.release.write_text('Fedora release 44 (Forty Four)\n')
        self.marker = self.folder / 'marker'
        self.marker.write_bytes(vm.MARKER_BYTES)
        self.marker.chmod(0o600)

    def _gate(self, vm_code=0, container_code=1, root_uid=0):
        def command(*args):
            return vm_code if '--vm' in args else container_code
        return patch.object(vm, '_run', side_effect=command), \
               patch.object(vm.os, 'geteuid', return_value=root_uid)

    def test_full_vm_with_valid_marker_passes_identity_gate(self):
        a, b = self._gate()
        with a, b, patch.object(vm, 'MARKER', self.marker):
            vm.guard_vm(marker=self.marker, release=self.release)

    def test_rootless_vm_rejected(self):
        a, b = self._gate(root_uid=1000)
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'root'):
                vm.guard_vm(marker=self.marker, release=self.release)

    def test_host_rejected(self):
        a, b = self._gate(vm_code=1)
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'Full hardware VM'):
                vm.guard_vm(marker=self.marker, release=self.release)

    def test_container_rejected_even_with_virtualization_detected(self):
        a, b = self._gate(vm_code=0, container_code=0)
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'Container'):
                vm.guard_vm(marker=self.marker, release=self.release)

    def test_bad_marker_rejected(self):
        self.marker.write_text('an arbitrary marker')
        a, b = self._gate()
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'invalid content'):
                vm.guard_vm(marker=self.marker, release=self.release)

    def test_symlink_marker_rejected(self):
        link = self.folder / 'alias'
        link.symlink_to(self.marker)
        a, b = self._gate()
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'root-owned'):
                vm.guard_vm(marker=link, release=self.release)

    def test_bad_release_rejected(self):
        self.release.write_text('Fedora release 43\n')
        a, b = self._gate()
        with a, b:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'Fedora 44'):
                vm.guard_vm(marker=self.marker, release=self.release)

    def test_qualification_rejects_existing_state_before_review(self):
        candidate = self.folder / 'candidate.gresource'
        candidate.write_bytes(b'fixture candidate')
        state = self.folder / 'manager-state'
        state.write_text('{}')
        with patch.object(vm, 'STATE', state), patch.object(vm, 'BACKUP', self.folder / 'missing'), \
             patch.object(vm, '_load') as loader:
            with self.assertRaisesRegex(vm.QualificationBlocked, 'Backup or manager state'):
                vm.qualification(candidate)
        loader.assert_not_called()

    def test_qualification_normal_cycle_keeps_everything_unchanged(self):
        stock = self.folder / 'stock.gresource'
        stock.write_bytes(b'real stock bytes')
        candidate = self.folder / 'candidate.gresource'
        candidate.write_bytes(b'compiled resource bytes')
        initial = {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        installed = SimpleNamespace(review=lambda *args, **kw: {
            'verdict': 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW',
            'added_resource': '/org/gnome/shell/theme/fedora-login-wallpaper.png',
            'issues': [],
        })
        cases = ['normal-install-and-restore', 'recover-install-intent',
                 'recover-install-swap', 'recover-restore-intent',
                 'recover-restore-swap']
        simulator = SimpleNamespace(simulate=lambda base, image: cases)
        def helper(name, file):
            if file == 'install_review.py':
                return installed
            if file == 'fixture_transaction.py':
                return simulator
            raise AssertionError(file)
        with patch.object(vm, 'THEME', stock), \
             patch.object(vm, 'STATE', self.folder / 'absent-state'), \
             patch.object(vm, 'BACKUP', self.folder / 'absent-backup'), \
             patch.object(vm, '_load', side_effect=helper):
            result = vm.qualification(candidate)
        self.assertEqual(result['verdict'], 'VM_READ_ONLY_ADMISSION_PASS')
        self.assertFalse(result['install_performed'])
        self.assertEqual(result['recovery_scenarios'], cases)
        self.assertEqual(initial, {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()})

    def test_install_review_block_is_not_overridden(self):
        candidate = self.folder / 'candidate.gresource'
        candidate.write_bytes(b'fixture candidate')
        stock = self.folder / 'stock.gresource'
        stock.write_bytes(b'original')
        reviewer = SimpleNamespace(review=lambda *args, **kw: {
            'verdict': 'BLOCKED', 'issues': ['unexpected GDM modifications']
        })
        with patch.object(vm, 'THEME', stock), patch.object(vm, 'BACKUP', self.folder / 'missing-b'), \
             patch.object(vm, 'STATE', self.folder / 'missing-s'), patch.object(vm, '_load', return_value=reviewer):
            with self.assertRaisesRegex(vm.QualificationBlocked, 'unexpected GDM'):
                vm.qualification(candidate)

    def test_cli_denies_without_vm_proof(self):
        with patch.object(vm, 'guard_vm', side_effect=vm.QualificationBlocked('Not a VM')), \
             patch.object(vm, 'qualification') as qualify, \
             contextlib.redirect_stderr(StringIO()) as error:
            code = vm.main(['--candidate', str(self.folder / 'candidate'),
                            '--confirm', 'DISPOSABLE FEDORA 44 VM'])
        self.assertEqual(code, 1)
        self.assertIn('Not a VM', error.getvalue())
        qualify.assert_not_called()

    def test_cli_requires_exact_confirm_phrase(self):
        with patch.object(vm, 'guard_vm') as gate, \
             contextlib.redirect_stderr(StringIO()) as error:
            code = vm.main(['--candidate', 'unused', '--confirm', 'yes'])
        self.assertEqual(code, 1)
        self.assertIn('phrase does not match', error.getvalue())
        gate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
