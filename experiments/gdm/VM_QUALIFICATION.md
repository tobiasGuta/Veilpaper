# Disposable Fedora 44 VM qualification — read-only first gate

**Do not run this on the main laptop, an existing production VM, or Docker.** This is an experimental research procedure, not authorization to install or restore a live GDM theme. The VM-specific tool deliberately contains no live GDM writer.

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
