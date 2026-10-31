"""Static contract tests for the Fedora full-VM read-only harness.

These guardrails complement, not replace, a real QEMU guest run.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/fedora44_qemu_vm_check.sh'
WORKFLOW = ROOT / '.github/workflows/fedora44-qemu-vm.yml'


class QEMUHarnessContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text()
        cls.workflow = WORKFLOW.read_text()

    def test_host_only_github_ephemeral_runner_and_full_qemu_vm(self):
        self.assertIn('GITHUB_ACTIONS', self.script)
        self.assertIn('RUNNER_TEMP', self.script)
        self.assertIn('RUNNER_OS', self.script)
        self.assertIn('/dev/kvm', self.script)
        self.assertIn('accel=kvm', self.script)
        self.assertIn('accel=tcg', self.script)
        self.assertIn('-machine "accel=$accel"', self.script)
        self.assertIn('qemu-system-x86_64', self.script)
        self.assertNotIn('docker run', self.script)

    def test_pinned_official_fedora_cloud_image(self):
        self.assertIn('Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2', self.script)
        self.assertIn('28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f', self.script)
        self.assertIn('sha256sum -c -', self.script)

    def test_no_host_gdm_mount_or_host_install_commands(self):
        self.assertNotIn('mount --bind', self.script)
        self.assertNotIn('virtiofs', self.script)
        self.assertNotIn('9p,', self.script)
        self.assertNotIn('systemctl restart gdm', self.script)
        self.assertNotIn('sudo python3 experiments/gdm/fedora_wallpaper_manager_v02.py', self.script)
        self.assertIn('overlay.qcow2', self.script)
        self.assertIn('trap cleanup EXIT', self.script)

    def test_guest_denies_missing_marker_then_requires_explicit_marker(self):
        self.assertIn('PASS: markerless guest correctly refused', self.script)
        self.assertIn('DISPOSABLE FEDORA 44 VM', self.script)
        self.assertIn('chmod 0600 /etc/veilpaper-disposable-vm-qualification', self.script)
        self.assertIn('vm_gate.py', self.script)
        self.assertIn('sudo rpm -V gnome-shell', self.script)

    def test_ci_uses_standard_runner_and_read_only_permissions(self):
        self.assertIn('runs-on: ubuntu-24.04', self.workflow)
        self.assertIn('timeout-minutes: 35', self.workflow)
        self.assertIn('contents: read', self.workflow)
        self.assertIn('bash -n scripts/fedora44_qemu_vm_check.sh', self.workflow)
        self.assertIn('bash scripts/fedora44_qemu_vm_check.sh', self.workflow)


if __name__ == '__main__':
    unittest.main()
