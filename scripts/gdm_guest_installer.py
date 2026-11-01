#!/usr/bin/env python3
"""Veilpaper GDM guest installer controller — disposable Fedora 44 VM ONLY.

Operational install/restore orchestration over the existing, previously
qualified VM transaction engine. No new filesystem writer is introduced.
This entrypoint is deliberately *not* an end-user production helper:
actual GDM writes require BOTH root-owned VM markers, a full Fedora 44 VM,
an exact manual confirmation phrase, and verified bytes inside the lock.
Never provision VM test markers on a physical workstation.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import sys

TRANSACTION = Path(__file__).resolve().parents[1] / 'experiments/gdm/vm_real_transaction.py'
CONFIRM = 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
_HEX = re.compile(r'[0-9a-f]{64}\Z')


class GuestInstallBlocked(RuntimeError):
    pass


def _engine():
    spec = importlib.util.spec_from_file_location('veilpaper_guest_installer_txn', TRANSACTION)
    if spec is None or spec.loader is None:
        raise GuestInstallBlocked('Qualified disposable VM transaction engine is missing.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(action, *, candidate=None, expected_sha256, confirm):
    """Invoke only a VM-qualified transaction with an exact-action digest.

    This program cannot grant approval, migrate prior customizations, or
    invoke a host production installer. It never restarts GDM automatically.
    The independent transaction itself performs the locked hash recheck.
    """
    if confirm != CONFIRM:
        raise GuestInstallBlocked('Exact disposable-VM authorization phrase required.')
    if not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256):
        raise GuestInstallBlocked('Exact lowercase 64-character SHA-256 required.')
    if action not in ('install', 'restore'):
        raise GuestInstallBlocked('Unsupported action; only install or restore.')
    if action == 'install' and candidate is None:
        raise GuestInstallBlocked('Install requires an explicit candidate path.')
    if action == 'restore' and candidate is not None:
        raise GuestInstallBlocked('Restore must not supply a candidate.')

    transaction = _engine()
    # Gate BEFORE reading the candidate or GDM theme. This checks root, a
    # full Fedora 44 VM and both separate root-owned marker files.
    transaction.gate()
    if action == 'install':
        outcome = transaction.install(
            Path(candidate), expected_candidate_sha256=expected_sha256)
        if outcome != 'VM_REAL_GDM_INSTALLED':
            raise GuestInstallBlocked('Unexpected installation result; check guest transaction.')
        return outcome
    outcome = transaction.restore(expected_active_sha256=expected_sha256)
    if outcome != 'VM_REAL_GDM_RESTORED':
        raise GuestInstallBlocked('Unexpected restore result; check guest transaction.')
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    install = sub.add_parser('install', help='Exact-hash install inside marked VM only')
    install.add_argument('--candidate', type=Path, required=True)
    install.add_argument('--sha256', required=True, help='Exact candidate SHA-256')
    install.add_argument('--confirm', required=True)
    restore = sub.add_parser('restore', help='Exact-hash restoration inside marked VM only')
    restore.add_argument('--active-sha256', required=True,
                         help='SHA-256 of the currently active GDM theme')
    restore.add_argument('--confirm', required=True)
    args = parser.parse_args(argv)
    try:
        outcome = execute(
            args.action,
            candidate=args.candidate if args.action == 'install' else None,
            expected_sha256=args.sha256 if args.action == 'install' else args.active_sha256,
            confirm=args.confirm)
    except (GuestInstallBlocked, RuntimeError, OSError, ValueError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1
    print(outcome)
    print('DISPOSABLE VM ONLY: operator must verify the graphical greeter separately.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
