"""Veilpaper production ownership/recovery *model*, offline and NO-WRITE.

This is an evidence-shape classifier, NOT a privileged helper, authorization
token, file-system inspector, journal validator for real adoption, or recovery
command. Inputs are hypothetical snapshots supplied by tests. In particular,
an internally consistent journal only makes a recovery *review* conceivable;
it NEVER establishes that Veilpaper created or owns an on-host customization.
"""
from __future__ import annotations

import re

_HEX = re.compile(r'[0-9a-f]{64}\Z')
_SEL = re.compile(r'(?:[0-9a-f]{2})*\Z')
_RESOURCE = re.compile(
    r'/org/gnome/shell/theme/fedora-login-wallpaper\.(?:png|jpg)\Z')
_PHASES = frozenset({
    'install-prepared', 'installed', 'restore-prepared', 'restored',
})
_EVIDENCE_KEYS = frozenset({
    'rpm_sha256', 'active_sha256', 'active_metadata_verified',
    'legacy_backup_present', 'legacy_manager_state_present',
    'transaction_state_present', 'transaction_backup_sha256', 'journal',
})
_JOURNAL_KEYS = frozenset({
    'version', 'phase', 'base', 'candidate', 'uid', 'gid',
    'mode', 'selinux_hex', 'resource', 'mtime_ns',
})


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _boolean(value):
    return type(value) is bool


def _journal_valid(value):
    """Reject ambiguous/unrecognized journal shapes; never authenticate one."""
    if not isinstance(value, dict) or set(value) != _JOURNAL_KEYS:
        return False
    return (
        type(value['version']) is int and value['version'] == 2
        and value['phase'] in _PHASES
        and _digest(value['base']) and _digest(value['candidate'])
        and value['base'] != value['candidate']
        and type(value['uid']) is int and value['uid'] == 0
        and type(value['gid']) is int and value['gid'] >= 0
        and type(value['mode']) is int and value['mode'] == 0o644
        and type(value['mtime_ns']) is int and value['mtime_ns'] >= 0
        and isinstance(value['selinux_hex'], str)
        and len(value['selinux_hex']) <= 8192
        and _SEL.fullmatch(value['selinux_hex']) is not None
        and isinstance(value['resource'], str)
        and _RESOURCE.fullmatch(value['resource']) is not None
    )


def classify(snapshot):
    """Evaluate a fixture snapshot without filesystem, network or root access.

    Each result is advisory. Even RECOVERY_REVIEW_REQUIRED cannot authorize an
    install, restore, journal cleanup, GDM restart, or use of an existing backup.
    A future production helper must independently verify trusted provenance,
    live path identities/metadata, locks and all hashes at operation time.
    """
    verdict = {
        'contract_version': 1,
        'classification': 'BLOCKED_INVALID_EVIDENCE',
        'authorization': 'NOT_GRANTED',
        'write_enabled': False,
        'recovery_enabled': False,
        'delete_backup': False,
        'delete_journal': False,
        'requires_independent_ownership_proof': True,
        'issues': [],
        'next_gate': (
            'Production helper must independently establish ownership, '
            'exact-action authorization, backup integrity and crash recovery.'
        ),
    }
    issues = verdict['issues']

    if not isinstance(snapshot, dict) or set(snapshot) != _EVIDENCE_KEYS:
        issues.append('Evidence schema missing, ambiguous, or contains unknown keys.')
        return verdict
    for key in ('legacy_backup_present', 'legacy_manager_state_present',
                'transaction_state_present', 'active_metadata_verified'):
        if not _boolean(snapshot[key]):
            issues.append(f'{key} must be a real boolean.')
    if not _digest(snapshot['rpm_sha256']) or not _digest(snapshot['active_sha256']):
        issues.append('Exact installed RPM and active theme SHA-256 required.')
    backup = snapshot['transaction_backup_sha256']
    if backup is not None and not _digest(backup):
        issues.append('Transaction backup digest is invalid.')
    if issues:
        return verdict

    if snapshot['legacy_backup_present'] or snapshot['legacy_manager_state_present']:
        verdict['classification'] = 'PRESERVE_LEGACY_CUSTOMIZATION'
        issues.append('Existing legacy backup/manager state must never be adopted or overwritten.')
        return verdict

    if not snapshot['active_metadata_verified']:
        verdict['classification'] = 'BLOCKED_METADATA'
        issues.append('Exact active GDM metadata has not been independently verified.')
        return verdict

    present = snapshot['transaction_state_present']
    record = snapshot['journal']
    if not present:
        if record is not None:
            issues.append('Journal supplied despite absent state file.')
            return verdict
        if backup is not None:
            verdict['classification'] = 'PRESERVE_ORPHANED_BACKUP'
            issues.append('Backup without journal has unknown ownership; preserve it.')
            return verdict
        if snapshot['active_sha256'] == snapshot['rpm_sha256']:
            verdict['classification'] = 'FIRST_INSTALL_REVIEW_REQUIRED'
            issues.append('Pristine fixture is only eligible for separate structural review.')
        else:
            verdict['classification'] = 'PRESERVE_FOREIGN_CUSTOMIZATION'
            issues.append('Existing active customization has no provable Veilpaper ownership.')
        return verdict

    if not _journal_valid(record):
        verdict['classification'] = 'QUARANTINE_UNVERIFIED_JOURNAL'
        issues.append('Malformed, unknown, or unsupported transaction journal; no recovery.')
        return verdict
    if backup is None:
        verdict['classification'] = 'PRESERVE_MISSING_BACKUP'
        issues.append('Transaction journal exists without durable original backup.')
        return verdict
    if backup != record['base'] or snapshot['rpm_sha256'] != record['base']:
        verdict['classification'] = 'QUARANTINE_INCONSISTENT_BASELINE'
        issues.append('Transaction backup, journal base, and installed RPM digest disagree.')
        return verdict

    active = snapshot['active_sha256']
    phase = record['phase']
    allowed = {
        ('install-prepared', record['base']): 'INSTALL_INTENT_REVIEW',
        ('install-prepared', record['candidate']): 'INSTALL_SWAP_REVIEW',
        ('installed', record['candidate']): 'INSTALLED_REVIEW',
        ('restore-prepared', record['candidate']): 'RESTORE_INTENT_REVIEW',
        ('restore-prepared', record['base']): 'RESTORE_SWAP_REVIEW',
        ('restored', record['base']): 'RESTORED_RETAIN_EVIDENCE',
    }
    stage = allowed.get((phase, active))
    if stage is None:
        verdict['classification'] = 'QUARANTINE_UNKNOWN_ACTIVE_OR_PHASE'
        issues.append('Active bytes and journal checkpoint are inconsistent or foreign.')
        return verdict
    verdict['classification'] = stage
    issues.append(
        'Digest and checkpoint correspondence is NOT transaction ownership proof; '
        'never restore or finalize based on this claim alone.'
    )
    return verdict
