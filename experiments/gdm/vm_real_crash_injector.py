#!/usr/bin/env python3
"""DISPOSABLE-FEDORA-VM-ONLY: SIGKILL real theme install after durable swap.

Not a supported installer or recovery tool. The normal transaction API has no
failure-injection flags. The injector requires both root-owned VM markers and
exact confirmation from vm_real_transaction.

Only one checkpoint: after candidate real resource rename and parent-dir fsync,
before final installed journal publication. Caller must independently verify
SIGKILL, install-prepared journal, and candidate bytes before restoring in VM.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import signal
import sys

HERE = Path(__file__).resolve().parent


def _load_txn():
    spec = importlib.util.spec_from_file_location(
        'veilpaper_vm_real_crash_txn', HERE / 'vm_real_transaction.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('VM-only transaction engine unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inject_install_swap(txn, candidate):
    """Revalidate VM-only authorization then crash AFTER actual durable swap."""
    txn.gate()
    original_atomic = txn._atomic

    def crash_after_durable_swap(path, data, **kwargs):
        original_atomic(path, data, **kwargs)
        if Path(path) == txn.THEME:
            os.kill(os.getpid(), signal.SIGKILL)

    txn._atomic = crash_after_durable_swap
    txn.install(Path(candidate))
    raise RuntimeError('Expected SIGKILL after actual theme swap did not occur')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', choices=('install-swap',))
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args(argv)
    try:
        txn = _load_txn()
        if args.confirm != txn.PHRASE:
            raise RuntimeError('Exact disposable-VM-only write phrase missing')
        inject_install_swap(txn, args.candidate)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
