#!/usr/bin/env bash
# Experimental graphical GDM visual evidence in disposable Fedora 44 GNOME VM.
# Captures unaltered framebuffer PNGs through QMP before/after live guest GDM swap.
# Collected screenshots still REQUIRE manual visual review.
# Never run this on a developer laptop.
set -Eeuo pipefail
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
[[ -f "$GITHUB_WORKSPACE/scripts/qemu_capture_greeter.py" ]] || exit 1
[[ -f "$GITHUB_WORKSPACE/scripts/verify_qemu_gdm_greeter.py" ]] || exit 1
screenshots="$RUNNER_TEMP/veilpaper-gdm-visual"
mkdir -p "$screenshots"
chmod 0700 "$screenshots"
snapshot() {
  local name="$1"
  local options=(--socket "$work/qmp.sock" --output "$screenshots/$name.png")
  if [[ "$name" != diagnostic-* ]]; then
    options+=(--wake-display --require-visible-display)
  fi
  python3 "$GITHUB_WORKSPACE/scripts/qemu_capture_greeter.py" "${options[@]}"
}
verify_greeter() {
  local attempt=0
  while (( attempt < 45 )); do
    if ssh "${ssh_opts[@]}" "$guest" \
      'python3 "$HOME/veilpaper/scripts/verify_qemu_gdm_greeter.py"' 2>/dev/null; then
      echo 'GREETER_PROCESS_CONFIRMED: seat0 Class=greeter and matching GNOME Shell --mode=gdm'
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 6
  done
  echo 'BLOCKED: real GNOME GDM greeter process did not start' >&2
  echo '=== GDM/seat/DRM debug evidence from this disposable guest ===' >&2
  ssh "${ssh_opts[@]}" "$guest" 'bash -se' <<'DIAGNOSTICS' >&2 || true
set +e
printf '\n== boot mode ==\n'
cat /proc/cmdline
systemctl get-default
systemctl is-active graphical.target systemd-logind.service gdm.service
printf '\n== graphical seat ==\n'
loginctl list-seats
loginctl seat-status seat0
printf '\n== graphics devices ==\n'
ls -l /dev/dri /dev/tty0 /dev/tty1 /dev/fb0 2>&1
readlink -f /sys/class/drm/card*/device/driver 2>&1
printf '\n== session and user processes ==\n'
loginctl list-sessions
ps -eo user,pid,tty,args | grep -E '[g]dm|[g]nome-shell|[X]org|[X]wayland'
printf '\n== GDM journal last 100 ==\n'
sudo journalctl -b -u gdm -n 100 --no-pager
printf '\n== GDM user journal last 100 ==\n'
sudo journalctl -b _UID=42 -n 100 --no-pager
printf '\n== display/seat errors ==\n'
sudo journalctl -b --no-pager -p warning -n 70
DIAGNOSTICS
  # Preserve a raw QEMU diagnostic framebuffer even if no actual greeter
  # exists. Never label diagnostic evidence as stock/customized greeter.
  snapshot diagnostic-no-greeter >&2 || true
  return 1
}

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
# Expand disposable overlay for GNOME+Mesa packages; never touch a host disk.
qemu-img resize "$work/overlay.qcow2" +18G >/dev/null

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
qemu-system-x86_64 -machine "accel=$accel" -cpu "$cpu" -smp 4 -m 6144 \
  -drive file="$work/overlay.qcow2",format=qcow2,if=virtio \
  -drive file="$work/seed.iso",format=raw,media=cdrom,if=virtio \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:22357-:22 \
  -device virtio-net-pci,netdev=net0 \
  -vga none -device virtio-vga \
  -display "vnc=unix:$work/guest-vnc.sock" \
  -qmp "unix:$work/qmp.sock,server=on,wait=off" \
  -serial "file:$work/serial.log" -monitor none \
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
  scripts/verify_qemu_gdm_greeter.py \
  | ssh "${ssh_opts[@]}" "$guest" \
    'mkdir -p "$HOME/veilpaper" && tar -xf - -C "$HOME/veilpaper"'

echo "=== Install GNOME graphical prerequisites only inside isolated Fedora guest ==="
ssh "${ssh_opts[@]}" "$guest" 'bash -se' <<'GUEST'
set -Eeuo pipefail
cd "$HOME/veilpaper"
cat /etc/fedora-release
systemd-detect-virt --vm
! systemd-detect-virt --container
sudo dnf install -y --setopt=install_weak_deps=False \
  gnome-shell gdm glib2-devel gnome-session gnome-settings-daemon \
  mesa-dri-drivers mesa-libEGL xorg-x11-server-Xwayland
