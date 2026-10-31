#!/usr/bin/env python3
"""Portable GDM admission review — READ-ONLY, never an installer.

Tests whether an unmodified RPM-matching live theme and a separately built
candidate have the exact expected Veilpaper resource diff. Even a PASS is only
structural evidence, not permission to write a system theme. Existing Veilpaper
or foreign customizations are always blocked.

All operations are reads of explicit paths, RPM metadata and compiled resources.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')
STATE = Path('/var/backups/fedora-gdm-wallpaper/manager-state.json')
MAX_CANDIDATE_BYTES = 96 * 1024 * 1024


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Missing review helper: {filename}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gdm = _load('veilpaper_admission_resource_reader', 'fedora_wallpaper_manager_v02.py')
rpm = _load('veilpaper_admission_rpm_reader', 'rpm_baseline.py')


def _regular(path: Path, label: str, issues: list[str], *, single_link=False) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        issues.append(f'{label} missing.')
        return False
    except OSError as error:
        issues.append(f'{label} inaccessible: {error}')
        return False
    if not stat.S_ISREG(info.st_mode):
        issues.append(f'{label} is not a regular non-symlink file.')
        return False
    if single_link and info.st_nlink != 1:
        issues.append(f'{label} has multiple hardlinks; refusing ambiguous candidate.')
        return False
    return True


def _resource_differences(theme: Path, candidate: Path):
    """Verify only two CSS rules and one new valid image; preserve all other data."""
    original = gdm.resources(theme)
    updated = gdm.resources(candidate)
    css_resources = {gdm.PREFIX + n for n in gdm.CSS_NAMES}
    if not css_resources.issubset(set(original)):
        raise RuntimeError('Baseline does not contain both expected GNOME CSS resources.')
    additions = set(updated) - set(original)
    if len(additions) != 1 or set(updated) != set(original) | additions:
        raise RuntimeError('Candidate does not preserve original resources plus one image.')
    asset = next(iter(additions))
    allowed = {gdm.PREFIX + f'{gdm.ASSET_BASENAME}.{ext}' for ext in ('png', 'jpg')}
    if asset not in allowed:
        raise RuntimeError('Candidate added an unexpected resource instead of a Veilpaper PNG/JPEG.')
    image = gdm.extract(candidate, asset)
    if not 10 <= len(image) <= gdm.MAX_IMAGE_BYTES:
        raise RuntimeError('Embedded wallpaper size is invalid.')
    if asset.endswith('.png') and not image.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Embedded wallpaper does not contain PNG bytes.')
    if asset.endswith('.jpg') and not image.startswith(b'\xff\xd8\xff'):
        raise RuntimeError('Embedded wallpaper does not contain JPEG bytes.')
    for name in original:
        before = gdm.extract(theme, name)
        after = gdm.extract(candidate, name)
        if name in css_resources:
            expected = gdm.patch_css(before.decode('utf-8'), asset).encode('utf-8')
            if after != expected:
                raise RuntimeError(f'Unexpected CSS modification in {name}.')
        elif before != after:
            raise RuntimeError(f'Unrelated packaged resource modified: {name}.')
    return asset, len(original)


def review(candidate: Path, *, theme=THEME, backup=BACKUP, state=STATE):
    """Return review evidence, blocked by default.

    A clean result may guide further offline engineering; it never authorizes
    writes, privileged actions, logouts, or replacing the GNOME theme.
    """
    candidate, theme, backup, state = map(Path, (candidate, theme, backup, state))
    result = {
        'verdict': 'BLOCKED',
        'active_theme': str(theme),
        'candidate': str(candidate),
        'rpm_sha256': None,
        'active_sha256': None,
        'candidate_sha256': None,
        'added_resource': None,
        'preserved_entries': None,
        'issues': [],
    }
    issues = result['issues']

    # A portable first-time install must not reuse our v0.2 on-host state or
    # silently overwrite an existing backup from another tool/version.
    if os.path.lexists(state):
        issues.append('Existing manager state: portable first-time installation is blocked.')
    if not _regular(theme, 'Active GDM theme', issues):
        return result
    record, error = rpm.package_record(theme)
    if error:
        issues.append(f'RPM baseline unavailable: {error}')
        return result
    result['rpm_sha256'] = record['digest']
    try:
        current = gdm.sha256(theme)
        result['active_sha256'] = current
        if current != record['digest'] or theme.stat().st_size != record['size']:
            issues.append('Active GDM theme differs from installed RPM metadata; preserve customization.')
        if os.path.lexists(backup):
            if _regular(backup, 'Existing backup', issues):
                if gdm.sha256(backup) != record['digest'] or backup.stat().st_size != record['size']:
                    issues.append('Existing backup is not the current installed RPM baseline; do not replace it.')
        if not _regular(candidate, 'Candidate', issues, single_link=True):
            return result
        if candidate.stat().st_size > MAX_CANDIDATE_BYTES:
            issues.append('Candidate resource exceeds size limit.')
            return result
        if candidate.samefile(theme) or (os.path.lexists(backup) and candidate.samefile(backup)):
            issues.append('Candidate aliases the active theme or original backup.')
            return result
        candidate_hash = gdm.sha256(candidate)
        result['candidate_sha256'] = candidate_hash
        if candidate_hash == current:
            issues.append('Candidate is identical to the active resource.')
        # Avoid costly parsing or false qualification when the live theme is
        # already customized, state exists, or backup disagrees with RPM.
        if issues:
            return result
        asset, original_count = _resource_differences(theme, candidate)
        result['added_resource'] = asset
        result['preserved_entries'] = original_count
        # Recheck read-only evidence, never permit a stale review to be an
        # install authorization (a later installer must independently recheck).
        refreshed, refreshed_error = rpm.package_record(theme)
        if (refreshed_error or refreshed != record or
                gdm.sha256(theme) != current or gdm.sha256(candidate) != candidate_hash):
            issues.append('Source or RPM metadata changed during review.')
    except (OSError, UnicodeError, RuntimeError, ValueError) as error:
        issues.append(f'Candidate review failed: {error}')
    if not issues:
        result['verdict'] = 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW'
    return result


def show(result):
    print('Veilpaper portable GDM install review — READ ONLY')
    print('Active GDM theme:', result['active_theme'])
    print('Candidate:', result['candidate'])
    print('Installed RPM SHA-256:', result['rpm_sha256'] or 'unavailable')
    print('Active SHA-256:', result['active_sha256'] or 'unavailable')
    print('Candidate SHA-256:', result['candidate_sha256'] or 'unavailable')
    if result['added_resource']:
        print('Added wallpaper resource:', result['added_resource'])
        print('Preserved resources:', result['preserved_entries'])
    for issue in result['issues']:
        print('BLOCKER:', issue)
    print('Verdict:', result['verdict'])
    print('NO INSTALL AUTHORIZATION. This inspection neither changes nor approves changing GDM.')
    print('A future privileged installer must independently validate provenance, backup, transaction, and recovery.')
    return 0 if result['verdict'] == 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW' else 1


if __name__ == '__main__':
    raise SystemExit('Use: python3 veilpaper.py login install-check CANDIDATE')
