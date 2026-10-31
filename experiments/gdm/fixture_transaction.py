#!/usr/bin/env python3
"""Disposable-only GDM install/restore transaction simulator.

NEVER writes /usr/share, /var/backups, RPM metadata, or GNOME settings.
This is engineering evidence for a future portable installer, NOT an installer.
All writes are confined to a fresh TemporaryDirectory owned by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

MAX_RESOURCE_BYTES = 64 * 1024 * 1024
MARKER = b'VEILPAPER-DISPOSABLE-GDM-FIXTURE-V1\n'
PHASES = {'install-prepared', 'installed', 'restore-prepared'}


class FixtureError(RuntimeError):
    pass


class InjectedInterruption(FixtureError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise FixtureError(f'Unsafe fixture file type or hardlink: {path.name}')
    if metadata.st_size > MAX_RESOURCE_BYTES:
        raise FixtureError(f'Fixture file exceeds size limit: {path.name}')
    with path.open('rb') as stream:
        return stream.read()


def _sync_dir(folder: Path) -> None:
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(path: Path, data: bytes, mode=0o600):
    if len(data) > MAX_RESOURCE_BYTES:
        raise FixtureError('Fixture output exceeds size limit')
    if path.is_symlink():
        raise FixtureError(f'Symlink destination is forbidden: {path.name}')
    if path.exists():
        _read_regular(path)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix='.veilpaper-fixture-stage-')
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _sync_dir(path.parent)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


class FixtureTransaction:
    """A state-machine deliberately requiring the private fixture marker."""
    def __init__(self, root: Path):
        self.root = Path(root)
        self.active = self.root / 'active.gresource'
        self.base = self.root / 'original.gresource'
        self.candidate = self.root / 'candidate.gresource'
        self.state = self.root / 'intent.json'
        self.marker = self.root / '.veilpaper-fixture-only'
        self.lock = self.root / '.transaction.lock'
        self._guard()

    @classmethod
    def initialize(cls, root: Path, base: bytes, candidate: bytes):
        root = Path(root)
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise FixtureError('Fixture directory must be empty, real, and newly created')
        if not base or not candidate or base == candidate:
            raise FixtureError('Distinct nonempty original and candidate bytes required')
        if max(len(base), len(candidate)) > MAX_RESOURCE_BYTES:
            raise FixtureError('Fixture input exceeds size limit')
        for name, data in [('.veilpaper-fixture-only', MARKER),
                           ('original.gresource', base),
                           ('candidate.gresource', candidate),
                           ('active.gresource', base)]:
            with (root / name).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        _sync_dir(root)
        return cls(root)

    def _guard(self):
        if self.root.is_symlink() or not self.root.is_dir():
            raise FixtureError('Fixture root invalid')
        if _read_regular(self.marker) != MARKER:
            raise FixtureError('Missing disposable fixture marker')
        for path in (self.active, self.base, self.candidate):
            _read_regular(path)
        for path in (self.state, self.lock):
            if os.path.lexists(path):
                _read_regular(path)

    @contextmanager
    def _exclusive(self):
        self._guard()
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if os.fstat(fd).st_nlink != 1:
                raise FixtureError('Unsafe transaction lock')
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._guard()
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _expected(self):
        base, candidate, active = (_read_regular(p) for p in
                                   (self.base, self.candidate, self.active))
        if digest(base) == digest(candidate):
            raise FixtureError('Fixture candidate equals original')
        return digest(base), digest(candidate), digest(active)

    def _load_state(self):
        if not os.path.lexists(self.state):
            return None
        try:
            record = json.loads(_read_regular(self.state))
        except (UnicodeError, ValueError) as error:
            raise FixtureError(f'Corrupt transaction state: {error}') from error
        if not isinstance(record, dict) or set(record) != {'version', 'base', 'candidate', 'phase'}:
            raise FixtureError('Unexpected transaction state schema')
        if record['version'] != 1 or record['phase'] not in PHASES:
            raise FixtureError('Invalid transaction state version or phase')
        return record

    def _record(self, phase: str, base: str, candidate: str):
        if phase not in PHASES:
            raise FixtureError('Invalid phase')
        doc = dict(version=1, base=base, candidate=candidate, phase=phase)
        _atomic_bytes(self.state, json.dumps(doc, sort_keys=True).encode(), 0o600)

    def _clear_state(self):
        if os.path.lexists(self.state):
            _read_regular(self.state)
            self.state.unlink()
            _sync_dir(self.root)

    def status(self):
        with self._exclusive():
            base, candidate, active = self._expected()
            record = self._load_state()
            if record is None:
                if active == base:
                    return 'ORIGINAL'
                raise FixtureError('Active theme differs from original with no transaction state')
            if record['base'] != base or record['candidate'] != candidate:
                raise FixtureError('Transaction state hash mismatch')
            phase = record['phase']
            allowed = {
                ('install-prepared', base): 'INSTALL_INTENT_ONLY',
                ('install-prepared', candidate): 'INSTALL_SWAPPED_NOT_FINALIZED',
                ('installed', candidate): 'INSTALLED',
                ('restore-prepared', candidate): 'RESTORE_INTENT_ONLY',
                ('restore-prepared', base): 'RESTORE_SWAPPED_NOT_FINALIZED',
            }
            result = allowed.get((phase, active))
            if result is None:
                raise FixtureError('Unexpected active hash/transaction phase combination')
            return result

    def apply(self, *, interrupt=None):
        with self._exclusive():
            base, candidate, active = self._expected()
            if self._load_state() is not None or active != base:
                raise FixtureError('Cannot apply over an existing or unknown transaction')
            self._record('install-prepared', base, candidate)
            if interrupt == 'install-intent':
                raise InjectedInterruption(interrupt)
            _atomic_bytes(self.active, _read_regular(self.candidate), 0o644)
            if interrupt == 'install-swap':
                raise InjectedInterruption(interrupt)
            if digest(_read_regular(self.active)) != candidate:
                raise FixtureError('Installed candidate checksum mismatch')
            self._record('installed', base, candidate)

    def restore(self, *, interrupt=None):
        with self._exclusive():
            base, candidate, active = self._expected()
            record = self._load_state()
            if record is None:
                if active == base:
                    return
                raise FixtureError('Cannot restore unknown active theme')
            if record['base'] != base or record['candidate'] != candidate:
                raise FixtureError('Transaction state no longer matches resource hashes')
            phase = record['phase']
            if active == base and phase in ('install-prepared', 'restore-prepared'):
                self._clear_state()
                return
            if active != candidate or phase not in PHASES:
                raise FixtureError('Unknown active theme or invalid transaction phase')
            self._record('restore-prepared', base, candidate)
            if interrupt == 'restore-intent':
                raise InjectedInterruption(interrupt)
            _atomic_bytes(self.active, _read_regular(self.base), 0o644)
            if interrupt == 'restore-swap':
                raise InjectedInterruption(interrupt)
            if digest(_read_regular(self.active)) != base:
                raise FixtureError('Restore hash mismatch')
            self._clear_state()


def _source_bytes(path: Path):
    if path.is_symlink() or not path.is_file():
        raise FixtureError(f'Expected regular, non-symlink input: {path}')
    return _read_regular(path)


def simulate(baseline_path: Path, candidate_path: Path):
    """Create fresh private temporary fixtures; only read supplied input paths."""
    base = _source_bytes(Path(baseline_path).expanduser())
    candidate = _source_bytes(Path(candidate_path).expanduser())
    if base == candidate:
        raise FixtureError('Candidate and baseline must differ')
    scenarios = (
        ('normal-install-and-restore', None, None),
        ('recover-install-intent', 'install-intent', None),
        ('recover-install-swap', 'install-swap', None),
        ('recover-restore-intent', None, 'restore-intent'),
        ('recover-restore-swap', None, 'restore-swap'),
    )
    results = []
    for name, interrupt_install, interrupt_restore in scenarios:
        with tempfile.TemporaryDirectory(prefix='veilpaper-fixture-gdm-') as dirname:
            fixture = FixtureTransaction.initialize(Path(dirname), base, candidate)
            try:
                fixture.apply(interrupt=interrupt_install)
            except InjectedInterruption:
                if interrupt_install is None:
                    raise
            if interrupt_install is None:
                try:
                    fixture.restore(interrupt=interrupt_restore)
                except InjectedInterruption:
                    if interrupt_restore is None:
                        raise
            fixture.restore()
            if fixture.status() != 'ORIGINAL':
                raise FixtureError(f'Fixture did not restore cleanly: {name}')
            results.append(name)
    if _source_bytes(Path(baseline_path).expanduser()) != base or \
            _source_bytes(Path(candidate_path).expanduser()) != candidate:
        raise FixtureError('Read-only input changed during simulation')
    return results


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args(argv)
    for label in simulate(args.baseline, args.candidate):
        print('PASS —', label)
    print('DISPOSABLE ONLY: no real GDM theme, backup, or manager state changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
