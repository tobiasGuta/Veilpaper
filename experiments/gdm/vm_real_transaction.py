#!/usr/bin/env python3
"""EXPERIMENTAL REAL GDM TRANSACTION — disposable Fedora 44 full VM ONLY.

NOT a general installer, not part of the GUI, not intended for a laptop.
Requires two distinct root-owned 0600 markers, exact human-supplied phrase,
full Fedora 44 VM, pristine RPM theme, and no prior Veilpaper installation.
The lab journal and verified original backup live in a dedicated root-only
directory and are retained after restoration. Does not restart GDM.

First slice: clean install -> persisted installed phase -> verified restore.
SIGKILL/real-reboot qualification is a separate next step.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

HERE = Path(__file__).resolve().parent
THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
LAB = Path('/var/lib/veilpaper-disposable-gdm-transaction')
LEGACY_BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')
LEGACY_STATE = Path('/var/backups/fedora-gdm-wallpaper/manager-state.json')
WRITE_MARKER = Path('/etc/veilpaper-disposable-vm-GDM-write-test')
WRITE_BYTES = b'VEILPAPER-REAL-GDM-WRITES-IN-DISPOSABLE-VM-ONLY\n'
PHRASE = 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
MAX_CANDIDATE = 96 * 1024 * 1024


class LabBlocked(RuntimeError):
    pass


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if not spec or not spec.loader:
        raise LabBlocked(f'Missing qualification helper: {filename}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _regular(path, *, max_bytes=MAX_CANDIDATE):
    try:
        info = path.lstat()
    except OSError as exc:
        raise LabBlocked(f'Cannot inspect {path}: {exc}') from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_size <= 0 or info.st_size > max_bytes):
        raise LabBlocked(f'Unsafe file type, size, or hardlink: {path}')
    return info


def _bytes(path):
    info = _regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise LabBlocked('Input file changed while opening')
        data = bytearray()
        while len(data) <= MAX_CANDIDATE:
            part = os.read(fd, min(1024 * 1024, MAX_CANDIDATE + 1 - len(data)))
            if not part:
                break
            data.extend(part)
        if len(data) != opened.st_size or len(data) > MAX_CANDIDATE:
            raise LabBlocked('Input file size changed during read')
        return bytes(data)
    finally:
        os.close(fd)


def _sync_dir(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path, data, *, mode=0o600, owner=None, xattrs=None):
    """Atomic durable publication on same filesystem as destination."""
    if path.is_symlink():
        raise LabBlocked(f'Refusing symlink destination: {path}')
    fd, stage = tempfile.mkstemp(prefix='.veilpaper-vm-stage-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(stage, mode)
        if owner is not None:
            os.chown(stage, *owner)
        for name, value in (xattrs or {}).items():
            os.setxattr(stage, name, value)
        # Metadata and label changes also precede the atomic swap.
        with open(stage, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(stage, path)
        _sync_dir(path.parent)
    finally:
        if os.path.lexists(stage):
            os.unlink(stage)


def _metadata(theme):
    info = _regular(theme)
    # Preserve exact SELinux label and all currently readable xattrs.
    attrs = {name: os.getxattr(theme, name) for name in os.listxattr(theme)}
    return {'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode), 'xattrs': attrs}


def _verify_meta(theme, meta):
    info = _regular(theme)
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
            meta['uid'], meta['gid'], meta['mode']):
        raise LabBlocked('Theme uid/gid/mode changed unexpectedly')
    if {name: os.getxattr(theme, name) for name in os.listxattr(theme)} != meta['xattrs']:
        raise LabBlocked('Theme SELinux/xattr metadata differs from original')


def _check_marker():
    info = _regular(WRITE_MARKER, max_bytes=256)
    if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or
            _bytes(WRITE_MARKER) != WRITE_BYTES):
        raise LabBlocked('Missing or unsafe independent VM-only GDM write marker')


def gate():
    # The original gate requires root, full VM, Fedora 44 and the FIRST marker.
    vm = _load('veilpaper_real_vm_guard', 'vm_gate.py')
    vm.guard_vm()
    _check_marker()
    for path in (LEGACY_BACKUP, LEGACY_STATE):
        if os.path.lexists(path):
            raise LabBlocked(f'Existing legacy Veilpaper customization: {path}')


def _lab():
    if LAB.is_symlink():
        raise LabBlocked('Lab directory is a symlink')
    if not LAB.exists():
        LAB.mkdir(mode=0o700)
        _sync_dir(LAB.parent)
    info = LAB.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or
            stat.S_IMODE(info.st_mode) != 0o700):
        raise LabBlocked('Lab directory must be root-owned and mode 0700')


@contextmanager
def _locked():
    _lab()
    lock = LAB / 'lock'
    if lock.is_symlink():
        raise LabBlocked('Transaction lock is a symlink')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_nlink != 1:
            raise LabBlocked('Unsafe transaction lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _state():
    path = LAB / 'state.json'
    if not os.path.lexists(path):
        return None
    try:
        record = json.loads(_bytes(path))
    except (ValueError, UnicodeError) as exc:
        raise LabBlocked(f'Unparseable transaction state: {exc}') from exc
    expected = {'version', 'phase', 'base', 'candidate', 'uid', 'gid', 'mode',
                'selinux_hex', 'resource'}
    if (not isinstance(record, dict) or set(record) != expected or
            record['version'] != 1 or
            record['phase'] not in ('install-prepared', 'installed',
                                    'restore-prepared', 'restored') or
            not all(isinstance(record[key], str) and len(record[key]) == 64
                    for key in ('base', 'candidate'))):
        raise LabBlocked('Unexpected transaction state schema')
    return record


def _write_state(record):
    _atomic(LAB / 'state.json', json.dumps(record, sort_keys=True).encode(), mode=0o600)


def _meta_from_state(record):
    # This prototype requires the baseline theme to have zero or one SELinux
    # security label xattr; if other attrs exist, fail rather than discard them.
    attrs = {}
    if record['selinux_hex']:
        attrs['security.selinux'] = bytes.fromhex(record['selinux_hex'])
    return {'uid': record['uid'], 'gid': record['gid'],
            'mode': record['mode'], 'xattrs': attrs}


def _record(base, candidate, meta, resource):
    attrs = meta['xattrs']
    if set(attrs).difference({'security.selinux'}):
        raise LabBlocked('Unexpected theme xattrs; refusing to lose metadata')
    return {'version': 1, 'phase': 'install-prepared',
            'base': _sha(base), 'candidate': _sha(candidate),
            'uid': meta['uid'], 'gid': meta['gid'], 'mode': meta['mode'],
            'selinux_hex': attrs.get('security.selinux', b'').hex(),
            'resource': resource}


def install(candidate):
    candidate = Path(candidate)
    with _locked():
        if _state() is not None or (LAB / 'original.gresource').exists():
            raise LabBlocked('Existing VM lab transaction; refusing repeated install')
        if THEME.is_symlink():
            raise LabBlocked('Theme is a symlink')
        meta = _metadata(THEME)
        if meta['uid'] != 0:
            raise LabBlocked('Packaged GDM theme is not root-owned')
        reviewer = _load('veilpaper_real_install_review', 'install_review.py')
        report = reviewer.review(candidate, theme=THEME,
                                 backup=LEGACY_BACKUP, state=LEGACY_STATE)
        if report['verdict'] != 'STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW':
            raise LabBlocked('First-time install review blocked: ' + '; '.join(report['issues']))
        pristine = _bytes(THEME)
        selected = _bytes(candidate)
        if _sha(pristine) != report['active_sha256'] or _sha(selected) != report['candidate_sha256']:
            raise LabBlocked('Theme or candidate changed after first-time review')
        record = _record(pristine, selected, meta, report['added_resource'])
        # Immutable original backup is written and synced before *any* journal
        # or active GDM theme replacement. Never overwrite preexisting backup.
        backup = LAB / 'original.gresource'
        if os.path.lexists(backup):
            raise LabBlocked('Original backup already exists')
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(pristine)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_dir(LAB)
        if _sha(_bytes(backup)) != record['base']:
            raise LabBlocked('Durable original backup mismatch')
        _write_state(record)  # install-prepared, durable journal
        # One atomic rename in package directory; never changes unrelated files.
        _atomic(THEME, selected, mode=meta['mode'],
                owner=(meta['uid'], meta['gid']), xattrs=meta['xattrs'])
        if _sha(_bytes(THEME)) != record['candidate']:
            raise LabBlocked('Candidate checksum mismatch after swap')
        _verify_meta(THEME, meta)
        record['phase'] = 'installed'
        _write_state(record)
        return 'VM_REAL_GDM_INSTALLED'


def restore():
    with _locked():
        record = _state()
        if record is None:
            raise LabBlocked('No durable transaction journal; manual snapshot recovery required')
        meta = _meta_from_state(record)
        backup = LAB / 'original.gresource'
        base = _bytes(backup)
        if _sha(base) != record['base']:
            raise LabBlocked('Original backup corrupted; refusing restore')
        current = _sha(_bytes(THEME))
        phase = record['phase']
        if current == record['base'] and phase in ('install-prepared', 'restore-prepared', 'restored'):
            record['phase'] = 'restored'
            _write_state(record)
            _verify_meta(THEME, meta)
            return 'VM_REAL_GDM_RESTORED'
        if current != record['candidate'] or phase not in (
                'install-prepared', 'installed', 'restore-prepared'):
            raise LabBlocked('Unknown active GDM resource; refusing to overwrite')
        _verify_meta(THEME, meta)
        record['phase'] = 'restore-prepared'
        _write_state(record)
        _atomic(THEME, base, mode=meta['mode'],
                owner=(meta['uid'], meta['gid']), xattrs=meta['xattrs'])
        if _sha(_bytes(THEME)) != record['base']:
            raise LabBlocked('Restored GDM checksum mismatch')
        _verify_meta(THEME, meta)
        record['phase'] = 'restored'
        _write_state(record)
        return 'VM_REAL_GDM_RESTORED'


def status():
    with _locked():
        record = _state()
        if not record:
            return 'NO_TRANSACTION'
        base = _bytes(LAB / 'original.gresource')
        if _sha(base) != record['base']:
            raise LabBlocked('Backup corruption')
        active = _sha(_bytes(THEME))
        if active not in (record['base'], record['candidate']):
            raise LabBlocked('Unknown active GDM resource')
        return f"{record['phase']}: active={'original' if active == record['base'] else 'candidate'}"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('install', 'restore', 'status'))
    p.add_argument('--candidate', type=Path)
    p.add_argument('--confirm', required=True)
    args = p.parse_args(argv)
    try:
        if args.confirm != PHRASE:
            raise LabBlocked('VM-only write confirmation phrase missing')
        gate()
        if args.action == 'install':
            if args.candidate is None:
                raise LabBlocked('--candidate is required for installation')
            outcome = install(args.candidate)
        elif args.action == 'restore':
            outcome = restore()
        else:
            outcome = status()
        print(outcome)
        print('DISPOSABLE VM ONLY. This tool is not a general installer.')
        return 0
    except (LabBlocked, OSError, ValueError, RuntimeError) as error:
        print(f'BLOCKED: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
