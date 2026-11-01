#!/usr/bin/env python3
"""Read-only Veilpaper GDM action evidence contract (NOT an approval grant).

Classify proposed install/restore actions against current installed RPM data,
GDM customization, original backups, and an exact expected SHA-256. No
system writes, pkexec/sudo, auth tokens, or privileged install/restore APIs.
A positive structural review NEVER authorizes a later operation; a future
privileged helper must independently revalidate at execution time.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')
STATE = Path('/var/backups/fedora-gdm-wallpaper/manager-state.json')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


def _load(filename, label):
    spec = importlib.util.spec_from_file_location(label, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Read-only review component missing: {filename}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rpm = _load('rpm_baseline.py', 'veilpaper_approval_rpm')
reviewer = _load('install_review.py', 'veilpaper_approval_install_review')


def _safe_digest(path, label, issues, *, candidate=False):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or (candidate and info.st_nlink != 1):
            issues.append(f'{label} is not a regular, unaliased file.')
            return None
        if candidate and (info.st_size <= 0 or
                          info.st_size > reviewer.MAX_CANDIDATE_BYTES):
            issues.append('Candidate size exceeds accepted bounds.')
            return None
        return rpm.sha256_file(path)
    except (OSError, ValueError) as exc:
        issues.append(f'{label} not safely readable: {exc}')
        return None


def inspect_action(action, *, candidate=None, expected_sha256=None,
                   theme=THEME, backup=BACKUP, state=STATE):
    """Return a JSON-safe, fail-closed snapshot; never a permission or token.

    Paths may be overridden ONLY to permit offline fixture tests. This review
    has no write capability regardless of chosen paths. Any later privileged
    operation must ignore this report as authorization and recheck sources.
    """
    if action not in ('install', 'restore'):
        raise ValueError('Unsupported GDM action; only install or restore.')
    theme, backup, state = map(Path, (theme, backup, state))
    issues = []
    result = {
        'schema_version': 1,
        'action': action,
        'verdict': 'BLOCKED',
        'read_only': True,
        'authorization': 'NOT_GRANTED',
        'privileged_helper_available': False,
        'active_theme': str(theme),
        'original_backup': str(backup),
        'manager_state': str(state),
        'candidate': str(candidate) if candidate is not None else None,
        'expected_sha256': expected_sha256,
        'active_sha256': None,
        'candidate_sha256': None,
        'rpm_sha256': None,
        'backup_sha256': None,
        'existing_customization': 'UNVERIFIED',
        'issues': issues,
        'next_gate': 'Independent privileged revalidation, recovery and graphical qualification are required.',
    }

    if os.geteuid() == 0:
        issues.append('Read-only action review must run as an unprivileged user.')
        return result
    if not isinstance(expected_sha256, str) or not HEX64.fullmatch(expected_sha256):
        issues.append('An exact lowercase 64-character expected SHA-256 is required.')
        return result
    if action == 'install' and candidate is None:
        issues.append('Install review requires the exact candidate path.')
        return result
    if action == 'restore' and candidate is not None:
        issues.append('Restore review must not carry an installation candidate.')
        return result

    # Observe state existence but NEVER trust unknown existing manager state
    # as proof that this version owns the active customization or its backup.
    existing_state = os.path.lexists(state)
    existing_backup = os.path.lexists(backup)
    if existing_state:
        issues.append('Existing manager state requires independent recovery/ownership review.')
    if existing_backup and action == 'install':
        issues.append('Existing original backup must not be overwritten by an install.')

    try:
        baseline = rpm.inspect(theme=theme, backup=backup)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError) as exc:
        issues.append(f'Installed RPM comparison failed: {exc}')
        return result
    result['active_sha256'] = baseline.get('active_digest')
    result['backup_sha256'] = baseline.get('backup_digest')
    result['rpm_sha256'] = baseline.get('rpm_digest')
    match = baseline.get('active_matches_rpm') is True
    result['existing_customization'] = ('NONE_DETECTED' if match else
                                        'CUSTOM_OR_UNKNOWN' if result['active_sha256']
                                        else 'UNVERIFIED')
    if not baseline.get('rpm_digest'):
        issues.append('Installed RPM baseline is unavailable.')
    if not result['active_sha256']:
        issues.append('Active GDM theme cannot be verified.')
    elif not match:
        issues.append('Existing or unknown GDM customization must be preserved.')

    if action == 'restore':
        if result['active_sha256'] != expected_sha256:
            issues.append('Active GDM SHA-256 changed from the expected value.')
        if not existing_backup:
            issues.append('No independent original-theme backup exists.')
        elif baseline.get('backup_matches_rpm') is not True:
            issues.append('Backup is not proven to match the installed RPM baseline.')
        # There is no general production transaction owner/parser or approved
        # restore helper yet, so even apparently matching inputs remain blocked.
        issues.append('Production restore ownership and recovery helper are not implemented.')
        return result

    candidate = Path(candidate)
    result['candidate'] = str(candidate)
    digest = _safe_digest(candidate, 'Candidate', issues, candidate=True)
    result['candidate_sha256'] = digest
    if digest != expected_sha256:
        issues.append('Candidate SHA-256 does not equal the requested exact digest.')
    if issues:
        return result

    try:
        detail = reviewer.review(candidate, theme=theme, backup=backup, state=state)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError) as exc:
        issues.append(f'Independent candidate review failed: {exc}')
        return result
    if detail.get('verdict') != 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW':
        issues.extend(detail.get('issues') or ['Candidate failed independent structural review.'])
    if detail.get('candidate_sha256') != digest:
        issues.append('Candidate digest differs from independent structural review.')
    if detail.get('rpm_sha256') != result['rpm_sha256']:
        issues.append('RPM evidence differs between independent reviews.')
    if detail.get('active_sha256') != result['active_sha256']:
        issues.append('Active theme changed between independent reviews.')
    # Check for TOCTOU during this advisory report, never authorize from it.
    if (_safe_digest(candidate, 'Candidate recheck', issues, candidate=True) != digest
            or _safe_digest(theme, 'Active theme recheck', issues) != result['active_sha256']
            or os.path.lexists(state) != existing_state
            or os.path.lexists(backup) != existing_backup):
        issues.append('Input or manager state changed during the read-only review.')
    if not issues:
        result['verdict'] = 'STRUCTURAL_REVIEW_ONLY'
        result['next_gate'] = (
            'Visual Workstation qualification and separately approved privileged '
            'helper required; THIS REPORT IS NOT AN AUTHORIZATION.')
    return result


def show(report):
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['verdict'] == 'STRUCTURAL_REVIEW_ONLY' else 1


if __name__ == '__main__':
    raise SystemExit('Use: python3 veilpaper.py login approval-review ...')
