#!/usr/bin/env python3
"""Read-only RPM database baseline comparison for GNOME's compiled theme.

A digest match is evidence of consistency with the installed RPM database, NOT
independent proof that the RPM package or its metadata is trustworthy. This
module never changes /usr/share, backup files, RPM metadata or manager state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package_record(theme: Path):
    """Fetch exactly this packaged file's SHA-256 and size from installed RPM DB."""
    if not shutil.which('rpm'):
        return None, 'RPM utility is not installed.'
    try:
        proc = subprocess.run(
            ['rpm', '-q', '--dump', '-f', str(theme)],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f'RPM query failed: {exc}'
    if proc.returncode:
        return None, f'RPM metadata unavailable for {theme}: {proc.stderr.strip()}'
    matching = [line.split() for line in proc.stdout.splitlines()
                if line.split() and line.split()[0] == str(theme)]
    if len(matching) != 1 or len(matching[0]) < 4:
        return None, 'RPM file record is missing, ambiguous, or incomplete.'
    row = matching[0]
    try:
        size = int(row[1])
    except ValueError:
        return None, 'RPM file record has invalid size.'
    if size < 0:
        return None, 'RPM file record has negative size.'
    recorded_digest = row[3].lower()
    if not re.fullmatch(r'[0-9a-f]{64}', recorded_digest):
        return None, 'RPM file digest is not SHA-256; cannot qualify baseline.'
    return {'digest': recorded_digest, 'size': size}, None


def inspect(theme=THEME, backup=BACKUP):
    result = {
        'theme': str(theme),
        'backup': str(backup),
        'rpm_digest': None,
        'rpm_size': None,
        'active_digest': None,
        'backup_digest': None,
        'active_matches_rpm': False,
        'backup_matches_rpm': False,
        'verdict': 'UNVERIFIED',
        'issues': [],
    }
    if theme.is_symlink() or not theme.is_file():
        result['issues'].append('Active theme is absent, not a regular file or is a symlink.')
        return result

    record, error = package_record(theme)
    if error:
        result['issues'].append(error)
        return result
    result['rpm_digest'] = record['digest']
    result['rpm_size'] = record['size']

    def compare(path, label):
        if path.is_symlink() or not path.is_file():
            result['issues'].append(f'{label} absent, not regular or is a symlink.')
            return None, False
        try:
            mode = path.stat()
            if not stat.S_ISREG(mode.st_mode):
                result['issues'].append(f'{label} is not a regular file.')
                return None, False
            digest = sha256_file(path)
            return digest, digest == record['digest'] and mode.st_size == record['size']
        except OSError as exc:
            result['issues'].append(f'{label} unreadable: {exc}')
            return None, False

    result['active_digest'], result['active_matches_rpm'] = compare(theme, 'Active theme')
    if backup.exists() or backup.is_symlink():
        result['backup_digest'], result['backup_matches_rpm'] = compare(backup, 'Backup')
    else:
        result['issues'].append('No independent original-theme backup found.')

    if result['active_matches_rpm']:
        result['verdict'] = 'ACTIVE_MATCHES_RPM_DATABASE'
    elif result['backup_matches_rpm']:
        result['verdict'] = 'BACKUP_MATCHES_RPM_DATABASE'
    else:
        result['verdict'] = 'NO_MATCHING_RPM_BASELINE'
    return result


def show(result):
    print('Veilpaper RPM baseline inspection — READ-ONLY')
    print('Active theme:', result['theme'])
    print('Backup:', result['backup'])
    print('Installed RPM SHA-256:', result['rpm_digest'] or 'unavailable')
    print('Installed RPM size:', result['rpm_size'] if result['rpm_size'] is not None else 'unavailable')
    print('Active SHA-256:', result['active_digest'] or 'unavailable')
    print('Backup SHA-256:', result['backup_digest'] or 'unavailable')
    print('Active matches RPM database:', result['active_matches_rpm'])
    print('Backup matches RPM database:', result['backup_matches_rpm'])
    for issue in result['issues']:
        print('NOTE:', issue)
    print('Verdict:', result['verdict'])
    print('WARNING: RPM database match does not independently verify package provenance.')
    print('No system or backup files have been modified.')
    return 0 if result['active_matches_rpm'] or result['backup_matches_rpm'] else 1


if __name__ == '__main__':
    raise SystemExit(show(inspect()))
