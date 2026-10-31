"""Tests for disposable GDM journal engine: no /usr/share or /var/backups writes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('veilpaper_fixture_transaction',
    HERE / 'experiments/gdm/fixture_transaction.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
BASE = b'original GDM fixture data'
CANDIDATE = b'customized GDM fixture data'


class FixtureTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-test-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = engine.FixtureTransaction.initialize(self.root, BASE, CANDIDATE)

    def test_normal_apply_restore(self):
        self.assertEqual(self.fixture.status(), 'ORIGINAL')
        self.fixture.apply()
        self.assertEqual(self.fixture.status(), 'INSTALLED')
        self.assertEqual(self.fixture.active.read_bytes(), CANDIDATE)
        self.fixture.restore()
        self.assertEqual(self.fixture.status(), 'ORIGINAL')
        self.assertEqual(self.fixture.active.read_bytes(), BASE)
        self.assertFalse(self.fixture.state.exists())

    def test_repeated_install_refused(self):
        self.fixture.apply()
        with self.assertRaisesRegex(engine.FixtureError, 'existing or unknown'):
            self.fixture.apply()
        self.assertEqual(self.fixture.status(), 'INSTALLED')

    def test_install_intent_only_can_recover(self):
        with self.assertRaises(engine.InjectedInterruption):
            self.fixture.apply(interrupt='install-intent')
        self.assertEqual(self.fixture.status(), 'INSTALL_INTENT_ONLY')
        self.fixture.restore()
        self.assertEqual(self.fixture.status(), 'ORIGINAL')

    def test_install_swap_recovery(self):
        with self.assertRaises(engine.InjectedInterruption):
            self.fixture.apply(interrupt='install-swap')
        self.assertEqual(self.fixture.status(), 'INSTALL_SWAPPED_NOT_FINALIZED')
        self.fixture.restore()
        self.assertEqual(self.fixture.status(), 'ORIGINAL')

    def test_restore_intent_recovery(self):
        self.fixture.apply()
        with self.assertRaises(engine.InjectedInterruption):
            self.fixture.restore(interrupt='restore-intent')
        self.assertEqual(self.fixture.status(), 'RESTORE_INTENT_ONLY')
        self.fixture.restore()
        self.assertEqual(self.fixture.status(), 'ORIGINAL')

    def test_restore_swap_recovery(self):
        self.fixture.apply()
        with self.assertRaises(engine.InjectedInterruption):
            self.fixture.restore(interrupt='restore-swap')
        self.assertEqual(self.fixture.status(), 'RESTORE_SWAPPED_NOT_FINALIZED')
        self.fixture.restore()
        self.assertEqual(self.fixture.status(), 'ORIGINAL')

    def test_alien_active_bytes_fail_closed(self):
        self.fixture.apply()
        self.fixture.active.write_bytes(b'unrelated modification')
        with self.assertRaisesRegex(engine.FixtureError, 'Unknown active'):
            self.fixture.restore()
        self.assertEqual(self.fixture.active.read_bytes(), b'unrelated modification')

    def test_tampered_state_fails_closed(self):
        self.fixture.apply()
        self.fixture.state.write_text('{"version": 1, "phase": "installed", "base": "bad", "candidate": "bad"}')
        with self.assertRaisesRegex(engine.FixtureError, 'no longer matches'):
            self.fixture.restore()
        self.assertEqual(self.fixture.active.read_bytes(), CANDIDATE)

    def test_symlink_fixture_active_refused(self):
        self.fixture.active.unlink()
        self.fixture.active.symlink_to(self.fixture.base)
        with self.assertRaisesRegex(engine.FixtureError, 'Unsafe fixture'):
            self.fixture.apply()

    def test_hardlinked_fixture_active_refused(self):
        alias = self.root / 'other-link'
        alias.hardlink_to(self.fixture.active)
        with self.assertRaisesRegex(engine.FixtureError, 'hardlink'):
            self.fixture.apply()

    def test_missing_fixture_marker_refused(self):
        self.fixture.marker.unlink()
        with self.assertRaises(FileNotFoundError):
            self.fixture.apply()

    def test_simulation_does_not_modify_input_files(self):
        with tempfile.TemporaryDirectory(prefix='veilpaper-txn-source-') as name:
            folder = Path(name)
            base, candidate = folder / 'stock.gresource', folder / 'custom.gresource'
            base.write_bytes(BASE)
            candidate.write_bytes(CANDIDATE)
            results = engine.simulate(base, candidate)
            self.assertEqual(len(results), 5)
            self.assertEqual(base.read_bytes(), BASE)
            self.assertEqual(candidate.read_bytes(), CANDIDATE)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['custom.gresource', 'stock.gresource'])

    def test_same_bytes_denied(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name) / 'a.gresource'
            p.write_bytes(BASE)
            with self.assertRaisesRegex(engine.FixtureError, 'must differ'):
                engine.simulate(p, p)


if __name__ == '__main__':
    unittest.main()
