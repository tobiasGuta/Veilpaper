"""Crash injector is gated; actual SIGKILL test only writes temporary files."""
import contextlib
import importlib.util
from io import StringIO
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_vm_crash_injector',
    ROOT / 'experiments/gdm/vm_real_crash_injector.py')
inject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inject)


class RealVMCrashInjectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-crash-real-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.theme = Path(self.temp.name) / 'fake-gnome-theme.gresource'
        self.theme.write_bytes(b'original')

    def test_guard_denies_before_any_atomic_write(self):
        def refuse():
            raise RuntimeError('not in authorized disposable VM')
        txn = SimpleNamespace(
            gate=refuse, THEME=self.theme,
            _atomic=lambda *a, **kw: self.fail('must not write'),
            install=lambda *a: self.fail('must not install'))
        with self.assertRaisesRegex(RuntimeError, 'not in authorized'):
            inject.inject_install_swap(txn, Path('candidate.gresource'))
        self.assertEqual(self.theme.read_bytes(), b'original')

    def test_wrong_confirmation_rejected_before_guard(self):
        txn = SimpleNamespace(PHRASE='VM ONLY')
        with patch.object(inject, '_load_txn', return_value=txn), \
             patch.object(inject, 'inject_install_swap') as launch, \
             contextlib.redirect_stderr(StringIO()) as errors:
            code = inject.main(['install-swap', '--candidate', str(self.theme),
                                '--confirm', 'no'])
        self.assertEqual(code, 1)
        self.assertIn('phrase missing', errors.getvalue())
        launch.assert_not_called()

    @unittest.skipUnless(hasattr(os, 'fork'), 'Needs POSIX SIGKILL')
    def test_child_is_actually_killed_after_target_write(self):
        # Never fork a child that can access live GDM: the transaction fake
        # points exclusively into a new TemporaryDirectory.
        fake = SimpleNamespace()
        fake.THEME = self.theme
        fake.gate = lambda: None
        fake._atomic = lambda path, data, **kw: Path(path).write_bytes(data)
        fake.install = lambda candidate: fake._atomic(fake.THEME, b'candidate')
        pid = os.fork()
        if pid == 0:
            try:
                inject.inject_install_swap(fake, self.theme)
            except BaseException:
                os._exit(99)
            os._exit(98)
        waited, status = os.waitpid(pid, 0)
        self.assertEqual(waited, pid)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
        self.assertEqual(self.theme.read_bytes(), b'candidate')

    def test_non_theme_write_does_not_trigger_kill(self):
        journal = Path(self.temp.name) / 'journal'
        fake = SimpleNamespace()
        fake.THEME = self.theme
        fake.gate = lambda: None
        fake._atomic = lambda path, data, **kw: Path(path).write_bytes(data)
        fake.install = lambda candidate: fake._atomic(journal, b'prepared')
        with self.assertRaisesRegex(RuntimeError, 'Expected SIGKILL'):
            inject.inject_install_swap(fake, self.theme)
        self.assertEqual(self.theme.read_bytes(), b'original')
        self.assertEqual(journal.read_bytes(), b'prepared')


if __name__ == '__main__':
    unittest.main()
