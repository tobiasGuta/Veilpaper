#!/usr/bin/env bash
# First-time stock Fedora 44 GDM theme integration smoke test.
# Invoked from within an isolated Fedora 44 container; NEVER on the host.
# Installs Fedora packages INSIDE that container only.
set -euo pipefail

if [[ ! -f /.dockerenv && ! -f /run/.containerenv ]]; then
  echo "ERROR: this smoke script is container-only." >&2
  exit 1
fi
if [[ ! -f /src/veilpaper.py || ! -f /src/experiments/gdm/install_review.py ]]; then
  echo "ERROR: mount the Veilpaper repository read-only at /src." >&2
  exit 1
fi
if [[ ! -r /src/veilpaper.py || -w /src/veilpaper.py ]]; then
  echo "ERROR: repository mount must be readable and read-only." >&2
  exit 1
fi
if ! grep -qE '^Fedora release 44' /etc/fedora-release; then
  echo "ERROR: expected a Fedora 44 container." >&2
  exit 1
fi

dnf install -y --setopt=install_weak_deps=False python3 gnome-shell glib2-devel shadow-utils util-linux
target=/usr/share/gnome-shell/gnome-shell-theme.gresource
[[ -f "$target" ]] || { echo "ERROR: packaged theme missing" >&2; exit 1; }
rpm -qf "$target"
original_sha=$(sha256sum "$target" | cut -d' ' -f1)
# The container's original package file should match the RPM database.
rpm -V gnome-shell || { echo "ERROR: packaged GNOME Shell files failed verification" >&2; exit 1; }

id veiltest &>/dev/null || useradd --create-home veiltest
install -d -m 0700 -o veiltest -g veiltest /tmp/veilpaper-test

# Write a minimal, valid 1x1 PNG using only Python's standard library.
runuser -u veiltest -- python3 - <<'PY'
from pathlib import Path
import struct
import zlib
def chunk(kind, data):
    return (struct.pack('>I', len(data)) + kind + data +
            struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))
header = b'\x89PNG\r\n\x1a\n'
ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
pixel = zlib.compress(b'\x00\x00\x00\x00')
png = header + chunk(b'IHDR', ihdr) + chunk(b'IDAT', pixel) + chunk(b'IEND', b'')
Path('/tmp/veilpaper-test/login.png').write_bytes(png)
PY

echo "=== Verify stock theme preflight ==="
runuser -u veiltest -- python3 /src/veilpaper.py login preflight
echo "=== Verify stock RPM baseline (no original backup yet) ==="
runuser -u veiltest -- python3 /src/veilpaper.py login baseline

echo "=== Build portable candidate (unprivileged, output in /tmp) ==="
runuser -u veiltest -- python3 /src/veilpaper.py login portable-build \
  /tmp/veilpaper-test/login.png \
  --output /tmp/veilpaper-test/candidate.gresource

echo "=== Review pristine first-time installation candidate (read-only) ==="
runuser -u veiltest -- python3 /src/veilpaper.py login install-check \
  /tmp/veilpaper-test/candidate.gresource

echo "=== Exercise GUI build-only candidate backend against real stock RPM ==="
runuser -u veiltest -- env XDG_CACHE_HOME=/tmp/veilpaper-test/cache PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import hashlib
from pathlib import Path
import sys
sys.path.insert(0, '/src/gui')
from backend import prepare_login_candidate
source = Path('/tmp/veilpaper-test/login.png')
before = source.read_bytes()
candidate = prepare_login_candidate(source)
assert candidate.path.is_file()
assert candidate.path.stat().st_mode & 0o777 == 0o600
assert candidate.digest == hashlib.sha256(candidate.path.read_bytes()).hexdigest()
assert 'login-candidates' in candidate.path.parts
assert candidate.resource.endswith('.png')
assert source.read_bytes() == before
print('PASS: GUI prepared an independently checked, private GDM candidate; original image unchanged.')
PY

echo "=== Confirm VM-only gate refuses running in a container ==="
if python3 /src/experiments/gdm/vm_gate.py \
  --candidate /tmp/veilpaper-test/candidate.gresource \
  --confirm 'DISPOSABLE FEDORA 44 VM'; then
  echo "ERROR: VM-only gate incorrectly admitted a container." >&2
  exit 1
fi
echo "PASS: Full-VM-only admission refuses this disposable container."

echo "=== Verify journal recovery using disposable paths only ==="
runuser -u veiltest -- python3 /src/veilpaper.py login transaction-check \
  "$target" /tmp/veilpaper-test/candidate.gresource

after_sha=$(sha256sum "$target" | cut -d' ' -f1)
[[ "$original_sha" == "$after_sha" ]] || {
  echo "ERROR: packaged theme changed during smoke test" >&2; exit 1;
}
[[ ! -e /var/backups/fedora-gdm-wallpaper/manager-state.json ]] || {
  echo "ERROR: unexpected GDM manager state" >&2; exit 1;
}
echo "PASS: pristine RPM baseline, compiled candidate, install admission review,"
echo "      disposable transaction recovery, and installed GDM theme unchanged."
echo "NOTE: no real install, graphical GDM launch, or reboot was attempted."
