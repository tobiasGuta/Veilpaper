"""Static boundaries for graphical GDM evidence; no VM or host mutations."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = (ROOT / 'scripts/fedora44_vm_graphical_gdm_check.sh').read_text()
FLOW = (ROOT / '.github/workflows/fedora44-vm-gdm-visual.yml').read_text()


class GraphicalGDMHarnessGuards(unittest.TestCase):
    def test_guest_only_provenance_and_distinct_gpu(self):
        for value in ('GITHUB_ACTIONS', 'RUNNER_TEMP', 'Fedora-Cloud-Base-Generic-44',
                      'sha256sum -c -', '-vga none -device virtio-vga',
                      '-qmp "unix:$work/qmp.sock,server=on,wait=off"'):
            self.assertIn(value, HARNESS)

    def test_marker_protections_before_any_customization(self):
        for value in ('vm_gate.py', 'veilpaper-disposable-vm-qualification',
                      'veilpaper-disposable-vm-GDM-write-test',
                      'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'):
            self.assertIn(value, HARNESS)
        self.assertLess(HARNESS.index('snapshot stock-greeter'),
                        HARNESS.index('vm_real_transaction.py install'))

    def test_real_greeter_process_and_four_visual_artifacts(self):
        self.assertIn('scripts/verify_qemu_gdm_greeter.py', HARNESS)
        self.assertNotIn('pgrep -u gdm -f gnome-shell', HARNESS)
        for image in ('stock-greeter','customized-greeter',
                      'customized-after-reboot','restored-greeter'):
            self.assertIn('snapshot ' + image, HARNESS)
        self.assertIn('VISUAL_REVIEW_REQUIRED', HARNESS)
        self.assertIn('sudo rpm -V gnome-shell', HARNESS)

    def test_artifact_upload_and_bounded_runner(self):
        self.assertIn('runs-on: ubuntu-24.04', FLOW)
        self.assertIn('contents: read', FLOW)
        self.assertIn('timeout-minutes: 55', FLOW)
        self.assertIn('actions/upload-artifact@v4', FLOW)
        self.assertIn('if: always()', FLOW)
        self.assertNotIn('systemctl restart gdm' + '\nGUEST', HARNESS)
        self.assertNotIn('/mnt/Development/Tools', HARNESS)


if __name__ == '__main__':
    unittest.main()
