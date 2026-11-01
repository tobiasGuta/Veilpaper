#!/usr/bin/python3
"""Install the root-owned Veilpaper helper *inside a qualified disposable VM*.

This never installs a real-host product helper and never changes GDM resources.
Both independent root-owned VM-only markers and the full Fedora 44 VM gate
must pass BEFORE any directory/policy write. Run manually in a throwaway VM
with an operator-owned snapshot, never on a physical laptop.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEST = Path('/usr/libexec/veilpaper-guest')
POLICY_DEST = Path('/usr/share/polkit-1/actions/me.tobiasguta.Veilpaper.Guest.policy')
POLICY_SOURCE = ROOT / 'packaging/me.tobiasguta.Veilpaper.Guest.policy'
BUNDLE = (
    'scripts/gdm_guest_installer.py',
    'experiments/gdm/vm_real_transaction.py',
    'experiments/gdm/vm_gate.py',
    'experiments/gdm/install_review.py',
    'experiments/gdm/rpm_baseline.py',
    'experiments/gdm/fedora_wallpaper_manager_v02.py',
)


class ProvisionBlocked(RuntimeError):
    pass


def _admit():
    path = ROOT / 'experiments/gdm/vm_real_transaction.py'
    spec = importlib.util.spec_from_file_location('veilpaper_guest_provision_gate', path)
    if spec is None or spec.loader is None:
        raise ProvisionBlocked('Disposable-VM safety gate missing.')
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.gate()


def _check_source(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size == 0 or info.st_size > 1024 * 1024):
        raise ProvisionBlocked(f'Invalid guest helper source file: {path.name}')


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def provision():
    _admit()  # Must always run before ANY writes.
    if os.path.lexists(DEST) or os.path.lexists(POLICY_DEST):
        raise ProvisionBlocked('VM helper or policy already exists; no overwrite.')
    for parent in (DEST.parent, POLICY_DEST.parent):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022):
            raise ProvisionBlocked('Root-owned system installation directory is unsafe.')
    for label in BUNDLE:
        _check_source(ROOT / label)
    _check_source(POLICY_SOURCE)

    # Private staging on the destination filesystem; publish a fresh,
    # exclusively reserved directory only once all files are fully copied.
    staging = Path(tempfile.mkdtemp(prefix='.veilpaper-guest-stage-', dir=DEST.parent))
    installed = False
    try:
        for label in BUNDLE:
            dest = staging / label
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / label, dest)
            dest.chmod(0o755 if label == 'scripts/gdm_guest_installer.py' else 0o644)
            with dest.open('rb') as stream:
                os.fsync(stream.fileno())
        for directory in sorted(
                (p for p in staging.rglob('*') if p.is_dir()),
                key=lambda p: len(p.parts), reverse=True):
            directory.chmod(0o755)
            _sync(directory)
        staging.chmod(0o755)
        _sync(staging)
        if os.path.lexists(DEST):
            raise ProvisionBlocked('Guest helper path appeared while preparing; no overwrite.')
        staging.rename(DEST)
        installed = True
        _sync(DEST.parent)

        policy_bytes = POLICY_SOURCE.read_bytes()
        fd = os.open(POLICY_DEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(policy_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        _sync(POLICY_DEST.parent)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    if not installed:
        raise ProvisionBlocked('Guest helper provisioning did not complete.')
    print('VM helper and Polkit action provisioned ONLY inside marked disposable VM.')
    print('This is not permission to change a physical host login screen.')


def main():
    try:
        provision()
    except (ProvisionBlocked, OSError, RuntimeError, ValueError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
