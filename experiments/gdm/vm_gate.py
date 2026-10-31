#!/usr/bin/env python3
"""Read-only disposable Fedora 44 VM admission for future GDM write trials.

This tool deliberately has NO live-install capability. VM qualification is not
inferred from an ordinary user flag: an operator must provision a root-owned,
non-symlink marker *inside* a disposable full VM and call this explicitly.
The GDM/backup/state paths are only ever read. All transaction writes occur
inside TemporaryDirectory fixtures from fixture_transaction.simulate().
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parent
MARKER = Path('/etc/veilpaper-disposable-vm-qualification')
MARKER_BYTES = b'VEILPAPER-DISPOSABLE-FEDORA44-VM-ONLY\n'
THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')
STATE = Path('/var/backups/fedora-gdm-wallpaper/manager-state.json')
FEDORA_RELEASE = Path('/etc/fedora-release')


class QualificationBlocked(RuntimeError):
    pass


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, REPO / file)
    if spec is None or spec.loader is None:
        raise QualificationBlocked(f'Qualification helper unavailable: {file}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
        raise QualificationBlocked(f'VM environment check failed: {error}') from error
    return result.returncode


def guard_vm(*, marker=MARKER, release=FEDORA_RELEASE):
    """Must pass BEFORE reading candidate or touching any transaction tooling."""
    if os.geteuid() != 0:
        raise QualificationBlocked('Qualification must run as root INSIDE the disposable VM.')
    if _run('systemd-detect-virt', '--vm', '--quiet') != 0:
        raise QualificationBlocked('Full hardware VM not detected (host or container is forbidden).')
    if _run('systemd-detect-virt', '--container', '--quiet') == 0:
        raise QualificationBlocked('Container context is forbidden; a disposable full VM is required.')
    try:
        if 'Fedora release 44' not in release.read_text():
            raise QualificationBlocked('Only an isolated Fedora 44 VM is qualified.')
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or (info.st_mode & 0o777) != 0o600 or info.st_nlink != 1:
            raise QualificationBlocked('Disposable VM marker must be root-owned, mode 0600, single-link regular file.')
        if marker.read_bytes() != MARKER_BYTES:
            raise QualificationBlocked('Disposable VM marker has invalid content.')
    except (OSError, UnicodeError) as error:
        raise QualificationBlocked(f'Disposable VM proof unavailable: {error}') from error


def qualification(candidate: Path):
    """Require stock RPM + precise candidate diff, then simulate recovery."""
    candidate = Path(candidate)
    if candidate.is_symlink() or not candidate.is_file():
        raise QualificationBlocked('Candidate must be a real, regular file inside the VM.')
    if BACKUP.exists() or BACKUP.is_symlink() or STATE.exists() or STATE.is_symlink():
        raise QualificationBlocked('Backup or manager state already exists: first-time VM qualification only.')
    review = _load('veilpaper_vm_install_review', 'install_review.py')
    trial = _load('veilpaper_vm_transaction_sim', 'fixture_transaction.py')
    report = review.review(candidate, theme=THEME, backup=BACKUP, state=STATE)
    if report['verdict'] != 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW':
        raise QualificationBlocked('Read-only installation review blocked: ' + '; '.join(report['issues']))
    original_sha = hashlib.sha256(THEME.read_bytes()).hexdigest()
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    scenarios = trial.simulate(THEME, candidate)
    if scenarios != [
        'normal-install-and-restore',
        'recover-install-intent',
        'recover-install-swap',
        'recover-restore-intent',
        'recover-restore-swap',
    ]:
        raise QualificationBlocked('Unexpected recovery scenarios; refusing qualification.')
    if (hashlib.sha256(THEME.read_bytes()).hexdigest() != original_sha or
            hashlib.sha256(candidate.read_bytes()).hexdigest() != candidate_sha):
        raise QualificationBlocked('Read-only inputs changed during qualification.')
    if BACKUP.exists() or BACKUP.is_symlink() or STATE.exists() or STATE.is_symlink():
        raise QualificationBlocked('Unexpected GDM backup/state after read-only qualification.')
    return {
        'verdict': 'VM_READ_ONLY_ADMISSION_PASS',
        'original_sha256': original_sha,
        'candidate_sha256': candidate_sha,
        'resource': report['added_resource'],
        'recovery_scenarios': scenarios,
        'install_performed': False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--confirm', required=True,
                   help='Must be exactly: DISPOSABLE FEDORA 44 VM')
    args = p.parse_args(argv)
    try:
        if args.confirm != 'DISPOSABLE FEDORA 44 VM':
            raise QualificationBlocked('Explicit disposable VM phrase does not match.')
        guard_vm()
        result = qualification(args.candidate)
        for key, value in result.items():
            print(f'{key}: {value}')
        print('READ-ONLY PASS. Real installation/restore and GUI enablement remain blocked.')
        return 0
    except (QualificationBlocked, OSError, RuntimeError, ValueError) as error:
        print(f'BLOCKED: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
