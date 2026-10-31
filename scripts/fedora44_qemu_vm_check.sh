#!/usr/bin/env bash
# Disposable Fedora 44 full-VM, READ-ONLY GDM admission on GitHub Actions.
# No live GDM installer, restore, or reboot. Never run this on user's laptop.
set -Eeuo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux ||
      -z "${GITHUB_WORKSPACE:-}" || -z "${RUNNER_TEMP:-}" ]]; then
  echo "BLOCKED: ephemeral GitHub-hosted Linux runner required" >&2; exit 1
fi
if [[ ! -c /dev/kvm || ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  echo "BLOCKED: KVM unavailable; Docker/TCG cannot replace a full VM qualification" >&2
  exit 1
fi
[[ -f "$GITHUB_WORKSPACE/experiments/gdm/vm_gate.py" ]] || exit 1

umask 077
work="$(mktemp -d -p "$RUNNER_TEMP" veilpaper-qemu-XXXXXX)"
qemu_pid=""
cleanup() {
  if [[ -n "$qemu_pid" ]] && kill -0 "$qemu_pid" 2>/dev/null; then
    kill "$qemu_pid" || true
    wait "$qemu_pid" 2>/dev/null || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT

echo "=== Setting up QEMU on ephemeral Actions runner only ==="
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  qemu-system-x86 qemu-utils cloud-image-utils openssh-client curl

image='Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2'
url="https://download.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/$image"
sha='28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f'
echo "=== Downloading official Fedora 44 cloud image (pinned SHA-256) ==="
curl -fL --retry 3 --connect-timeout 20 --max-time 600 "$url" -o "$work/$image"
printf '%s  %s\n' "$sha" "$work/$image" | sha256sum -c -
qemu-img create -f qcow2 -F qcow2 -b "$work/$image" "$work/overlay.qcow2" >/dev/null

ssh-keygen -q -t ed25519 -N '' -f "$work/guest_key"
pubkey="$(cat "$work/guest_key.pub")"
cat > "$work/user-data" <<EOF
#cloud-config
hostname: veilpaper-ephemeral-vm
ssh_pwauth: false
disable_root: true
users:
  - name: veiltest
    shell: /bin/bash
    groups: wheel
    lock_passwd: true
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - $pubkey
EOF
cat > "$work/meta-data" <<EOF
instance-id: veilpaper-fedora44-gdm-ci
local-hostname: veilpaper-ephemeral-vm
EOF
cloud-localds "$work/seed.iso" "$work/user-data" "$work/meta-data"

echo "=== Booting QEMU/KVM VM with independent qcow2 overlay ==="
qemu-system-x86_64 -machine accel=kvm -cpu host -smp 2 -m 4096 \
  -drive file="$work/overlay.qcow2",format=qcow2,if=virtio \
  -drive file="$work/seed.iso",format=raw,media=cdrom,if=virtio \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:22357-:22 \
  -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$work/serial.log" -monitor none \
  -daemonize -pidfile "$work/qemu.pid"
qemu_pid="$(cat "$work/qemu.pid")"
ssh_opts=(-p 22357 -i "$work/guest_key" -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$work/known_hosts"
  -o ConnectTimeout=4 -o ServerAliveInterval=10 -o ServerAliveCountMax=3
  -o LogLevel=ERROR)
guest='veiltest@127.0.0.1'
ready=0
for _ in $(seq 1 90); do
  if ! kill -0 "$qemu_pid" 2>/dev/null; then
    echo 'BLOCKED: QEMU terminated before guest SSH became ready' >&2
    tail -n 80 "$work/serial.log" >&2 || true; exit 1
  fi
  if ssh "${ssh_opts[@]}" "$guest" true 2>/dev/null; then ready=1; break; fi
  sleep 5
done
if [[ "$ready" != 1 ]]; then
  echo 'BLOCKED: Fedora VM failed to reach SSH' >&2
  tail -n 80 "$work/serial.log" >&2 || true; exit 1
fi

echo "=== Copying selected source files into VM home (NO writable host mount) ==="
tar -C "$GITHUB_WORKSPACE" -cf - \
  veilpaper.py \
  experiments/gdm/fedora_wallpaper_manager_v02.py \
  experiments/gdm/preflight.py \
  experiments/gdm/rpm_baseline.py \
  experiments/gdm/portable_build.py \
  experiments/gdm/install_review.py \
  experiments/gdm/fixture_transaction.py \
  experiments/gdm/vm_gate.py \
  | ssh "${ssh_opts[@]}" "$guest" \
    'mkdir -p "$HOME/veilpaper" && tar -xf - -C "$HOME/veilpaper"'

echo "=== Run read-only qualification INSIDE QEMU VM ==="
ssh "${ssh_opts[@]}" "$guest" 'bash -se' <<'GUEST'
set -Eeuo pipefail
cd "$HOME/veilpaper"
cat /etc/fedora-release
systemd-detect-virt --vm
! systemd-detect-virt --container
sudo dnf install -y --setopt=install_weak_deps=False gnome-shell gdm glib2-devel
rpm -q gnome-shell gdm
sudo rpm -V gnome-shell
theme=/usr/share/gnome-shell/gnome-shell-theme.gresource
[[ -f "$theme" && ! -L "$theme" ]]
before="$(sha256sum "$theme" | cut -d' ' -f1)"
[[ ! -e /var/backups/fedora-gdm-wallpaper/manager-state.json ]]
[[ ! -e /var/backups/fedora-gdm-wallpaper/original.gresource ]]
python3 - <<'PY'
from pathlib import Path
import struct, zlib
def chunk(name, data):
    return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
png = (b'\x89PNG\r\n\x1a\n' +
       chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) +
       chunk(b'IDAT', zlib.compress(b'\x00\x24\x40\x80')) +
       chunk(b'IEND', b''))
Path.home().joinpath('login-ci.png').write_bytes(png)
PY
python3 veilpaper.py login preflight
python3 veilpaper.py login baseline
python3 veilpaper.py login portable-build \
  "$HOME/login-ci.png" --output "$HOME/vm-candidate.gresource"
python3 veilpaper.py login install-check "$HOME/vm-candidate.gresource"

# Verify the full VM is not enough without the explicit marker.
if sudo python3 experiments/gdm/vm_gate.py \
  --candidate "$HOME/vm-candidate.gresource" \
  --confirm 'DISPOSABLE FEDORA 44 VM'; then
  echo "FAIL: VM gate admitted guest without marker!" >&2; exit 1
fi
echo "PASS: markerless guest correctly refused"

printf 'VEILPAPER-DISPOSABLE-FEDORA44-VM-ONLY\n' | \
  sudo tee /etc/veilpaper-disposable-vm-qualification >/dev/null
sudo chown root:root /etc/veilpaper-disposable-vm-qualification
sudo chmod 0600 /etc/veilpaper-disposable-vm-qualification
sudo python3 experiments/gdm/vm_gate.py \
  --candidate "$HOME/vm-candidate.gresource" \
  --confirm 'DISPOSABLE FEDORA 44 VM'
after="$(sha256sum "$theme" | cut -d' ' -f1)"
[[ "$before" == "$after" ]]
[[ ! -e /var/backups/fedora-gdm-wallpaper/original.gresource ]]
[[ ! -e /var/backups/fedora-gdm-wallpaper/manager-state.json ]]
sudo rpm -V gnome-shell
echo "PASS: real Fedora 44 full-VM read-only admission and five fixture recovery scenarios"
echo "PASS: no live GDM theme, backup, or state modification"
GUEST
echo "PASS: ephemeral full VM qualification completed; VM overlay and SSH key discarded"
