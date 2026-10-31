#!/usr/bin/env python3
"""Fedora GNOME 50 GDM wallpaper manager (experimental, local and reversible).

Build a custom GDM theme from a verified original resource. Building never touches
/usr/share. Applying/restoring require root and an unmodified expected base.
No network requests, external wallpaper managers, or automatic GDM restarts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP_DIR = Path('/var/backups/fedora-gdm-wallpaper')
ORIGINAL = BACKUP_DIR / 'original.gresource'
STATE = BACKUP_DIR / 'manager-state.json'
# From the user's verified Fedora 44 / GNOME Shell 50.6 backup.
ORIGINAL_SHA256 = '28170a6cd8be11441339bd00384877f0ad56b88c9c32b5ce2458ba286760fb79'
PREFIX = '/org/gnome/shell/theme/'
CSS_NAMES = ('gnome-shell-dark.css', 'gnome-shell-light.css')
ASSET_BASENAME = 'fedora-login-wallpaper'
MAX_IMAGE_BYTES = 25 * 1024 * 1024
CSS_BLOCK = re.compile(r'#lockDialogGroup\s*\{[^{}]*\}', re.DOTALL)


def fail(message: str):
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(*args: str, binary=False, cwd=None):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=True, timeout=35, cwd=cwd)
    except FileNotFoundError:
        fail(f'Required Fedora utility not found: {args[0]}')
    except subprocess.CalledProcessError as e:
        fail(f'Command failed: {" ".join(args)}\n{e.stderr.decode(errors="replace")}')
    return p.stdout if binary else p.stdout.decode('utf-8').strip()


def verified_original() -> Path:
    if not ORIGINAL.is_file():
        fail(f'Original backup not found: {ORIGINAL}')
    if sha256(ORIGINAL) != ORIGINAL_SHA256:
        fail('Original backup checksum changed; refusing to proceed.')
    return ORIGINAL


def image_type(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        fail(f'Choose a regular PNG/JPEG file: {path}')
    size = path.stat().st_size
    if not 10 <= size <= MAX_IMAGE_BYTES:
        fail('Wallpaper must be between 10 bytes and 25 MiB.')
    with path.open('rb') as f:
        magic = f.read(12)
    if magic.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if magic.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    fail('Only PNG and JPEG images are supported.')


def resources(path: Path) -> list[str]:
    entries = [s for s in run('gresource', 'list', str(path)).splitlines() if s]
    if not entries or len(entries) != len(set(entries)):
        fail('Resource archive is empty or has duplicate names.')
    for name in entries:
        if not name.startswith(PREFIX):
            fail(f'Unexpected path in theme, no patch applied: {name}')
        relative = name.lstrip('/')
        if any(x in ('.', '..') for x in Path(relative).parts):
            fail(f'Unsafe resource path: {name}')
    return sorted(entries)


def extract(path: Path, name: str) -> bytes:
    return run('gresource', 'extract', str(path), name, binary=True)


def patch_css(text: str, resource_image_path: str) -> str:
    if len(CSS_BLOCK.findall(text)) != 1:
        fail('Expected exactly one #lockDialogGroup block; refusing to patch.')
    new_block = (
        '#lockDialogGroup {\n'
        '  background-color: #222226;\n'
        f'  background-image: url("resource://{resource_image_path}");\n'
        '  background-size: cover;\n'
        '  background-repeat: no-repeat;\n'
        '  background-position: center;\n'
        '}')
    return CSS_BLOCK.sub(lambda _: new_block, text, count=1)


def build(image_path: Path, output: Path):
    original = verified_original()
    suffix = image_type(image_path)
    asset = f'{ASSET_BASENAME}.{suffix}'
    resource_image = PREFIX + asset
    source_names = resources(original)
    if resource_image in source_names:
        fail('Unexpected existing custom asset inside original resource.')
    if output.resolve() in (THEME.resolve(), ORIGINAL.resolve()):
        fail('Build output may not overwrite the original or active theme.')
    if output.exists():
        fail(f'Output already exists. Choose a new --output path: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gdm-theme-build-') as tmpname:
        tmp = Path(tmpname)
        for name in source_names:
            target = tmp / name.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            data = extract(original, name)
            if name in {PREFIX + n for n in CSS_NAMES}:
                data = patch_css(data.decode('utf-8'), resource_image).encode('utf-8')
            target.write_bytes(data)
        image_target = tmp / resource_image.lstrip('/')
        image_target.write_bytes(image_path.read_bytes())
        image_target.chmod(0o644)
        all_names = source_names + [resource_image]
        xml_root = ET.Element('gresources')
        group = ET.SubElement(xml_root, 'gresource', {'prefix': '/'})
        for name in all_names:
            ET.SubElement(group, 'file').text = name.lstrip('/')
        xmlfile = tmp / 'theme.xml'
        ET.ElementTree(xml_root).write(xmlfile, encoding='utf-8', xml_declaration=True)
        generated = tmp / 'custom-theme.gresource'
        run('glib-compile-resources', str(xmlfile), '--sourcedir', str(tmp),
            '--target', str(generated))
        if set(resources(generated)) != set(all_names):
            fail('Compiled theme lost or renamed resources.')
        if extract(generated, resource_image) != image_path.read_bytes():
            fail('Compiled wallpaper bytes do not match input image.')
        for name in source_names:
            data = extract(generated, name)
            if name in {PREFIX + n for n in CSS_NAMES}:
                if f'resource://{resource_image}' not in data.decode('utf-8'):
                    fail(f'Missing wallpaper CSS in compiled {name}')
            elif data != extract(original, name):
                fail(f'Original resource changed unexpectedly: {name}')
        shutil.copyfile(generated, output)
        output.chmod(0o644)
    print(f'Built and verified: {output}')
    print(f'Original entries preserved: {len(source_names)}; wallpaper added: {asset}')
    print(f'Compiled SHA-256: {sha256(output)}')
    print('System resource unchanged. Use apply only after review and recovery preparation.')


def require_root():
    if os.geteuid() != 0:
        fail('This operation requires sudo/root. Build and status do not.')


def atomic_replace(source: Path, destination: Path):
    # Temp file on same filesystem, owner root, preserve standard world-readable mode.
    fd, tmpname = tempfile.mkstemp(prefix='.fedora-gdm-', dir=str(destination.parent))
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmpname, 0o644)
        os.chown(tmpname, 0, 0)
        os.replace(tmpname, destination)
        if shutil.which('restorecon'):
            run('restorecon', str(destination))
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


def record_state(data: dict):
    fd, tmpname = tempfile.mkstemp(prefix='.gdm-state-', dir=str(BACKUP_DIR))
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmpname, 0o600)
        os.replace(tmpname, STATE)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


def state() -> dict | None:
    if not STATE.is_file():
        return None
    try:
        return json.loads(STATE.read_text())
    except PermissionError:
        fail(f'Manager state is restricted to root: {STATE}. Run status with sudo.')
    except (OSError, ValueError) as e:
        fail(f'Unable to read or parse manager state: {STATE} ({e})')


def apply(candidate: Path):
    require_root()
    verified_original()
    if STATE.exists():
        fail('Existing manager state. Restore first; never apply over another patch.')
    if not THEME.is_file() or sha256(THEME) != ORIGINAL_SHA256:
        fail('Active theme is not the verified original (possibly updated). Refusing overwrite.')
    if not candidate.is_file() or candidate.is_symlink():
        fail('Candidate resource not found or is a symbolic link.')
    current_names = set(resources(ORIGINAL))
    candidate_names = set(resources(candidate))
    extras = candidate_names - current_names
    if len(extras) != 1 or not next(iter(extras)).startswith(PREFIX + ASSET_BASENAME + '.'):
        fail('Candidate does not match the expected one-asset theme layout.')
    new_asset = next(iter(extras))
    if candidate_names != current_names | {new_asset}:
        fail('Candidate is missing original theme resources.')
    for name in current_names:
        before = extract(ORIGINAL, name)
        after = extract(candidate, name)
        if name in {PREFIX + n for n in CSS_NAMES}:
            expected = patch_css(before.decode('utf-8'), new_asset).encode('utf-8')
            if after != expected:
                fail(f'Unexpected CSS difference: {name}')
        elif after != before:
            fail(f'Unexpected difference in original resource: {name}')
    desired_hash = sha256(candidate)
    # Record intention before swapping; a subsequent restore can recover even
    # if the process is interrupted after the atomic replacement.
    record_state({'base': ORIGINAL_SHA256, 'installed': desired_hash})
    try:
        atomic_replace(candidate, THEME)
    except Exception:
        # Leave state in place for a safe, explicit restore.
        raise
    if sha256(THEME) != desired_hash:
        fail('Installed theme hash mismatch. Restore the verified original from TTY.')
    print('Theme installed. GDM has NOT been restarted or logged you out.')
    print('Save all work and reboot when ready to test the login screen.')
    print('Recovery: sudo python3 fedora_wallpaper_manager.py restore')


def restore():
    require_root()
    verified_original()
    if not THEME.is_file():
        fail('Active GNOME theme missing; inspect manually before recovery.')
    current_hash = sha256(THEME)
    if current_hash == ORIGINAL_SHA256:
        if STATE.exists():
            STATE.unlink()
        print('Already running the verified original theme.')
        return
    meta = state()
    if not meta or current_hash != meta.get('installed') or meta.get('base') != ORIGINAL_SHA256:
        fail('Active theme is not our known patch (it may have been updated). Refusing to downgrade it.')
    atomic_replace(ORIGINAL, THEME)
    if sha256(THEME) != ORIGINAL_SHA256:
        fail('Restore verification failed; use recovery TTY and inspect backup.')
    STATE.unlink(missing_ok=True)
    print('Original verified theme restored. Reboot later to refresh GDM.')


def status():
    for label, path in [('Active theme', THEME), ('Original backup', ORIGINAL)]:
        print(f'{label}: {path}')
        print(f'  SHA-256: {sha256(path) if path.is_file() else "MISSING"}')
    good = ORIGINAL.is_file() and sha256(ORIGINAL) == ORIGINAL_SHA256
    print(f'Backup matches previously verified checksum: {good}')
    if STATE.is_file() and not os.access(STATE, os.R_OK):
        print('Manager state: root-only (run status with sudo to inspect)')
    else:
        print(f'Manager state: {state() or "none"}')
    if THEME.is_file():
        print(f'Active theme equals original backup: {sha256(THEME) == ORIGINAL_SHA256}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    build_cmd = sub.add_parser('build', help='Build and validate a new GDM theme without modifying the OS')
    build_cmd.add_argument('image', type=Path, help='A PNG/JPEG wallpaper')
    build_cmd.add_argument('--output', type=Path,
                           default=Path.home() / 'Downloads' / 'gnome-shell-theme-custom.gresource')
    apply_cmd = sub.add_parser('apply', help='Install verified candidate. Requires root.')
    apply_cmd.add_argument('candidate', type=Path)
    sub.add_parser('restore', help='Restore original resource if our patch is installed. Requires root.')
    sub.add_parser('status', help='Read-only status of original, active resource, and manager state')
    args = p.parse_args()
    try:
        if args.command == 'build':
            build(args.image.expanduser(), args.output.expanduser())
        elif args.command == 'apply':
            apply(args.candidate.expanduser())
        elif args.command == 'restore':
            restore()
        else:
            status()
    except (RuntimeError, OSError, UnicodeError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())