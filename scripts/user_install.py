#!/usr/bin/env python3
"""Install a development Veilpaper CLI launcher in a user's home, without sudo.

Copies an explicit allowlist of app source files to ~/.local/lib/veilpaper-dev
and creates ~/.local/bin/veilpaper. Does NOT install/enable GNOME extensions,
replace GDM files, alter wallpaper images, or change any system settings.

Uninstall refuses modified files and never deletes wallpaper data or extensions.
This is experimental development packaging, not a system-wide release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
APP_NAME = 'veilpaper-dev'
APP_FILES = (
    'veilpaper.py',
    'experiments/gdm/fedora_wallpaper_manager_v02.py',
    'experiments/gdm/preflight.py',
    'experiments/gdm/rpm_baseline.py',
    'experiments/gdm/portable_build.py',
    'experiments/gdm/fixture_transaction.py',
    'experiments/gdm/install_review.py',
    'experiments/lockscreen/lockscreen/extension.js',
    'experiments/lockscreen/lockscreen/metadata.json',
)
MANIFEST = 'veilpaper-manifest.json'


class InstallError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _require_user() -> None:
    if os.geteuid() == 0:
        raise InstallError('Never run the user installer with sudo or as root.')


def _regular(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode)


def _paths(prefix: Path):
    prefix = prefix.expanduser().absolute()
    return prefix / 'lib' / APP_NAME, prefix / 'bin' / 'veilpaper'


def _safe_directory(path: Path) -> None:
    if path.is_symlink():
        raise InstallError(f'Refusing symlink directory: {path}')
    if path.exists() and not path.is_dir():
        raise InstallError(f'Expected directory: {path}')


def _launcher(appdir: Path) -> bytes:
    python = Path('/usr/bin/python3') if Path('/usr/bin/python3').is_file() else Path(sys.executable)
    script = appdir / 'veilpaper.py'
    return ('#!/bin/sh\n'
            '# Development-only Veilpaper user launcher.\n'
            'export PYTHONDONTWRITEBYTECODE=1\n'
            f'exec {shlex.quote(str(python))} {shlex.quote(str(script))} "$@"\n').encode()


def _source_files() -> dict[str, Path]:
    found = {}
    for name in APP_FILES:
        path = SOURCE / name
        if path.is_symlink() or not _regular(path):
            raise InstallError(f'Missing or unsafe project source file: {path}')
        found[name] = path
    return found


def _manifest(files: dict[str, Path], launcher: bytes) -> bytes:
    hashes = {name: _hash(source) for name, source in files.items()}
    data = {'format': 1, 'files': hashes, 'launcher_sha256': hashlib.sha256(launcher).hexdigest()}
    return (json.dumps(data, indent=2, sort_keys=True) + '\n').encode()


def inspect(prefix: Path) -> tuple[str, list[str]]:
    appdir, launcher = _paths(prefix)
    if not os.path.lexists(appdir) and not os.path.lexists(launcher):
        return 'NOT_INSTALLED', []
    issues = []
    if appdir.is_symlink() or not appdir.is_dir():
        issues.append('App directory missing, not a directory or is a symlink.')
        return 'INCONSISTENT', issues
    metadata = appdir / MANIFEST
    if not _regular(metadata):
        issues.append('Manifest missing or not a regular file.')
        return 'INCONSISTENT', issues
    try:
        data = json.loads(metadata.read_text())
        if (not isinstance(data, dict) or set(data) != {'format', 'files', 'launcher_sha256'}
                or data['format'] != 1 or
                set(data['files']) != set(APP_FILES) or
                any(not isinstance(h, str) or len(h) != 64 for h in data['files'].values())):
            raise ValueError('Unknown manifest schema')
    except (ValueError, OSError, UnicodeError, TypeError) as error:
        issues.append(f'Invalid manifest: {error}')
        return 'INCONSISTENT', issues

    for name, expected in data['files'].items():
        target = appdir / name
        if not _regular(target):
            issues.append(f'Installed source missing or unsafe: {name}')
        elif _hash(target) != expected:
            issues.append(f'Installed source modified: {name}')
    if not _regular(launcher):
        issues.append('Launcher missing or is not a regular file.')
    elif _hash(launcher) != data['launcher_sha256']:
        issues.append('Launcher differs from installed manifest.')
    return ('INCONSISTENT' if issues else 'INSTALLED'), issues


def install(prefix: Path):
    _require_user()
    prefix = prefix.expanduser().absolute()
    appdir, launcher = _paths(prefix)
    for directory in (prefix, prefix / 'lib', prefix / 'bin'):
        _safe_directory(directory)
    if os.path.lexists(appdir) or os.path.lexists(launcher):
        raise InstallError('Veilpaper installation/launcher already exists; refusing overwrite.')
    files = _source_files()
    (prefix / 'lib').mkdir(parents=True, exist_ok=True)
    (prefix / 'bin').mkdir(parents=True, exist_ok=True)
    _safe_directory(prefix / 'lib')
    _safe_directory(prefix / 'bin')

    stage = Path(tempfile.mkdtemp(prefix='.veilpaper-install-', dir=prefix / 'lib'))
    app_published = False
    try:
        for name, source in files.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
            if _hash(destination) != _hash(source):
                raise InstallError(f'Failed to verify copied file: {name}')
        script = _launcher(appdir)
        (stage / MANIFEST).write_bytes(_manifest(files, script))
        stage.rename(appdir)
        app_published = True

        fd, staged_launcher = tempfile.mkstemp(prefix='.veilpaper-launcher-', dir=prefix / 'bin')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(script)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(staged_launcher, 0o755)
            # Hardlink publication refuses to clobber an existing executable.
            os.link(staged_launcher, launcher)
        finally:
            if os.path.lexists(staged_launcher):
                os.unlink(staged_launcher)
    except BaseException:
        # If the process is killed at the wrong instant, status reports the
        # incomplete installation. Do not delete an existing launcher.
        if app_published and not os.path.lexists(launcher) and appdir.is_dir():
            shutil.rmtree(appdir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(f'Veilpaper user command installed: {launcher}')
    print('Open a new shell or add ~/.local/bin to PATH, then run: veilpaper status')
    print('No GNOME extension, GDM theme, wallpaper or system file was modified.')


def uninstall(prefix: Path):
    _require_user()
    prefix = prefix.expanduser().absolute()
    appdir, launcher = _paths(prefix)
    status, errors = inspect(prefix)
    if status != 'INSTALLED':
        raise InstallError(f'Cannot safely uninstall: {status}; {"; ".join(errors)}')
    # Delete only allowlisted files; refuse unrecognized contents (except
    # cached Python bytecode generated by an installed interpreter).
    allowed_dirs = {'experiments', 'experiments/gdm', 'experiments/lockscreen',
                    'experiments/lockscreen/lockscreen'}
    for item in appdir.rglob('*'):
        relative = item.relative_to(appdir).as_posix()
        if item.is_symlink():
            raise InstallError(f'Unexpected symlink in app files: {relative}')
        if item.is_dir():
            if relative not in allowed_dirs:
                raise InstallError(f'Unexpected directory in installation: {relative}')
        elif relative not in APP_FILES and relative != MANIFEST:
            raise InstallError(f'Unexpected file in installation: {relative}')
    # Exact verified installer-owned files only. Wallpaper data is elsewhere.
    launcher.unlink()
    for name in APP_FILES:
        (appdir / name).unlink()
    (appdir / MANIFEST).unlink()
    for directory in sorted(allowed_dirs, key=lambda s: s.count('/'), reverse=True):
        (appdir / directory).rmdir()
    appdir.rmdir()
    print('Removed Veilpaper user launcher and its installed source.')
    print('Existing login wallpaper, lock wallpaper, GNOME extension and backups remain untouched.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'uninstall'))
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local',
                        help='User prefix (default: ~/.local; useful for isolated tests)')
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            install(args.prefix)
        elif args.action == 'uninstall':
            uninstall(args.prefix)
        else:
            status, errors = inspect(args.prefix)
            print('Veilpaper user installation:', status)
            for error in errors:
                print('ISSUE:', error)
            return 0 if status in ('INSTALLED', 'NOT_INSTALLED') else 1
    except (OSError, InstallError, ValueError) as error:
        print('ERROR:', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
