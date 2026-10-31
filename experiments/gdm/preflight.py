#!/usr/bin/env python3
"""Read-only GNOME GDM theme portability preflight. Never modifies the system.

This is intentionally NOT proof that the current resource is pristine. A future
cross-machine installer must independently establish trusted baselines, backups,
recovery access, and safe transactional writes before offering apply/restore.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess

THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')
STATE = Path('/var/backups/fedora-gdm-wallpaper/manager-state.json')
PREFIX = '/org/gnome/shell/theme/'
CSS_NAMES = ('gnome-shell-dark.css', 'gnome-shell-light.css')
CSS_BLOCK = re.compile(r'#lockDialogGroup\s*\{([^{}]*)\}', re.DOTALL)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _run(*args):
    try:
        p = subprocess.run(args, capture_output=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, str(exc)
    if p.returncode != 0:
        return None, p.stderr.decode('utf-8', errors='replace').strip()
    return p.stdout, None


def inspect(theme=THEME, state=STATE, backup=BACKUP):
    """Return a diagnostic snapshot; all access is read-only."""
    result = {
        'path': str(theme),
        'resource_sha256': None,
        'resource_count': None,
        'css': {},
        'modified_state_present': state.exists() or state.is_symlink(),
        'backup_present': backup.exists() or backup.is_symlink(),
        'issues': [],
        'notes': [],
    }
    if theme.is_symlink():
        result['issues'].append('Theme path is a symlink; do not write through it.')
        return result
    if not theme.is_file():
        result['issues'].append('No regular GNOME Shell theme resource was found.')
        return result
    try:
        result['resource_sha256'] = _sha256(theme)
    except OSError as exc:
        result['issues'].append(f'Cannot read theme: {exc}')
        return result

    if not shutil.which('gresource'):
        result['issues'].append('gresource utility missing (needed for inspection).')
        return result
    raw, err = _run('gresource', 'list', str(theme))
    if err is not None:
        result['issues'].append(f'Cannot list compiled theme resources: {err}')
        return result
    entries = raw.decode('utf-8', errors='replace').splitlines()
    result['resource_count'] = len(entries)
    if not entries or len(entries) != len(set(entries)):
        result['issues'].append('Resource listing is empty or contains duplicates.')
    if any(not entry.startswith(PREFIX) for entry in entries):
        result['issues'].append('Unknown resource prefix; resource layout is unsupported.')
    for css in CSS_NAMES:
        resource = PREFIX + css
        if resource not in entries:
            result['issues'].append(f'Missing expected resource: {resource}')
            continue
        data, err = _run('gresource', 'extract', str(theme), resource)
        if err is not None:
            result['issues'].append(f'Failed to extract {css}: {err}')
            continue
        text = data.decode('utf-8', errors='replace')
        blocks = CSS_BLOCK.findall(text)
        result['css'][css] = {
            'lock_dialog_blocks': len(blocks),
            'contains_background_image': any('background-image' in b or 'url(' in b for b in blocks),
        }
        if len(blocks) != 1:
            result['issues'].append(f'{css} has {len(blocks)} lock dialog rules (expected 1).')
    if result['modified_state_present']:
        result['notes'].append('Existing Veilpaper manager state detected. Do not adopt as a new pristine baseline.')
    if result['backup_present']:
        result['notes'].append('A backup exists, but preflight does not certify it as original.')
    if any(c.get('contains_background_image') for c in result['css'].values()):
        result['notes'].append('GDM CSS has an image rule; theme may already be customized.')
    result['notes'].append('Read-only compatibility inspection; NOT authorization to modify a system theme.')
    return result


def show(result):
    print('GDM theme portability preflight (READ-ONLY)')
    print('Resource:', result['path'])
    print('SHA-256:', result['resource_sha256'] or 'unknown')
    print('Resources:', result['resource_count'] if result['resource_count'] is not None else 'unknown')
    for name, data in result['css'].items():
        print(f"{name}: {data['lock_dialog_blocks']} lock-dialog block(s), "
              f"background image CSS: {data['contains_background_image']}")
    print('Managed state present:', result['modified_state_present'])
    print('Backup present:', result['backup_present'])
    for issue in result['issues']:
        print('ISSUE:', issue)
    for note in result['notes']:
        print('NOTE:', note)
    print('Result:', 'STRUCTURE OK; NOT VERIFIED PRISTINE' if not result['issues'] else 'UNSUPPORTED / INSPECTION INCOMPLETE')
    return 0 if not result['issues'] else 1


if __name__ == '__main__':
    raise SystemExit(show(inspect()))
