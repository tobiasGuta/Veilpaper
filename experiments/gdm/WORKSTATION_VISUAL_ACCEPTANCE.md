# Veilpaper: Fedora 44 Workstation graphical GDM qualification

Status: **BLOCKED / NOT QUALIFIED** until a person inspects a real virtual
console. No physical-host GDM modifications are permitted.

## Why unattended CI is paused

GitHub Actions [41256374904](https://github.com/tobiasGuta/Veilpaper/actions/runs/41256374904)
successfully booted Fedora 44 into graphical.target and verified a real
`seat0` `Class=greeter` session, account `gdm-greeter`, and
`gnome-shell --mode=gdm`. **Before any GDM resource write**, the virtual
display proof failed: `Virtual display blank/inactive: 0/16000 visible pixels`.
Even the newer private QEMU VNC backend plus a harmless Shift wake-up yielded
a black scanout. The screenshot guard correctly BLOCKED the transaction.

Earlier trials also produced black or inactive virtual display frames. These
results **do not** establish whether the failure is the guest GPU, Wayland
scanout, blanking, QMP capture, or the VNC backend. A process check cannot
settle appearance. No further automatic full GNOME installation runs should
be triggered by incidental code/doc commits.

The standalone crash-recovery and RPM-clean restoration qualifications from
separate disposable **headless** guests remain accepted for their narrow scope.
Do not re-run those tests merely to investigate a black graphical framebuffer.

## Next experiment: an interactive, disposable Workstation guest

Use the official **Fedora Workstation 44 x86_64 Live ISO**, not a Cloud Base
image with desktop components installed later:

- Official download: https://fedoraproject.org/workstation/download/
- Verify the official signed CHECKSUM before use. Fedora's published
  x86_64 ISO SHA-256 for 44-1.7 is
  `1620295f6a00c27c3208f0c00b8ece4eab1ec69b9002152d97488bf26a426ddf`.
- In GNOME Boxes or virt-manager, create **a new VM only**. Do not select or
  replace an existing VM or disk, host theme, or backup.
- Start with 4 vCPUs, 6–8 GB RAM, a **new** 40 GB or larger qcow2 guest disk,
  and a graphical Spice/VNC console visible to the operator. Adjust for host
  capacity; do not require 3D acceleration initially.
- Install the ISO inside the guest; boot the installed Workstation from its
  own virtual disk, with its own non-sensitive temporary user.
- Do **not** mount host home/development directories, enable host/guest shared
  folders, share the physical GDM theme, or pass through the host's GPU.
- Confirm the **stock** GDM greeter is visibly rendered in the virtual
  console **before** any Veilpaper installation or marker provisioning.
- Record guest release, GNOME Shell/GDM versions, display model, whether
  graphics acceleration is enabled, and a screenshot of the stock greeter.
- Take a **hypervisor snapshot of the clean guest** while it is shut down,
  with a proven way to revert from the host console.

### Read-only guest checks first

Run these commands **in a guest terminal only**, after logging in to the
disposable VM. They do not install themes:

```bash
cat /etc/fedora-release
rpm -q gnome-shell gdm
systemd-detect-virt --vm
systemctl get-default
sudo rpm -V gnome-shell
sha256sum /usr/share/gnome-shell/gnome-shell-theme.gresource
```

Report any mismatch or pre-existing theme/backup and **stop**. Do not attempt
to overwrite an unknown customization. This read-only check alone is not
sufficient authorization to write a system resource.

### Guest-only visual test (after clean stock greeter and approval)

1. Review candidate source and run Veilpaper's **build-only** and
   **install-check** steps inside the VM; independently confirm the original
   matches the guest's installed RPM and is not previously customized.
2. Keep any privileged experiment restricted by both disposable-VM markers,
   exact VM-only authorization, preflight, journal and backup requirements.
   Never transplant those markers to a physical workstation. Installation
   into this guest remains subject to explicit operator approval.
3. After guest-only installation, return to the VM's console and **visually**
   confirm the image is actually shown by the GDM greeter, not the lock screen
   or an already logged-in desktop. Capture a screenshot.
4. Verify display after an actual guest reboot, and test temporary user
   login, lock/unlock, logout, session return and relevant light/dark modes.
   Avoid real accounts and credentials.
5. Perform guest-only verified restoration. Reboot, capture the restored stock
   greeter and require a clean `sudo rpm -V gnome-shell`, including
   modification time, owner/mode and SELinux label.
6. If the guest cannot sign in or loses display, **do not attempt rescue on
   the host**. Power off the disposable VM, revert its clean snapshot, and
   preserve failure logs/screenshots if safe.

## Required evidence / acceptance decision

Keep four independently reviewed screenshots: stock, installed, after reboot
and restored. Capture GDM version, verified active process/session identity,
resource hashes, RPM restoration result and usability observations. If a
screen is black, cropped incorrectly, or not actually a GDM greeter, report
**PARTIAL / BLOCKED**, not graphical PASS.

Even a complete graphical guest PASS does **not** authorize application
writes on the developer's Fedora laptop. A production privileged helper must
still preserve existing custom themes, use scoped administrator approval and
fail-closed recovery, and pass its separate integration tests. The GUI's
**Apply to login screen** remains disabled until those gates are satisfied.

## Development decision

Do not keep running 389-package headless CI experiments to solve display
output. Continue safe, offline production-beta engineering in parallel while
manual Workstation graphical qualification is pending.
