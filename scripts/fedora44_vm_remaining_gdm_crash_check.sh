#!/usr/bin/env bash
# Disposable Fedora 44 real-GDM post-swap SIGKILL and reboot recovery.
# CI ephemeral QEMU full guest ONLY; SIGKILL after actual resource swap.
# Never run this on a developer laptop.
set -Eeuo pipefail
case "${CRASH_CHECKPOINT:-}" in
  install-intent|restore-intent|restore-swap) ;;
  *) echo 'BLOCKED: select an authorized VM crash checkpoint' >&2; exit 1 ;;
esac
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_OS:-}" != Linux ||
      -z "${GITHUB_WORKSPACE:-}" || -z "${RUNNER_TEMP:-}" ]]; then
  echo "BLOCKED: ephemeral GitHub-hosted Linux runner required" >&2; exit 1
fi
# Both KVM and software TCG boot a real full-machine QEMU guest. The
# latter is slower but is NOT a container. Never downgrade to Docker.
accel=kvm
cpu=host
if [[ ! -c /dev/kvm || ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  accel=tcg
  cpu=max
  echo "INFO: KVM unavailable; using software-emulated QEMU full VM (TCG)."
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
qemu-system-x86_64 -machine "accel=$accel" -cpu "$cpu" -smp 2 -m 4096 \
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
  experiments/gdm/process_crash_probe.py \
  experiments/gdm/vm_gate.py \
  experiments/gdm/vm_real_transaction.py \
  experiments/gdm/vm_real_crash_injector.py \
  | ssh "${ssh_opts[@]}" "$guest" \
    'mkdir -p "$HOME/veilpaper" && tar -xf - -C "$HOME/veilpaper"'

echo "=== Run read-only qualification INSIDE QEMU VM ==="
ssh "${ssh_opts[@]}" "$guest" "bash -se -- '$CRASH_CHECKPOINT'" <<'GUEST'
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
echo "=== SIGKILL child during real fixture journal/swap, recover in fresh process ==="
python3 experiments/gdm/process_crash_probe.py   "$theme" "$HOME/vm-candidate.gresource"
after="$(sha256sum "$theme" | cut -d' ' -f1)"
[[ "$before" == "$after" ]]
[[ ! -e /var/backups/fedora-gdm-wallpaper/original.gresource ]]
[[ ! -e /var/backups/fedora-gdm-wallpaper/manager-state.json ]]
sudo rpm -V gnome-shell
echo "PASS: real Fedora 44 VM admission and independent fixture crash recoveries"
echo "=== Creating second root-only marker for real GDM replacement in guest ==="
printf 'VEILPAPER-REAL-GDM-WRITES-IN-DISPOSABLE-VM-ONLY\n' | \
  sudo tee /etc/veilpaper-disposable-vm-GDM-write-test >/dev/null
sudo chown root:root /etc/veilpaper-disposable-vm-GDM-write-test
sudo chmod 0600 /etc/veilpaper-disposable-vm-GDM-write-test

sha256sum "$theme" | cut -d' ' -f1 > "$HOME/stock-before.sha"
stat -c '%u:%g:%a:%C:%y' "$theme" > "$HOME/stock-before.meta"
sha256sum "$HOME/vm-candidate.gresource" | cut -d' ' -f1 > "$HOME/candidate.sha"
cat /proc/sys/kernel/random/boot_id > "$HOME/boot-before.id"
checkpoint="$1"
case "$checkpoint" in
  install-intent)
    injector_args=(--candidate "$HOME/vm-candidate.gresource")
    expected_phase=install-prepared
    expected_active=original
    expected_sha="$(cat "$HOME/stock-before.sha")"
    ;;
  restore-intent|restore-swap)
    sudo python3 experiments/gdm/vm_real_transaction.py install \
      --candidate "$HOME/vm-candidate.gresource" \
      --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
    injector_args=()
    expected_phase=restore-prepared
    if [[ "$checkpoint" == restore-intent ]]; then
      expected_active=candidate
      expected_sha="$(cat "$HOME/candidate.sha")"
    else
      expected_active=original
      expected_sha="$(cat "$HOME/stock-before.sha")"
    fi
    ;;
  *) exit 1 ;;
