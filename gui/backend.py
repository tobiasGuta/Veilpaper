"""Non-GTK interface between Veilpaper's graphical app and existing CLI.

No system writes. Login operations are READ-ONLY. Lock wallpaper updates
reuse the same validated CLI functions as 'veilpaper lock set/restore'.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
import importlib.util
from io import StringIO
import os
from pathlib import Path
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
CLI = PROJECT / 'veilpaper.py'
RPM = PROJECT / 'experiments/gdm/rpm_baseline.py'
LOGIN_RESOURCE = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
LOGIN_ASSET = '/org/gnome/shell/theme/fedora-login-wallpaper.'
EXTENSION_UUID = 'lockscreen@veilpaper.tobiasguta'
MAX_LOGIN_PREVIEW = 25 * 1024 * 1024


@dataclass(frozen=True)
class ScreenState:
    lock_image: Path | None
    extension_state: str
    login_label: str
    login_detail: str


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Missing Veilpaper component: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lock_image() -> Path | None:
    directory = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'veilpaper'
    for name in ('lock-wallpaper.png', 'lock-wallpaper.jpg'):
        path = directory / name
        if path.is_file() and not path.is_symlink():
            return path
    return None


def extension_status() -> str:
    if shutil.which('gnome-extensions') is None:
        return 'Extension status unavailable'
    try:
        result = subprocess.run(
            ['gnome-extensions', 'info', EXTENSION_UUID],
            capture_output=True, text=True, check=False, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return 'Extension status unavailable'
    if result.returncode:
        return 'Extension not installed or unavailable'
    fields = {}
    for line in result.stdout.splitlines():
        if ':' in line:
            key, value = line.strip().split(':', 1)
            fields[key] = value.strip()
    if fields.get('Enabled') == 'Yes' and fields.get('State') == 'ACTIVE':
        return 'Extension active'
    if fields.get('Enabled') == 'No':
        return 'Extension disabled'
    return 'Extension: ' + fields.get('State', 'unknown')


def login_status() -> tuple[str, str]:
    try:
        inspector = _load(RPM, 'veilpaper_gui_rpm')
        result = inspector.inspect()
        if result['active_matches_rpm']:
            return 'Default login appearance', 'Active theme matches Fedora RPM metadata.'
        if result['backup_matches_rpm']:
            return 'Custom login theme detected', 'Original theme backup matches the installed RPM.'
        return 'Login status needs attention', 'No matching RPM baseline was confirmed.'
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        return 'Login status unavailable', 'Could not inspect the GDM theme safely.'


def state() -> ScreenState:
    label, detail = login_status()
    return ScreenState(
        lock_image=lock_image(),
        extension_state=extension_status(),
        login_label=label,
        login_detail=detail,
    )


def set_lock(path: Path):
    cli = _load(CLI, 'veilpaper_gui_cli_set')
    with redirect_stdout(StringIO()):
        cli.set_lock(Path(path))
    return lock_image()


def restore_lock():
    cli = _load(CLI, 'veilpaper_gui_cli_restore')
    with redirect_stdout(StringIO()):
        cli.restore_lock()


def login_preview() -> tuple[bytes, str] | None:
    """Read the known Veilpaper asset from GDM; never extract it to disk."""
    if LOGIN_RESOURCE.is_symlink() or not LOGIN_RESOURCE.is_file() or not shutil.which('gresource'):
        return None
    for ext, mime in (('png', 'png'), ('jpg', 'jpeg')):
        try:
            result = subprocess.run(
                ['gresource', 'extract', str(LOGIN_RESOURCE), LOGIN_ASSET + ext],
                capture_output=True, timeout=10, check=False)
            if result.returncode or len(result.stdout) > MAX_LOGIN_PREVIEW:
                continue
            if ext == 'png' and result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                return result.stdout, mime
            if ext == 'jpg' and result.stdout.startswith(b'\xff\xd8\xff'):
                return result.stdout, mime
        except (OSError, subprocess.TimeoutExpired):
            return None
    return None