sudo systemctl set-default graphical.target
sudo systemctl enable --now gdm.service
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
# Distinct saturated test target visible only in disposable VM.
w, h = 1280, 720
rows = bytearray()
for y in range(h):
    rows.append(0)
    for x in range(w):
        band = (x // 160 + y // 120) % 3
        rows.extend(((245, 48, 120), (20, 230, 205), (248, 224, 37))[band])
img = (b'\x89PNG\r\n\x1a\n' +
       chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
       chunk(b'IDAT', zlib.compress(bytes(rows), 6)) +
       chunk(b'IEND', b''))
Path.home().joinpath('login-ci.png').write_bytes(img)
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
echo 'PASS: read-only GDM candidate admission finished before graphical install'
GUEST

echo '=== Reboot newly provisioned GNOME guest into graphical.target ==='
# Enabling the display manager in an already-booted Cloud image does not
# guarantee logind/seat0 and the virtual GPU are initialized for its greeter.
# Reboot once BEFORE any GDM file edits; prove a new kernel boot ID.
boot_before_gui="$(ssh "${ssh_opts[@]}" "$guest" 'cat /proc/sys/kernel/random/boot_id')"
ssh "${ssh_opts[@]}" "$guest" 'sudo systemctl reboot' || true
graphical_boot=0
for _ in $(seq 1 120); do
  if ! kill -0 "$qemu_pid" 2>/dev/null; then
    echo 'BLOCKED: VM died during clean graphical-target reboot' >&2; exit 1
  fi
  observed="$(ssh "${ssh_opts[@]}" "$guest" 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || true)"
  if [[ -n "$observed" && "$observed" != "$boot_before_gui" ]]; then
    graphical_boot=1
    break
  fi
  sleep 5
done
if [[ "$graphical_boot" != 1 ]]; then
  echo 'BLOCKED: graphical-target guest did not return after first reboot' >&2; exit 1
fi
echo 'PASS: Fedora full VM rebooted into configured graphical.target'
echo '=== Require the GDM greeter, then capture stock virtual display ==='
verify_greeter
snapshot stock-greeter

echo '=== Proceed with guarded candidate installation INSIDE disposable guest ==='
ssh "${ssh_opts[@]}" "$guest" 'bash -se' <<'INSTALL_GUEST'
set -Eeuo pipefail
cd "$HOME/veilpaper"
theme=/usr/share/gnome-shell/gnome-shell-theme.gresource
echo "=== Creating second root-only marker for real GDM replacement in guest ==="
printf 'VEILPAPER-REAL-GDM-WRITES-IN-DISPOSABLE-VM-ONLY\n' | \
  sudo tee /etc/veilpaper-disposable-vm-GDM-write-test >/dev/null
sudo chown root:root /etc/veilpaper-disposable-vm-GDM-write-test
sudo chmod 0600 /etc/veilpaper-disposable-vm-GDM-write-test

sha256sum "$theme" | cut -d' ' -f1 > "$HOME/stock-before.sha"
stat -c '%u:%g:%a:%C:%y' "$theme" > "$HOME/stock-before.meta"
sha256sum "$HOME/vm-candidate.gresource" | cut -d' ' -f1 > "$HOME/candidate.sha"
cat /proc/sys/kernel/random/boot_id > "$HOME/boot-before.id"
sudo python3 experiments/gdm/vm_real_transaction.py install \
  --candidate "$HOME/vm-candidate.gresource" \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
sudo python3 experiments/gdm/vm_real_transaction.py status \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$(cat "$HOME/candidate.sha")" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
gresource list "$theme" | grep -F '/org/gnome/shell/theme/fedora-login-wallpaper.png'
echo "PASS: actual GDM resource swapped and original metadata preserved INSIDE VM"
sudo systemctl restart gdm.service
INSTALL_GUEST

echo '=== Capture modified GDM greeter (not a simulated desktop) ==='
verify_greeter
snapshot customized-greeter

echo "=== Reboot the full Fedora VM with customized theme installed ==="
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

echo "=== Verify graphical greeter after reboot with modified guest GDM theme ==="
verify_greeter
snapshot customized-after-reboot
echo "=== Verify modified GDM theme survived reboot, then restore stock GDM ==="
ssh "${ssh_opts[@]}" "$guest" 'bash -se' <<'RESTORE_GUEST'
set -Eeuo pipefail
cd "$HOME/veilpaper"
theme=/usr/share/gnome-shell/gnome-shell-theme.gresource
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$(cat "$HOME/candidate.sha")" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
sudo python3 experiments/gdm/vm_real_transaction.py restore \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
[[ "$(sha256sum "$theme" | cut -d' ' -f1)" == "$(cat "$HOME/stock-before.sha")" ]]
[[ "$(stat -c '%u:%g:%a:%C:%y' "$theme")" == "$(cat "$HOME/stock-before.meta")" ]]
sudo rpm -V gnome-shell
sudo python3 experiments/gdm/vm_real_transaction.py status \
  --confirm 'I AUTHORIZE DISPOSABLE FEDORA 44 VM GDM WRITES ONLY'
echo "PASS: GDM theme restored byte-for-byte after Fedora VM reboot; original RPM mtime retained"
echo "PASS: original owner, mode and SELinux context preserved; RPM verification clean"
sudo systemctl restart gdm.service
RESTORE_GUEST

echo '=== Capture stock greeter restored after independent RPM-verifying rollback ==='
verify_greeter
snapshot restored-greeter
echo 'SCREENSHOT_EVIDENCE_CAPTURE_PASS: stock, customized, reboot, restored QEMU displays recorded'
echo 'VISUAL_REVIEW_REQUIRED: capture alone cannot prove background, crop or login functionality'
echo "PASS: real GDM install/reboot/restore complete in ephemeral VM; CI destroys overlay and SSH identity"
