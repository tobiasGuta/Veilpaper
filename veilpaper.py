#!/usr/bin/env python3
"""Veilpaper unified development CLI for GNOME 50 (NOT yet a stable release)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
GDM_BACKEND = ROOT / 'experiments/gdm/fedora_wallpaper_manager_v02.py'
GDM_PREFLIGHT = ROOT / 'experiments/gdm/preflight.py'
EXTENSION_SOURCE = ROOT / 'experiments/lockscreen/lockscreen'
UUID = 'lockscreen@veilpaper.tobiasguta'
MAX_IMAGE_BYTES = 25 * 1024 * 1024


def fail(message):
    raise RuntimeError(message)


def require_user():
    if os.geteuid() == 0:
        fail('Run lock-screen operations as your regular GNOME user, not with sudo.')


def data_dir():
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'veilpaper'


def extension_dir():
    return Path.home() / '.local/share/gnome-shell/extensions' / UUID


def image_type(image, *, allow_other=False):
    if image.is_symlink() or not image.is_file():
        fail(f'Expected a regular image file: {image}')
    if not 10 <= image.stat().st_size <= MAX_IMAGE_BYTES:
        fail('Wallpaper must be between 10 bytes and 25 MiB.')
    with image.open('rb') as f:
        header = f.read(16)
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if allow_other:
        return None
    fail('Image data is not PNG or JPEG.')


def convert_to_png(source, destination):
    """Decode a non-PNG/JPEG GNOME-readable image and save real PNG bytes.

    This uses the host's GNOME GdkPixbuf decoder instead of trusting extensions.
    Conversion is deliberately capped to avoid huge image allocations.
    """
    try:
        import gi
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import GdkPixbuf
    except (ImportError, ValueError) as error:
        fail('This image is not PNG/JPEG. GNOME image conversion needs '
             'python3-gobject (PyGObject), or export the image as PNG first: '
             f'{error}')
    try:
        info, width, height = GdkPixbuf.Pixbuf.get_file_info(str(source))
        if info is None:
            fail('GNOME could not identify the input image format. '
                 'Try exporting it as a genuine PNG.')
        if width < 1 or height < 1 or width * height > 32_000_000:
            fail(f'Input dimensions {width}x{height} exceed the 32-megapixel limit.')
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(source))
        if pixbuf is None or not pixbuf.savev(str(destination), 'png', [], []):
            fail('GNOME could not convert this image into PNG.')
    except RuntimeError:
        raise
    except Exception as error:
        fail(f'GNOME could not decode or convert this image: {error}')


def set_lock(image):
    require_user()
    original_kind = image_type(image, allow_other=True)
    kind = original_kind or 'png'
    dest = data_dir()
    if dest.is_symlink():
        fail('Wallpaper data directory is a symlink.')
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = dest / f'lock-wallpaper.{kind}'
    other = dest / ('lock-wallpaper.jpg' if kind == 'png' else 'lock-wallpaper.png')
    if other.is_dir() and not other.is_symlink():
        fail(f'Unexpected directory where wallpaper should be: {other}')
    fd, temp = tempfile.mkstemp(dir=str(dest), prefix='.veilpaper-')
    os.close(fd)
    try:
        if original_kind:
            with open(temp, 'wb') as target, image.open('rb') as source:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        else:
            convert_to_png(image, Path(temp))
        os.chmod(temp, 0o600)
        if image_type(Path(temp)) != kind:
            fail('Output image did not pass format verification.')
        os.replace(temp, name)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    if os.path.lexists(other):
        other.unlink()
    if original_kind is None:
        print('Converted GNOME-readable source image to PNG.')
    print(f'Lock wallpaper selected: {name}')
    print('Next lock (Super+L) should show this image; login/desktop are untouched.')


def restore_lock():
    require_user()
    for name in ('lock-wallpaper.png', 'lock-wallpaper.jpg'):
        path = data_dir() / name
        if path.is_dir() and not path.is_symlink():
            fail(f'Unexpected directory at {path}')
        if os.path.lexists(path):
            path.unlink()
    print('Custom lock wallpaper removed. GNOME default will appear on next lock.')


def install_lock():
    require_user()
    files = [EXTENSION_SOURCE / n for n in ('extension.js', 'metadata.json')]
    if any(f.is_symlink() or not f.is_file() for f in files):
        fail(f'GNOME extension source missing: {EXTENSION_SOURCE}')
    meta = json.loads(files[1].read_text())
    if (meta.get('uuid') != UUID or '50' not in meta.get('shell-version', [])
            or 'unlock-dialog' not in meta.get('session-modes', [])):
        fail('Extension metadata is incompatible with expected GNOME 50 setup.')
    dest = extension_dir()
    if dest.is_symlink():
        fail('Refusing symlink extension directory.')
    if dest.exists():
        if dest.is_dir() and all((dest / f.name).is_file()
                and (dest / f.name).read_bytes() == f.read_bytes() for f in files):
            print('Extension already installed and matches project source.')
            return
        fail('An extension already exists with different contents; refusing to overwrite.')
    dest.mkdir(parents=True, mode=0o755)
    try:
        for f in files:
            shutil.copyfile(f, dest / f.name)
    except Exception:
        shutil.rmtree(dest)
        raise
    print(f'Extension installed at {dest}. Log out/in if not detected yet.')
    print(f'Enable: gnome-extensions enable {UUID}')


def show_lock_status():
    folder = data_dir()
    paths = [folder / n for n in ('lock-wallpaper.png', 'lock-wallpaper.jpg')]
    matches = [str(p) for p in paths if p.is_file()]
    print('Lock image:', ', '.join(matches) if matches else '(default)')
    print('Lock extension installed:', (extension_dir() / 'extension.js').is_file())
    if os.geteuid() != 0 and shutil.which('gnome-extensions'):
        result = subprocess.run(['gnome-extensions', 'info', UUID],
            capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.strip().startswith(('Enabled:', 'State:')):
                    print(line.strip())


def gdm():
    # Reference implementation from the one host where GDM customization passed.
    # It refuses other original theme checksums, rather than modifying unknown GDM.
    spec = importlib.util.spec_from_file_location('veilpaper_gdm_backend', GDM_BACKEND)
    if spec is None or spec.loader is None:
        fail(f'GDM backend missing: {GDM_BACKEND}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight_login():
    """Inspect installed GDM theme read-only; never treat this as pristine proof."""
    spec = importlib.util.spec_from_file_location('veilpaper_gdm_preflight', GDM_PREFLIGHT)
    if spec is None or spec.loader is None:
        fail(f'GDM preflight module missing: {GDM_PREFLIGHT}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.show(module.inspect())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('status', help='Read-only status of both wallpaper systems')
    lock = subs.add_parser('lock', help='Manage lock-screen wallpaper (never sudo)')
    lock_sub = lock.add_subparsers(dest='action', required=True)
    lock_set = lock_sub.add_parser('set', help='Select PNG/JPEG for next lock')
    lock_set.add_argument('image', type=Path)
    lock_sub.add_parser('restore', help='Remove custom lock wallpaper')
    lock_sub.add_parser('install', help='Install packaged GNOME extension')
    lock_sub.add_parser('status', help='Report lock extension and image')
    login = subs.add_parser('login', help='GDM system-theme operations (only verified original host)')
    login_sub = login.add_subparsers(dest='action', required=True)
    login_build = login_sub.add_parser('build', help='Build candidate without changing GNOME')
    login_build.add_argument('image', type=Path)
    login_build.add_argument('--output', type=Path,
        default=Path.home() / 'Downloads' / 'gnome-shell-theme-custom.gresource')
    login_apply = login_sub.add_parser('apply', help='Install inspected candidate with sudo')
    login_apply.add_argument('candidate', type=Path)
    login_sub.add_parser('restore', help='Restore original GDM resource with sudo')
    login_sub.add_parser('status', help='Inspect GDM theme and recovery state')
    login_sub.add_parser('preflight', help='Inspect GDM theme portability without changes')
    args = parser.parse_args(argv)
    try:
        if args.command == 'lock':
            if args.action == 'set':
                set_lock(args.image.expanduser())
            elif args.action == 'restore':
                restore_lock()
            elif args.action == 'install':
                install_lock()
            else:
                show_lock_status()
        elif args.command == 'login':
            if args.action == 'preflight':
                return preflight_login()
            backend = gdm()
            if args.action == 'build':
                backend.build(args.image.expanduser(), args.output.expanduser())
            elif args.action == 'apply':
                backend.apply(args.candidate.expanduser())
            elif args.action == 'restore':
                backend.restore()
            else:
                backend.status()
        else:
            gdm().status()
            print('--- Lock screen ---')
            show_lock_status()
    except (RuntimeError, OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
