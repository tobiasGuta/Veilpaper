"""Non-GTK GUI adapter to Veilpaper's verified wallpaper tools.

Lock operations retain existing user-level CLI behavior. Login operations
read GDM/RPM state and may BUILD a candidate only in the user's private cache.
No privilege escalation, GDM installation or live-login changes are offered.
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
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
CLI = PROJECT / 'veilpaper.py'
RPM = PROJECT / 'experiments/gdm/rpm_baseline.py'
PORTABLE = PROJECT / 'experiments/gdm/portable_build.py'
REVIEW = PROJECT / 'experiments/gdm/install_review.py'
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


@dataclass(frozen=True)
class LoginCandidate:
    path: Path
    digest: str
    baseline_digest: str
    resource: str


def _candidate_parent() -> Path:
    """Confine unpublished candidates to a private, user-owned cache folder."""
    base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache').expanduser()
    # The immediate cache root must be an existing real directory. Never
    # interpret an arbitrary symlink as a safe place to save candidates.
    if base.is_symlink():
        raise RuntimeError('Cache root is a symlink; refusing to store a GDM candidate.')
    base.mkdir(parents=True, exist_ok=True)
    if not base.is_dir() or base.stat().st_uid != os.getuid():
        raise RuntimeError('Cache root must be a regular user-owned directory.')
    target = base / 'veilpaper' / 'login-candidates'
    for directory in (target.parent, target):
        if directory.is_symlink():
            raise RuntimeError('Veilpaper cache directory is a symlink.')
        directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.is_dir() or directory.stat().st_uid != os.getuid():
            raise RuntimeError('Veilpaper candidate directory is unsafe.')
        directory.chmod(0o700)
    return target


def prepare_login_candidate(source: Path) -> LoginCandidate:
    """Build and verify a GDM candidate, without writing to GDM or its backup.

    Importantly this DOES NOT call first-time install-check: an existing
    customized theme is expected on the development machine. Review the new
    candidate relative to the RPM-matching stock baseline instead.
    """
    if os.geteuid() == 0:
        raise RuntimeError('Never prepare Veilpaper login themes as root.')
    cli = _load(CLI, 'veilpaper_gui_cli_candidate')
    portable = _load(PORTABLE, 'veilpaper_gui_portable_builder')
    reviewer = _load(REVIEW, 'veilpaper_gui_candidate_review')
    source = Path(source).expanduser()
    kind = cli.image_type(source, allow_other=True)
    baseline, baseline_digest = portable.select_baseline()
    cache = _candidate_parent()
    job = Path(tempfile.mkdtemp(prefix='prepared-', dir=str(cache)))
    try:
        image = source
        if kind is None:
            image = job / 'normalized.png'
            cli.convert_to_png(source, image)
            if cli.image_type(image) != 'png':
                raise RuntimeError('Converted input did not pass PNG validation.')
        output = job / 'candidate.gresource'
        with redirect_stdout(StringIO()):
            portable.build(image, output)
        resource, _count = reviewer._resource_differences(baseline, output)
        # Demand a current RPM-matching baseline throughout build/inspection.
        if (portable.select_baseline() != (baseline, baseline_digest) or
                portable.gdm.sha256(baseline) != baseline_digest):
            raise RuntimeError('The verified RPM baseline changed during preparation.')
        if not resource.endswith(('.png', '.jpg')):
            raise RuntimeError('Candidate contains an unexpected wallpaper asset.')
        if image != source:
            image.unlink()
        output.chmod(0o600)
        return LoginCandidate(
            path=output,
            digest=portable.gdm.sha256(output),
            baseline_digest=baseline_digest,
            resource=resource,
        )
    except BaseException:
        shutil.rmtree(job)
        raise
