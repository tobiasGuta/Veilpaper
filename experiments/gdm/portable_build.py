#!/usr/bin/env python3
"""Portable, build-only GDM theme candidate for Fedora GNOME 50.

No GDM/theme/backup/state writes. This module is not an installer.
An active theme or independent backup must match the installed RPM database.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
THEME = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
BACKUP = Path('/var/backups/fedora-gdm-wallpaper/original.gresource')


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Missing GDM helper: {filename}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gdm = _load('veilpaper_original_builder_helpers', 'fedora_wallpaper_manager_v02.py')
rpm = _load('veilpaper_rpm_baseline_helpers', 'rpm_baseline.py')


def _matches(path, record):
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return path.stat().st_size == record['size'] and gdm.sha256(path) == record['digest']
    except OSError:
        return False


def select_baseline(theme=THEME, backup=BACKUP):
    """Return baseline, RPM digest. Never adopt unverified active themes/backups."""
    if theme.is_symlink() or not theme.is_file():
        raise RuntimeError('Active GDM theme is missing or symlinked; refusing build.')
    record, error = rpm.package_record(theme)
    if error:
        raise RuntimeError(f'Cannot verify GDM RPM metadata: {error}')
    if backup.is_symlink():
        raise RuntimeError('Backup is a symlink; refusing build.')
    # Prefer an independent stock backup on already customized machines.
    if _matches(backup, record):
        return backup, record['digest']
    if _matches(theme, record):
        return theme, record['digest']
    raise RuntimeError('Neither active theme nor backup matches installed RPM SHA-256 and size.')


def build(image, output, *, theme=THEME, backup=BACKUP):
    """Compile a candidate without overwriting an existing output or modifying GDM."""
    image = Path(image).expanduser()
    output = Path(output).expanduser()
    baseline, baseline_hash = select_baseline(theme, backup)
    # The original builder performs size, magic, archive path, and CSS checks.
    extension = gdm.image_type(image)
    image_data = image.read_bytes()
    if len(image_data) > gdm.MAX_IMAGE_BYTES:
        raise RuntimeError('Wallpaper changed during validation.')
    if output.resolve() in {theme.resolve(), backup.resolve()}:
        raise RuntimeError('Cannot use active theme or backup as build output.')
    if os.path.lexists(output):
        raise RuntimeError(f'Output already exists: {output}')
    if output.parent.is_symlink():
        raise RuntimeError('Output directory must not be a symlink.')
    if not output.parent.is_dir():
        raise RuntimeError('Output directory does not exist.')

    original_names = gdm.resources(baseline)
    asset = gdm.PREFIX + f'{gdm.ASSET_BASENAME}.{extension}'
    if asset in original_names:
        raise RuntimeError('Baseline unexpectedly contains Veilpaper wallpaper resource.')
    all_names = original_names + [asset]
    css_names = {gdm.PREFIX + name for name in gdm.CSS_NAMES}
    original_bytes = {name: gdm.extract(baseline, name) for name in original_names}
    changed = dict(original_bytes)
    for name in css_names:
        if name not in changed:
            raise RuntimeError(f'Missing expected CSS resource: {name}')
        changed[name] = gdm.patch_css(changed[name].decode('utf-8'), asset).encode('utf-8')
    changed[asset] = image_data

    # Build in a temporary directory; never write to system theme paths.
    with tempfile.TemporaryDirectory(prefix='veilpaper-portable-build-') as dirname:
        root = Path(dirname)
        for name, data in changed.items():
            dest = root / name.lstrip('/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        document = ET.Element('gresources')
        group = ET.SubElement(document, 'gresource', {'prefix': '/'})
        for name in all_names:
            ET.SubElement(group, 'file').text = name.lstrip('/')
        manifest = root / 'theme.xml'
        ET.ElementTree(document).write(manifest, encoding='utf-8', xml_declaration=True)
        compiled = root / 'candidate.gresource'
        gdm.run('glib-compile-resources', str(manifest), '--sourcedir', str(root),
                '--target', str(compiled))
        if set(gdm.resources(compiled)) != set(all_names):
            raise RuntimeError('Compiled candidate resource set differs from expected.')
        for name, expected in changed.items():
            if gdm.extract(compiled, name) != expected:
                raise RuntimeError(f'Compiled candidate differs from expected resource: {name}')
        if gdm.sha256(baseline) != baseline_hash:
            raise RuntimeError('Stock baseline changed during build.')
        if select_baseline(theme, backup) != (baseline, baseline_hash):
            raise RuntimeError('Installed RPM baseline changed during build.')
        # Stage on OUTPUT's own filesystem, then publish with a no-clobber
        # hardlink. A direct hardlink from /tmp can fail across filesystems.
        fd, stage = tempfile.mkstemp(prefix='.veilpaper-stage-', dir=str(output.parent))
        try:
            with os.fdopen(fd, 'wb') as target, compiled.open('rb') as source:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(stage, 0o644)
            os.link(stage, output)
        finally:
            if os.path.lexists(stage):
                os.unlink(stage)
    print(f'Portable candidate built: {output}')
    print(f'RPM-matching baseline: {baseline}')
    print(f'Baseline SHA-256: {baseline_hash}')
    print(f'Candidate SHA-256: {gdm.sha256(output)}')
    print('BUILD ONLY. GDM and its backups/state are unchanged; portable apply is not available.')


if __name__ == '__main__':
    raise SystemExit('Use: python3 veilpaper.py login portable-build IMAGE --output FILE')
