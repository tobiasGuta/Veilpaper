#!/usr/bin/env python3
"""Crash-process recovery probe for Veilpaper's disposable GDM journal.

Unlike the older exception-only fixture tests, this forks a child and kills it
with SIGKILL immediately after a durable journal or resource swap. A new
transaction instance then recovers the ORIGINAL bytes.

This tool has NO path to modify live GDM. Only fresh TemporaryDirectory
fixtures are writable, populated from read-only user-provided inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location(
        'veilpaper_crash_fixture', HERE / 'fixture_transaction.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Fixture transaction engine unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CASES = (
    ('install-intent-kill', 'apply', 'install-intent', 'INSTALL_INTENT_ONLY'),
    ('install-swap-kill', 'apply', 'install-swap', 'INSTALL_SWAPPED_NOT_FINALIZED'),
    ('restore-intent-kill', 'restore', 'restore-intent', 'RESTORE_INTENT_ONLY'),
    ('restore-swap-kill', 'restore', 'restore-swap', 'RESTORE_SWAPPED_NOT_FINALIZED'),
)


def _kill_at_checkpoint(fixture, operation: str, checkpoint: str, engine):
    pid = os.fork()
    if pid == 0:
        # Child performs the real fsynced write, then immediately dies. It
        # must never perform a graceful cleanup in the child process.
        try:
            try:
                getattr(fixture, operation)(interrupt=checkpoint)
            except engine.InjectedInterruption:
                os.kill(os.getpid(), signal.SIGKILL)
        except BaseException as error:
            print(f'Child failed unexpectedly: {error}', file=sys.stderr, flush=True)
        os._exit(91)
    waited, status = os.waitpid(pid, 0)
    if waited != pid or not os.WIFSIGNALED(status) or os.WTERMSIG(status) != signal.SIGKILL:
        raise RuntimeError(
            f'Expected SIGKILL at {checkpoint}; child status was {status}')


def probe(original: Path, candidate: Path):
    if os.geteuid() == 0:
        raise RuntimeError('Run crash recovery probe as a normal user, not with sudo')
    if not hasattr(os, 'fork'):
        raise RuntimeError('Only supported on a POSIX/Linux host')
    engine = _load()
    original = Path(original).expanduser()
    candidate = Path(candidate).expanduser()
    base = engine._source_bytes(original)
    target = engine._source_bytes(candidate)
    if not base or not target or base == target:
        raise RuntimeError('Two distinct nonempty regular source files are required')
    base_sha, candidate_sha = (
        hashlib.sha256(base).hexdigest(), hashlib.sha256(target).hexdigest())

    results = []
    for label, operation, checkpoint, expected in CASES:
        with tempfile.TemporaryDirectory(prefix='veilpaper-kill-fixture-') as name:
            root = Path(name)
            fixture = engine.FixtureTransaction.initialize(root, base, target)
            if operation == 'restore':
                fixture.apply()
                if fixture.status() != 'INSTALLED':
                    raise RuntimeError('Fixture did not reach installed state')
            _kill_at_checkpoint(fixture, operation, checkpoint, engine)
            # A newly constructed handler must infer the durable state from
            # files on disk; no in-memory child state survives the SIGKILL.
            recovered = engine.FixtureTransaction(root)
            current = recovered.status()
            if current != expected:
                raise RuntimeError(f'{label}: expected {expected}, found {current}')
            recovered.restore()
            if recovered.status() != 'ORIGINAL':
                raise RuntimeError(f'{label}: recovery did not reach ORIGINAL')
            if root.joinpath('active.gresource').read_bytes() != base:
                raise RuntimeError(f'{label}: original resource was not recovered')
            if root.joinpath('original.gresource').read_bytes() != base:
                raise RuntimeError(f'{label}: backup changed unexpectedly')
            if root.joinpath('candidate.gresource').read_bytes() != target:
                raise RuntimeError(f'{label}: candidate changed unexpectedly')
            if root.joinpath('intent.json').exists():
                raise RuntimeError(f'{label}: transaction intent survived recovery')
            results.append(label)

    # Verify the caller's source files are still unchanged after all crashes.
    if (hashlib.sha256(engine._source_bytes(original)).hexdigest() != base_sha or
            hashlib.sha256(engine._source_bytes(candidate)).hexdigest() != candidate_sha):
        raise RuntimeError('Original or candidate read-only source changed')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path, help='Read-only original input resource')
    parser.add_argument('candidate', type=Path, help='Read-only candidate input resource')
    args = parser.parse_args(argv)
    try:
        for label in probe(args.original, args.candidate):
            print('PASS —', label)
        print('SIGKILL PROBE PASS — all crash/restoration work confined to temporary fixture directories')
        print('NO LIVE GDM WRITES OR REBOOTS OCCURRED')
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print('BLOCKED:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
