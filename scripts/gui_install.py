#!/usr/bin/env python3
"""Install the Veilpaper GUI in the user's Applications menu (experimental).

Standalone add-on to the existing Veilpaper CLI installation. The copied GUI
reuses the Veilpaper CLI backend; no GUI file is written to /usr/share or GDM.
Does not enable/disable GNOME extensions or alter wallpapers. No sudo.
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

PROJECT = Path(__file__).resolve().parents[1]
APP = 'veilpaper-gui-dev'
DESKTOP = 'me.tobiasguta.Veilpaper.desktop'
FILES = (
    'gui/backend.py',
    'gui/veilpaper_gui.py',
    'veilpaper.py',
    'experiments/gdm/fedora_wallpaper_manager_v02.py',
    'experiments/gdm/rpm_baseline.py',
)
MANIFEST = 'gui-install-manifest.json'


class GUIInstallError(RuntimeError):
    pass


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _is_regular(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _paths(prefix):
    prefix = Path(prefix).expanduser().absolute()
    return (
        prefix / 'lib' / APP,
        prefix / 'bin/veilpaper-gui',
        prefix / 'share/applications' / DESKTOP,
    )


def _verify_user():
    if os.geteuid() == 0:
        raise GUIInstallError('Run the GUI installer as your normal user, never with sudo.')


def _check_directory(directory):
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise GUIInstallError(f'Unsafe install directory: {directory}')


def _launcher(appdir):
    python = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else sys.executable
    return (
        '#!/bin/sh\n'
        '# Veilpaper native GNOME GUI launcher (user install)\n'
        'export PYTHONDONTWRITEBYTECODE=1\n'
        f'exec {shlex.quote(python)} '
        f'{shlex.quote(str(appdir / "gui/veilpaper_gui.py"))} "$@"\n'
    ).encode()


def _desktop(launcher):
    # Desktop Entry Exec quoting differs from shell. Refuse paths with control
    # characters rather than generate ambiguous or unsafe desktop fields.
    path = str(launcher)
    if any(ord(c) < 32 for c in path):
        raise GUIInstallError('Unsupported control character in launcher path.')
    path = path.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Version=1.0\n'
        'Name=Veilpaper\n'
        'Comment=Independent GNOME lock-screen and login wallpaper manager\n'
        f'Exec="{path}"\n'
        'Icon=preferences-desktop-wallpaper\n'
        'Terminal=false\n'
        'StartupNotify=true\n'
        'Categories=Settings;Utility;\n'
    ).encode()


def _expected():
    srcs = {}
    for name in FILES:
        source = PROJECT / name
        if source.is_symlink() or not _is_regular(source):
            raise GUIInstallError(f'Invalid GUI installation source: {source}')
        srcs[name] = source
    return srcs


def _manifest(files, launcher, desktop):
    return (json.dumps({
        'format': 1,
        'files': {name: _hash(src) for name, src in files.items()},
        'launcher': hashlib.sha256(launcher).hexdigest(),
        'desktop': hashlib.sha256(desktop).hexdigest(),
    }, indent=2, sort_keys=True) + '\n').encode()


def check(prefix):
    appdir, launcher, desktop = _paths(prefix)
    if not any(os.path.lexists(p) for p in (appdir, launcher, desktop)):
        return 'NOT_INSTALLED', []
    errors = []
    if appdir.is_symlink() or not appdir.is_dir():
        return 'INCONSISTENT', ['GUI app bundle is missing or unsafe.']
    path = appdir / MANIFEST
    if not _is_regular(path):
        return 'INCONSISTENT', ['GUI install manifest is missing or unsafe.']
    try:
        data = json.loads(path.read_text())
        if (set(data) != {'format', 'files', 'launcher', 'desktop'} or
                data['format'] != 1 or set(data['files']) != set(FILES)):
            raise ValueError('Invalid GUI install schema')
        for label in ('launcher', 'desktop'):
            if not isinstance(data[label], str) or len(data[label]) != 64:
                raise ValueError('Invalid GUI install digest')
    except (TypeError, ValueError, UnicodeError, OSError) as error:
        return 'INCONSISTENT', [f'Invalid GUI manifest: {error}']
    for name, hashvalue in data['files'].items():
        target = appdir / name
        if not isinstance(hashvalue, str) or not _is_regular(target) or _hash(target) != hashvalue:
            errors.append(f'GUI source missing or modified: {name}')
    for name, path in (('launcher', launcher), ('desktop', desktop)):
        if not _is_regular(path) or _hash(path) != data[name]:
            errors.append(f'{name} missing or modified')
    known = set(FILES) | {MANIFEST}
    for path in appdir.rglob('*'):
        relative = path.relative_to(appdir).as_posix()
        if path.is_symlink():
            errors.append(f'Unsafe symlink in GUI bundle: {relative}')
        elif path.is_file() and relative not in known:
            errors.append(f'Unknown file in GUI bundle: {relative}')
        elif path.is_dir() and relative not in {'gui', 'experiments', 'experiments/gdm'}:
            errors.append(f'Unknown directory in GUI bundle: {relative}')
    return ('INCONSISTENT' if errors else 'INSTALLED'), errors


def _publish_bytes(path, data, mode):
    fd, staged = tempfile.mkstemp(prefix='.veilpaper-gui-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, mode)
        os.link(staged, path)  # no overwrite
    finally:
        if os.path.lexists(staged):
            os.unlink(staged)


def install(prefix):
    _verify_user()
    prefix = Path(prefix).expanduser().absolute()
    appdir, launcher, desktop = _paths(prefix)
    for directory in (
        prefix, prefix / 'lib', prefix / 'bin', prefix / 'share',
        prefix / 'share/applications',
    ):
        _check_directory(directory)
    if any(os.path.lexists(p) for p in (appdir, launcher, desktop)):
        raise GUIInstallError('Existing GUI installation, launcher, or desktop entry; no overwrite.')

    files = _expected()
    for directory in (appdir.parent, launcher.parent, desktop.parent):
        directory.mkdir(parents=True, exist_ok=True)
        _check_directory(directory)
    stage = Path(tempfile.mkdtemp(prefix='.veilpaper-gui-stage-', dir=appdir.parent))
    launcher_published = desktop_published = app_published = False
    try:
        for name, source in files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o644)
            if _hash(target) != _hash(source):
                raise GUIInstallError(f'Bundled source checksum mismatch: {name}')
        launch_data = _launcher(appdir)
        desktop_data = _desktop(launcher)
        (stage / MANIFEST).write_bytes(_manifest(files, launch_data, desktop_data))
        stage.rename(appdir)
        app_published = True
        _publish_bytes(launcher, launch_data, 0o755)
        launcher_published = True
        _publish_bytes(desktop, desktop_data, 0o644)
        desktop_published = True
    except BaseException:
        # Failure cleanup: remove only known output created by THIS call.
        if desktop_published:
            desktop.unlink()
        if launcher_published:
            launcher.unlink()
        if app_published and appdir.is_dir() and not appdir.is_symlink():
            shutil.rmtree(appdir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print('Veilpaper GUI installed in your Applications menu.')
    print(f'Launcher: {launcher}')
    print(f'Desktop entry: {desktop}')
    print('No system theme, extension, wallpaper, or existing CLI was changed.')


def uninstall(prefix):
    _verify_user()
    status, issues = check(prefix)
    if status != 'INSTALLED':
        raise GUIInstallError(f'Safe removal refused ({status}): {"; ".join(issues)}')
    appdir, launcher, desktop = _paths(prefix)
    desktop.unlink()
    launcher.unlink()
    for name in FILES:
        (appdir / name).unlink()
    (appdir / MANIFEST).unlink()
    for sub in ('experiments/gdm', 'experiments', 'gui'):
        (appdir / sub).rmdir()
    appdir.rmdir()
    print('Veilpaper GUI launcher and its bundle removed.')
    print('Existing CLI, login/lock wallpapers and GNOME extension were not removed.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'status', 'uninstall'])
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            install(args.prefix)
        elif args.action == 'uninstall':
            uninstall(args.prefix)
        else:
            status, issues = check(args.prefix)
            print('Veilpaper GUI:', status)
            for issue in issues:
                print('ISSUE:', issue)
            return 0 if status in ('NOT_INSTALLED', 'INSTALLED') else 1
    except (GUIInstallError, OSError, ValueError) as error:
        print('ERROR:', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
