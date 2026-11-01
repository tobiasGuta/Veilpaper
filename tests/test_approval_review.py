"""No-sudo, no-write GDM action-evidence contract (all test paths disposable)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_approval_review_test_module',
    ROOT / 'experiments/gdm/approval_review.py')
approval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approval)


class GDMApprovalReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-review-test-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.theme = root / 'theme.gresource'
        self.backup = root / 'original.gresource'
        self.state = root / 'manager-state.json'
        self.candidate = root / 'candidate.gresource'
        self.theme.write_bytes(b'packaged-theme')
        self.candidate.write_bytes(b'candidate-only')
        self.rpm_sha = hashlib.sha256(self.theme.read_bytes()).hexdigest()
        self.candidate_sha = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        self.patcher = patch.object(approval.rpm, 'package_record',
                                    return_value=({'digest': self.rpm_sha,
                                                   'size': self.theme.stat().st_size}, None))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.user = patch.object(approval.os, 'geteuid', return_value=1000)
        self.user.start()
        self.addCleanup(self.user.stop)

    def _review(self, action='install', **overrides):
        inputs = {'candidate': self.candidate if action == 'install' else None,
                  'expected_sha256': self.candidate_sha if action == 'install' else self.rpm_sha,
                  'theme': self.theme, 'backup': self.backup, 'state': self.state}
        inputs.update(overrides)
        return approval.inspect_action(action, **inputs)

    def _successful_structural_review(self):
        return {
            'verdict': 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW',
            'candidate_sha256': self.candidate_sha,
            'rpm_sha256': self.rpm_sha,
            'active_sha256': self.rpm_sha,
            'issues': [],
        }

    def test_clean_exact_install_is_structural_review_only_not_permission(self):
        with patch.object(approval.reviewer, 'review',
                          return_value=self._successful_structural_review()) as independent:
            before = self.theme.read_bytes()
            report = self._review()
        self.assertEqual(report['verdict'], 'STRUCTURAL_REVIEW_ONLY')
        self.assertEqual(report['authorization'], 'NOT_GRANTED')
        self.assertIs(report['privileged_helper_available'], False)
        self.assertIs(report['read_only'], True)
        self.assertEqual(self.theme.read_bytes(), before)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.state.exists())
        independent.assert_called_once_with(
            self.candidate, theme=self.theme, backup=self.backup, state=self.state)
        self.assertEqual(approval.show(report), 0)
        self.assertEqual(json.loads(json.dumps(report))['schema_version'], 1)

    def test_edited_candidate_is_blocked_before_structural_parse(self):
        self.candidate.write_bytes(b'modified')
        with patch.object(approval.reviewer, 'review') as independent:
            report = self._review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('Candidate SHA-256' in issue for issue in report['issues']))
        independent.assert_not_called()

    def test_existing_custom_theme_preserved_even_if_backup_matches_rpm(self):
        self.backup.write_bytes(self.theme.read_bytes())
        self.theme.write_bytes(b'existing-atom-custom-theme')
        with patch.object(approval.reviewer, 'review') as independent:
            report = self._review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertEqual(report['existing_customization'], 'CUSTOM_OR_UNKNOWN')
        self.assertTrue(any('preserved' in issue for issue in report['issues']))
        self.assertEqual(self.theme.read_bytes(), b'existing-atom-custom-theme')
        independent.assert_not_called()

    def test_existing_stock_backup_or_manager_state_blocks_install(self):
        self.backup.write_bytes(self.theme.read_bytes())
        report = self._review()
        self.assertTrue(any('overwritten' in issue for issue in report['issues']))
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.backup.unlink()
        self.state.write_text('foreign state')
        report = self._review()
        self.assertTrue(any('ownership review' in issue for issue in report['issues']))
        self.assertEqual(self.state.read_text(), 'foreign state')

    def test_restore_cannot_be_approved_even_with_valid_backup_and_matching_digest(self):
        self.backup.write_bytes(self.theme.read_bytes())
        with patch.object(approval.reviewer, 'review') as independent:
            report = self._review('restore')
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertEqual(report['authorization'], 'NOT_GRANTED')
        self.assertTrue(any('not implemented' in issue for issue in report['issues']))
        independent.assert_not_called()
        self.assertEqual(self.backup.read_bytes(), self.theme.read_bytes())

    def test_restore_stale_expected_active_sha_is_blocked(self):
        report = self._review('restore', expected_sha256='c' * 64)
        self.assertTrue(any('changed' in issue for issue in report['issues']))

    def test_restore_rejects_candidate_argument(self):
        report = self._review('restore', candidate=self.candidate)
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('must not carry' in issue for issue in report['issues']))

    def test_symlinked_candidate_rejected_and_target_unchanged(self):
        self.candidate.unlink()
        outside = self.candidate.parent / 'other-file'
        outside.write_bytes(b'candidate-only')
        self.candidate.symlink_to(outside)
        with patch.object(approval.reviewer, 'review') as independent:
            report = self._review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertEqual(outside.read_bytes(), b'candidate-only')
        independent.assert_not_called()

    def test_hardlinked_candidate_rejected(self):
        link = self.candidate.parent / 'second-hardlink'
        os.link(self.candidate, link)
        report = self._review()
        self.assertTrue(any('unaliased' in issue for issue in report['issues']))

    def test_fake_structural_review_digests_are_rejected(self):
        wrong = self._successful_structural_review()
        wrong['candidate_sha256'] = 'f' * 64
        with patch.object(approval.reviewer, 'review', return_value=wrong):
            report = self._review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('independent structural review' in i for i in report['issues']))

    def test_malformed_digest_and_root_never_call_structural_parser(self):
        with patch.object(approval.reviewer, 'review') as independent:
            result = self._review(expected_sha256='not-a-digest')
            self.assertEqual(result['verdict'], 'BLOCKED')
            with patch.object(approval.os, 'geteuid', return_value=0):
                result2 = self._review()
            self.assertEqual(result2['verdict'], 'BLOCKED')
        independent.assert_not_called()

    def test_unknown_action_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            self._review('erase')

    def test_rpm_metadata_unavailable_blocks(self):
        with patch.object(approval.rpm, 'package_record',
                          return_value=(None, 'RPM DB absent')):
            report = self._review()
        self.assertEqual(report['verdict'], 'BLOCKED')
        self.assertTrue(any('RPM baseline' in i for i in report['issues']))


if __name__ == '__main__':
    unittest.main()
