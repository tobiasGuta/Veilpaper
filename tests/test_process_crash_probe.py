"""Fork-and-SIGKILL GDM fixture recovery regression checks (no live writes)."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_process_crash_probe', ROOT / 'experiments/gdm/process_crash_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@unittest.skipUnless(hasattr(os, 'fork'), 'Real process-kill tests require POSIX')
class ProcessCrashFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-sigkill-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'stock.gresource'
        self.candidate = self.root / 'candidate.gresource'
        self.base.write_bytes(b'original GNOME fixture resource')
        self.candidate.write_bytes(b'customized GNOME fixture resource')

    def test_real_process_kills_recover_from_all_four_interruption_points(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch.object(probe.os, 'geteuid', return_value=1000):
            outcomes = probe.probe(self.base, self.candidate)
        self.assertEqual(outcomes, [name for name, *_ in probe.CASES])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_root_execution_is_refused_before_any_child_or_filesystem_operation(self):
        with patch.object(probe.os, 'geteuid', return_value=0), \
             patch.object(probe.os, 'fork') as fork:
            with self.assertRaisesRegex(RuntimeError, 'not with sudo'):
                probe.probe(self.base, self.candidate)
            fork.assert_not_called()

    def test_equal_candidate_is_rejected(self):
        with patch.object(probe.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(RuntimeError, 'distinct'):
                probe.probe(self.base, self.base)

    def test_symlink_source_is_refused(self):
        alias = self.root / 'linked.gresource'
        alias.symlink_to(self.base)
        with patch.object(probe.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(Exception, 'non-symlink'):
                probe.probe(alias, self.candidate)

    def test_missing_source_file_is_refused(self):
        with patch.object(probe.os, 'geteuid', return_value=1000):
            with self.assertRaises(FileNotFoundError):
                probe.probe(self.root / 'missing.gresource', self.candidate)


if __name__ == '__main__':
    unittest.main()
