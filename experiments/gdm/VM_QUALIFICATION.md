# Disposable Fedora 44 VM qualification — read-only first gate

**Do not run this on the main laptop, an existing production VM, or Docker.** This is an experimental research procedure, not authorization to install or restore a live GDM theme. The VM-specific tool deliberately contains no live GDM writer.

## Reproducible GitHub Actions full-VM test (read-only)

The experimental [Fedora 44 full-VM admission workflow](../../.github/workflows/fedora44-qemu-vm.yml)
uses `scripts/fedora44_qemu_vm_check.sh` to boot a **separate full-machine
QEMU guest** on an ephemeral GitHub-hosted Linux runner. It downloads the
official Fedora Cloud Base 44 QEMU image, checks its pinned SHA-256 against
Fedora's published digest, creates a disposable copy-on-write disk and
cloud-init SSH identity, transfers only required Veilpaper source files, and
runs the exact read-only VM admission gate inside the guest.

A full VM requires no hardware KVM acceleration: if unavailable, the harness
explicitly uses **QEMU TCG software machine emulation** instead. TCG is slower,
but it still emulates a full guest OS and is not a Docker container. Both modes
must satisfy `systemd-detect-virt --vm` inside Fedora. KVM and TCG are separate
from the existing Fedora container integration tests.

GitHub's standard runners do not guarantee nested KVM availability. The
workflow **fails closed** if the guest does not boot, package verification
fails, the required marker does not block before provisioning, any of the five
recovery simulations fail, or the original GDM resource/backup state changes.
The CI test never installs a custom GDM theme. Its positive result must not be
interpreted as safe graphical GDM startup or crash-safe live restoration.

Do not run the CI harness on your laptop: it explicitly checks for an
ephemeral GitHub Actions environment. Its guests are removed after the job.
Any test still in progress or unsuccessful is **not** a full-VM qualification.

## Create a disposable environment

Provision a **new Fedora 44 full virtual machine** using QEMU/KVM/libvirt, with a working console and unmodified GNOME Shell package. Take an **external hypervisor disk snapshot** first. Never expose host system or home paths as writable guest mounts.

Verify these commands **inside the disposable guest**:

~~~bash
cat /etc/fedora-release
systemd-detect-virt --vm
! systemd-detect-virt --container
rpm -q gnome-shell gdm
rpm -V gnome-shell
~~~

If any check fails, stop. A physical host and a container must both be refused. The tool supports Fedora 44 only.

Check out the Veilpaper experimental branch **in the guest** and use an ordinary test PNG/JPEG file present in its home:

~~~bash
python3 veilpaper.py login preflight
python3 veilpaper.py login baseline
python3 veilpaper.py login portable-build "$HOME/Pictures/test-login.png" \
  --output "$HOME/veilpaper-vm-candidate.gresource"
python3 veilpaper.py login install-check "$HOME/veilpaper-vm-candidate.gresource"
~~~

A pristine first-time target should return STRUCTURALLY_ELIGIBLE_FOR_OFFLINE_REVIEW. A customization, backup/state, or unexpected candidate resource MUST block it. A review PASS is not permission to write GDM.

## Provision an explicit VM-only marker

Only **inside this new disposable VM**, create its root-only marker:

~~~bash
printf 'VEILPAPER-DISPOSABLE-FEDORA44-VM-ONLY\n' | \
  sudo tee /etc/veilpaper-disposable-vm-qualification >/dev/null
sudo chown root:root /etc/veilpaper-disposable-vm-qualification
sudo chmod 0600 /etc/veilpaper-disposable-vm-qualification
~~~

Run the read-only gate (the built candidate must exist inside the VM):

~~~bash
sudo python3 experiments/gdm/vm_gate.py \
  --candidate "$HOME/veilpaper-vm-candidate.gresource" \
  --confirm 'DISPOSABLE FEDORA 44 VM'
~~~

Expected: VM_READ_ONLY_ADMISSION_PASS, source/candidate digests, five successful **temporary-directory** recovery simulations, and install_performed: False.

The gate must refuse physical hosts, containers, wrong Fedora versions, unsafe/missing markers, customized GDM, and preexisting manager state. It does **not** write to /usr/share/gnome-shell, change GDM backups or restart a session.

## Next separate qualification

A true VM-only privileged transaction prototype has **not** been implemented or tested. Before that, require an independent review of exact ownership/mode/SELinux handling, verified backup, crash-safe journal and atomic replacement, failure injection, TTY rollback and a real GDM boot/unlock test after reboot. Revert using the **hypervisor snapshot**, not an in-guest rollback, if the test environment becomes unusable.

A future narrowly authorized system helper must repeat every preflight itself. Neither a VM gate PASS nor prior conversational consent authorizes writing to the host GDM theme. Keep the GUI **Apply to login screen** disabled until a separate isolated-VM install-and-recovery trial succeeds.