esac
echo "=== SIGKILL real GDM at checkpoint $checkpoint ==="
ulimit -c 0
set +e
sudo python3 experiments/gdm/vm_real_crash_injector.py "$checkpoint" \
  "${injector_args[@]}" \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
crash_exit=$?
set -e
if [[ "$crash_exit" -ne 137 ]]; then
  echo "FAIL: expected real SIGKILL exit 137, got $crash_exit" >&2
  exit 1
fi
echo "PASS: real privileged operation killed at $checkpoint"
sudo python3 experiments/gdm/vm_real_transaction.py status \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY' \
  | grep -Fx "$expected_phase: active=$expected_active"
sudo python3 - "$expected_phase" <<'PY'
import json, sys
from pathlib import Path
root = Path('/var/lib/veilpaper-disposable-gdm-transaction')
state = json.loads((root/'state.json').read_text())
assert state['version'] == 2 and state['phase'] == sys.argv[1]
assert (root/'original.gresource').stat().st_size > 0
print('PASS: persisted journal and original backup survived real SIGKILL')
PY
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$expected_sha" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
if [[ "$expected_active" == candidate ]]; then
  gresource list "$theme" | grep -F '/org/gnome/shell/theme/fedora-login-wallpaper.png'
fi
printf '%s\n' "$expected_phase" > "$HOME/crash-expected-phase"
printf '%s\n' "$expected_active" > "$HOME/crash-expected-active"
printf '%s\n' "$expected_sha" > "$HOME/crash-expected-sha"
echo "PASS: actual GDM theme matches $checkpoint journal + metadata"
GUEST

echo "=== Reboot Fedora VM while real installer journal remains install-prepared ==="
# Reboot closes SSH and can exit 255; the actual proof is a changed kernel boot ID.
ssh "${ssh_opts[@]}" "$guest" 'sudo systemctl reboot' || true
new_boot=0
for _ in $(seq 1 120); do
  if ! kill -0 "$qemu_pid" 2>/dev/null; then
    echo "FAILED: disposable VM died before reboot validation." >&2; exit 1
  fi
  if ssh "${ssh_opts[@]}" "$guest" \
    '[ "$(cat /proc/sys/kernel/random/boot_id)" != "$(cat "$HOME/boot-before.id")" ]' 2>/dev/null; then
    new_boot=1
    break
  fi
  sleep 5
done
if [[ "$new_boot" != 1 ]]; then
  echo "FAILED: Fedora VM never resumed with a new kernel boot ID." >&2; exit 1
fi

echo "=== Verify modified GDM theme survived reboot, then restore stock GDM ==="
ssh "${ssh_opts[@]}" "$guest" "bash -se -- '$CRASH_CHECKPOINT'" <<'RESTORE_GUEST'
set -Eeuo pipefail
cd "$HOME/veilpaper"
theme=/usr/share/gnome-shell/gnome-shell-theme.gresource
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$(cat "$HOME/candidate.sha")" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
sudo python3 experiments/gdm/vm_real_transaction.py status \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY' \
  | grep -Fx 'install-prepared: active=candidate'
sudo python3 experiments/gdm/vm_real_transaction.py restore \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$(cat "$HOME/stock-before.sha")" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
sudo rpm -V gnome-shell
sudo python3 experiments/gdm/vm_real_transaction.py status \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
echo "PASS: GDM original restored byte-for-byte across SIGKILL, reboot and fresh-process recovery"
echo "PASS: original owner, mode and SELinux context preserved; RPM verification clean"
RESTORE_GUEST

echo "PASS: real-theme post-swap SIGKILL + reboot + restore complete in disposable VM"
