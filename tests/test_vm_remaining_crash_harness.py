"""Static safety assertions for remaining GDM crash VM qualification."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts/fedora44_vm_remaining_gdm_crash_check.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/fedora44-vm-remaining-crash.yml").read_text()


class RemainingCrashGuardTests(unittest.TestCase):
    def test_only_explicit_ci_and_disposable_vm(self):
        for word in ("GITHUB_ACTIONS", "RUNNER_TEMP", "CRASH_CHECKPOINT",
                     "qemu-system-x86_64", "vm_gate.py",
                     "veilpaper-disposable-vm-GDM-write-test"):
            self.assertIn(word, SCRIPT)
        self.assertNotIn("docker run", SCRIPT)

    def test_real_sigkill_verification_and_reboot_restoration(self):
        for word in ("crash_exit", "-ne 137", "expected_phase",
                     "expected_active", "crash-expected-sha",
                     "boot-before.id", "systemctl reboot",
                     "vm_real_transaction.py restore", "sudo rpm -V gnome-shell",
                     "%u:%g:%a:%C:%y"):
            self.assertIn(word, SCRIPT)

    def test_full_vm_matrix_and_narrow_permissions(self):
        for word in ("install-intent", "restore-intent", "restore-swap",
                     "matrix.checkpoint", "max-parallel: 3",
                     "fail-fast: false", "contents: read",
                     "runs-on: ubuntu-24.04"):
            self.assertIn(word, WORKFLOW)


if __name__ == "__main__":
    unittest.main()
