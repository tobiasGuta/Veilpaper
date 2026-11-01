"""Veilpaper GUI bridge to a pre-installed, root-owned *disposable-VM-only* helper.

NEVER run a Python script from the user's GUI bundle with pkexec. The helper
must already be installed at a fixed privileged path, including all its
imported dependencies, and the dedicated policy must match that path.
The ROOT helper independently gates full Fedora 44 VM + both VM-only markers,
and rechecks exact expected SHA-256 under the transaction lock.

No production host GDM installer or authorization is provided here.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import subprocess
import xml.etree.ElementTree as ET

HELPER = Path('/usr/libexec/veilpaper-guest/scripts/gdm_guest_installer.py')
POLICY = Path('/usr/share/polkit-1/actions/me.tobiasguta.Veilpaper.Guest.policy')
PKEXEC = Path('/usr/bin/pkexec')
RELEASE = Path('/etc/fedora-release')
VIRTUALIZER = Path('/usr/bin/systemd-detect-virt')
MARKERS = (
    Path('/etc/veilpaper-disposable-vm-qualification'),
    Path('/etc/veilpaper-disposable-vm-GDM-write-test'),
)
COMPONENTS = (
    HELPER,
    HELPER.parents[1] / 'experiments/gdm/vm_real_transaction.py',
    HELPER.parents[1] / 'experiments/gdm/vm_gate.py',
    HELPER.parents[1] / 'experiments/gdm/install_review.py',
    HELPER.parents[1] / 'experiments/gdm/fedora_wallpaper_manager_v02.py',
    HELPER.parents[1] / 'experiments/gdm/rpm_baseline.py',
)
CONFIRM = 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
_ACTION_ID = 'me.tobiasguta.Veilpaper.Guest'
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class VMInstallUnavailable(RuntimeError):
    pass


def _root_owned_file(path, *, executable=False, private=False):
    try:
        info = path.lstat()
    except OSError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != 0 or (info.st_mode & 0o022)):
        return False
    if private and stat.S_IMODE(info.st_mode) != 0o600:
        return False
    if executable and not (info.st_mode & stat.S_IXUSR):
        return False
    return True


def _root_owned_directory(path):
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not (info.st_mode & 0o022)


def _policy_matches():
    if not _root_owned_file(POLICY):
        return False
    try:
        root = ET.parse(POLICY).getroot()
    except (ET.ParseError, OSError):
        return False
    for action in root.findall('action'):
        if action.attrib.get('id') != _ACTION_ID:
            continue
        annotations = {
            item.attrib.get('key'): (item.text or '').strip()
            for item in action.findall('annotate')
        }
        defaults = action.find('defaults')
        if (annotations.get('org.freedesktop.policykit.exec.path') == str(HELPER)
                and defaults is not None and
                (defaults.findtext('allow_active') or '').strip() == 'auth_admin'):
            return True
    return False


def guest_install_availability():
    """Advisory UI gating only; the privileged helper must independently gate.

    Unprivileged users cannot read 0600 marker contents. The root transaction
    always revalidates their exact contents; metadata alone is not admission.
    """
    if os.geteuid() == 0:
        return False, 'Do not launch the Veilpaper GUI as root.'
    try:
        if 'Fedora release 44' not in RELEASE.read_text():
            return False, 'Guest installer requires Fedora 44.'
        commands = ((str(VIRTUALIZER), '--vm', '--quiet'),
                    (str(VIRTUALIZER), '--container', '--quiet'))
        codes = [
            subprocess.run(cmd, check=False, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            for cmd in commands
        ]
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return False, 'Cannot independently identify a full Fedora virtual machine.'
    if codes != [0, 1]:
        # systemd-detect-virt --container returns nonzero for a normal VM;
        # a return code other than 0 is acceptable there.
        if not (codes[0] == 0 and codes[1] != 0):
            return False, 'Only a full, non-container Fedora virtual machine is admitted.'
    if not all(_root_owned_file(path, private=True) for path in MARKERS):
        return False, 'Both independent root-owned VM-only markers are required.'
    if not all(_root_owned_directory(path) for path in (
            Path('/usr'), Path('/usr/libexec'), HELPER.parents[1],
            HELPER.parent, HELPER.parents[1] / 'experiments',
            HELPER.parents[1] / 'experiments/gdm')):
        return False, 'Privileged helper directory ownership is untrusted.'
    if not all(_root_owned_file(path, executable=(path == HELPER)) for path in COMPONENTS):
        return False, 'A complete root-owned guest helper bundle is not installed.'
    if not (_root_owned_file(PKEXEC, executable=True) and _policy_matches()):
        return False, 'Dedicated root-owned Polkit policy and pkexec are required.'
    return True, 'Marked disposable VM helper is installed (not a host installation grant).'


def install_candidate_in_guest(candidate, *, runner=subprocess.run):
    """One explicit GUI-confirmed install inside the VM; never auto-restart GDM."""
    path = Path(candidate.path)
    digest = candidate.digest
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise VMInstallUnavailable('Candidate SHA-256 is invalid.')
    if path.name != 'candidate.gresource' or not path.is_absolute():
        raise VMInstallUnavailable('Expected an absolute prepared candidate path.')
    admitted, reason = guest_install_availability()
    if not admitted:
        raise VMInstallUnavailable(reason)
    args = [
        str(PKEXEC), str(HELPER), 'install', '--candidate', str(path),
        '--sha256', digest, '--confirm', CONFIRM,
    ]
    try:
        finished = runner(args, check=False, capture_output=True,
                          text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VMInstallUnavailable(
            'Guest installer did not finish. Inspect the VM transaction journal '
            'before taking any other action.') from exc
    if finished.returncode or 'VM_REAL_GDM_INSTALLED' not in finished.stdout.splitlines():
        raise VMInstallUnavailable(
            'Guest installation did not report a verified success. '
            'Inspect the VM transaction and console before retrying.')
    return 'Installed inside disposable Fedora VM. GDM display must still be checked.'
