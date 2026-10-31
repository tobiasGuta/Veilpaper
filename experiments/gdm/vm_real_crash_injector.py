#!/usr/bin/env python3
"""Disposable Fedora 44 VM ONLY: SIGKILL real GDM transaction checkpoints.

NOT a general installer. Normal production transaction code has NO crash
switch. This separate injector requires the VM's two root-owned marker files,
Fedora 44 VM gate, and exact explicit VM-only confirmation on every call.

Kill *after durable publication* of a specified journal phase or actual
resource swap. The caller must independently verify SIGKILL, hashes, metadata,
journal and backup; reboot and restore inside the disposable guest.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import signal
import sys

HERE = Path(__file__).resolve().parent

CHECKPOINTS = ('install-intent', 'install-swap',
               'restore-intent', 'restore-swap')


def _load_txn():
    spec = importlib.util.spec_from_file_location(
        'veilpaper_vm_real_crash_txn', HERE / 'vm_real_transaction.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('VM-only transaction engine unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inject_checkpoint(txn, checkpoint, candidate=None):
    """Revalidate VM authorization, then die only at the selected checkpoint."""
    if checkpoint not in CHECKPOINTS:
        raise RuntimeError('Unknown or unsupported crash checkpoint')
    is_install = checkpoint.startswith('install-')
    if is_install and candidate is None:
        raise RuntimeError('Installation crash requires a candidate')
    if not is_install and candidate is not None:
        raise RuntimeError('Restoration crash forbids candidate')

    txn.gate()  # Gate first, even before monkeypatching an internal function.
    if checkpoint.endswith('-intent'):
        original_record = txn._write_state
        phase = 'install-prepared' if is_install else 'restore-prepared'

        def persist_then_kill(record):
            original_record(record)  # includes atomic journal fsync
            if record.get('phase') == phase:
                os.kill(os.getpid(), signal.SIGKILL)

        txn._write_state = persist_then_kill
    else:
        original_atomic = txn._atomic

        def swap_then_kill(path, data, **kwargs):
            original_atomic(path, data, **kwargs)  # fsyncs parent directory
            if Path(path) == txn.THEME:
                os.kill(os.getpid(), signal.SIGKILL)

        txn._atomic = swap_then_kill

    if is_install:
        txn.install(Path(candidate))
    else:
        txn.restore()
    raise RuntimeError(f'Expected SIGKILL at {checkpoint} did not occur')


def inject_install_swap(txn, candidate):
    """Backward-compatible narrow name for previous post-install swap proof."""
    return inject_checkpoint(txn, 'install-swap', candidate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', choices=CHECKPOINTS)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args(argv)
    try:
        txn = _load_txn()
        if args.confirm != txn.PHRASE:
            raise RuntimeError('Exact disposable-VM-only write phrase missing')
        inject_checkpoint(txn, args.checkpoint, args.candidate)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
