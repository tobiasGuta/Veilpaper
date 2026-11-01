"""Pure offline ownership and recovery model: never authority, never GDM writes."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_offline_ownership_recovery',
    ROOT / 'experiments/gdm/ownership_recovery_contract.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def sha(data):
    return hashlib.sha256(data).hexdigest()


BASE = sha(b'Veilpaper stock synthetic fixture')
CUSTOM = sha(b'Veilpaper custom synthetic fixture')
FOREIGN = sha(b'unrecognized foreign theme')


def clean():
    return {
        'rpm_sha256': BASE,
        'active_sha256': BASE,
        'active_metadata_verified': True,
        'legacy_backup_present': False,
        'legacy_manager_state_present': False,
        'transaction_state_present': False,
        'transaction_backup_sha256': None,
        'journal': None,
    }


def claim(phase, *, active=CUSTOM):
    e = clean()
    e.update({
        'active_sha256': active,
        'transaction_state_present': True,
        'transaction_backup_sha256': BASE,
        'journal': {
            'version': 2, 'phase': phase, 'base': BASE,
            'candidate': CUSTOM, 'uid': 0, 'gid': 0,
            'mode': 0o644, 'selinux_hex': '', 'mtime_ns': 987654321,
            'resource': '/org/gnome/shell/theme/fedora-login-wallpaper.png',
        },
    })
    return e


class OwnershipRecoveryModelTests(unittest.TestCase):
    def verdict(self, evidence):
        original = deepcopy(evidence)
        report = model.classify(evidence)
        self.assertEqual(evidence, original, 'Model must not modify source evidence')
        self.assertEqual(report['authorization'], 'NOT_GRANTED')
        self.assertFalse(report['write_enabled'])
        self.assertFalse(report['recovery_enabled'])
        self.assertFalse(report['delete_backup'])
        self.assertFalse(report['delete_journal'])
        self.assertTrue(report['requires_independent_ownership_proof'])
        self.assertTrue(report['issues'])
        self.assertEqual(report['contract_version'], 1)
        return report['classification']

    def test_pristine_stock_still_only_requires_review(self):
        self.assertEqual(self.verdict(clean()), 'FIRST_INSTALL_REVIEW_REQUIRED')

    def test_foreign_active_theme_preserved_even_with_matching_rpm(self):
        e = clean()
        e['active_sha256'] = FOREIGN
        self.assertEqual(self.verdict(e), 'PRESERVE_FOREIGN_CUSTOMIZATION')

    def test_legacy_backup_alone_blocks_even_pristine_stock(self):
        e = clean()
        e['legacy_backup_present'] = True
        self.assertEqual(self.verdict(e), 'PRESERVE_LEGACY_CUSTOMIZATION')

    def test_legacy_manager_state_blocks_even_if_no_backup(self):
        e = clean()
        e['legacy_manager_state_present'] = True
        self.assertEqual(self.verdict(e), 'PRESERVE_LEGACY_CUSTOMIZATION')

    def test_legacy_custom_theme_never_adopted_as_ours(self):
        e = claim('installed')
        e['legacy_backup_present'] = True
        self.assertEqual(self.verdict(e), 'PRESERVE_LEGACY_CUSTOMIZATION')

    def test_orphaned_backup_never_deleted_or_claimed(self):
        e = clean()
        e['transaction_backup_sha256'] = BASE
        self.assertEqual(self.verdict(e), 'PRESERVE_ORPHANED_BACKUP')

    def test_state_present_without_backup_never_recovered(self):
        e = claim('installed')
        e['transaction_backup_sha256'] = None
        self.assertEqual(self.verdict(e), 'PRESERVE_MISSING_BACKUP')

    def test_mismatched_backup_refuses_restore(self):
        e = claim('restore-prepared')
        e['transaction_backup_sha256'] = FOREIGN
        self.assertEqual(self.verdict(e), 'QUARANTINE_INCONSISTENT_BASELINE')

    def test_rpm_version_changed_after_install_requires_review(self):
        e = claim('installed')
        e['rpm_sha256'] = FOREIGN
        self.assertEqual(self.verdict(e), 'QUARANTINE_INCONSISTENT_BASELINE')

    def test_all_six_recovery_checkpoints_are_only_review_states(self):
        cases = (
            ('install-prepared', BASE, 'INSTALL_INTENT_REVIEW'),
            ('install-prepared', CUSTOM, 'INSTALL_SWAP_REVIEW'),
            ('installed', CUSTOM, 'INSTALLED_REVIEW'),
            ('restore-prepared', CUSTOM, 'RESTORE_INTENT_REVIEW'),
            ('restore-prepared', BASE, 'RESTORE_SWAP_REVIEW'),
            ('restored', BASE, 'RESTORED_RETAIN_EVIDENCE'),
        )
        for phase, active, expected in cases:
            with self.subTest(phase=phase, active=active):
                self.assertEqual(self.verdict(claim(phase, active=active)), expected)

    def test_foreign_active_bytes_under_journal_are_quarantined(self):
        e = claim('installed', active=FOREIGN)
        self.assertEqual(self.verdict(e), 'QUARANTINE_UNKNOWN_ACTIVE_OR_PHASE')

    def test_incompatible_phase_and_active_rejected(self):
        e = claim('restored', active=CUSTOM)
        self.assertEqual(self.verdict(e), 'QUARANTINE_UNKNOWN_ACTIVE_OR_PHASE')

    def test_forged_but_internally_consistent_journal_not_authorization(self):
        # Exact hashes and metadata fields supplied by an attacker can still
        # match; model must not claim ownership or permit recovery.
        report = model.classify(claim('restore-prepared', active=BASE))
        self.assertEqual(report['classification'], 'RESTORE_SWAP_REVIEW')
        self.assertFalse(report['recovery_enabled'])
        self.assertIn('NOT transaction ownership proof', report['issues'][0])

    def test_malformed_and_unknown_journals_quarantined(self):
        changes = (
            {'version': True}, {'version': 3}, {'phase': 'unknown-phase'},
            {'phase': []}, {'base': FOREIGN}, {'candidate': BASE},
            {'uid': 1000}, {'uid': True}, {'mode': 0o777},
            {'selinux_hex': 'xx'}, {'selinux_hex': 'a'},
            {'resource': '/tmp/injected'}, {'mtime_ns': -1},
            {'mtime_ns': False},
        )
        for change in changes:
            with self.subTest(change=change):
                e = claim('installed')
                e['journal'].update(change)
                self.assertEqual(self.verdict(e), 'QUARANTINE_UNVERIFIED_JOURNAL')

    def test_unknown_journal_fields_denied(self):
        e = claim('installed')
        e['journal']['owner_secret'] = 'forged'
        self.assertEqual(self.verdict(e), 'QUARANTINE_UNVERIFIED_JOURNAL')

    def test_unverified_metadata_blocks_even_consistent_journal(self):
        e = claim('restore-prepared', active=BASE)
        e['active_metadata_verified'] = False
        self.assertEqual(self.verdict(e), 'BLOCKED_METADATA')

    def test_unknown_top_level_keys_and_nonboolean_fields_refused(self):
        e = clean()
        e['authorization'] = 'GRANTED'
        self.assertEqual(self.verdict(e), 'BLOCKED_INVALID_EVIDENCE')
        e = clean()
        e['transaction_state_present'] = 1
        self.assertEqual(self.verdict(e), 'BLOCKED_INVALID_EVIDENCE')
        e = clean()
        e['rpm_sha256'] = 'BAD'
        self.assertEqual(self.verdict(e), 'BLOCKED_INVALID_EVIDENCE')

    def test_journal_cannot_be_supplied_without_state(self):
        e = clean()
        e['journal'] = claim('installed')['journal']
        self.assertEqual(self.verdict(e), 'BLOCKED_INVALID_EVIDENCE')

    def test_none_and_list_evidence_fail_closed(self):
        self.assertEqual(self.verdict(None), 'BLOCKED_INVALID_EVIDENCE')
        self.assertEqual(self.verdict([]), 'BLOCKED_INVALID_EVIDENCE')


if __name__ == '__main__':
    unittest.main()
