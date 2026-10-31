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


    def test_unsupported_checkpoint_refused_before_vm_gate(self):
        fake = SimpleNamespace(gate=lambda: self.fail('unexpected gate'))
        with self.assertRaisesRegex(RuntimeError, 'unsupported'):
            inject.inject_checkpoint(fake, 'not-a-checkpoint')

    def test_restore_checkpoint_rejects_candidate_before_vm_gate(self):
        fake = SimpleNamespace(gate=lambda: self.fail('unexpected gate'))
        with self.assertRaisesRegex(RuntimeError, 'forbids candidate'):
            inject.inject_checkpoint(fake, 'restore-intent', self.theme)

    def test_install_checkpoint_requires_candidate_before_vm_gate(self):
        fake = SimpleNamespace(gate=lambda: self.fail('unexpected gate'))
        with self.assertRaisesRegex(RuntimeError, 'requires a candidate'):
            inject.inject_checkpoint(fake, 'install-intent')

    @unittest.skipUnless(hasattr(os, 'fork'), 'Needs POSIX SIGKILL')
    def test_all_real_checkpoint_hooks_die_after_selected_durable_step(self):
        # All paths here are private TemporaryDirectory fixtures, not GDM.
        import json
        scenarios = {
            'install-intent': ('install-prepared', b'original'),
            'install-swap': ('install-prepared', b'candidate'),
            'restore-intent': ('restore-prepared', b'candidate'),
            'restore-swap': ('restore-prepared', b'original'),
        }
        for checkpoint, (phase, active) in scenarios.items():
            with self.subTest(checkpoint=checkpoint):
                target = Path(self.temp.name) / ('theme-' + checkpoint)
                journal = Path(self.temp.name) / ('state-' + checkpoint)
                target.write_bytes(b'original' if checkpoint.startswith('install') else b'candidate')
                fake = SimpleNamespace(THEME=target, gate=lambda: None)

                def write_journal(state):
                    journal.write_text(json.dumps(state))

                def write_resource(path, data, **kwargs):
                    Path(path).write_bytes(data)

                fake._write_state = write_journal
                fake._atomic = write_resource

                def do_install(candidate):
                    fake._write_state({'phase': 'install-prepared'})
                    fake._atomic(fake.THEME, b'candidate')
                    fake._write_state({'phase': 'installed'})

                def do_restore():
                    fake._write_state({'phase': 'restore-prepared'})
                    fake._atomic(fake.THEME, b'original')
                    fake._write_state({'phase': 'restored'})

                fake.install = do_install
                fake.restore = do_restore
                pid = os.fork()
                if pid == 0:
                    try:
                        inject.inject_checkpoint(fake, checkpoint,
                                                 target if checkpoint.startswith('install') else None)
                    except BaseException:
                        os._exit(99)
                    os._exit(98)
                waited, status = os.waitpid(pid, 0)
                self.assertEqual(waited, pid)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                self.assertEqual(json.loads(journal.read_text())['phase'], phase)
                self.assertEqual(target.read_bytes(), active)


if __name__ == '__main__':
    unittest.main()
