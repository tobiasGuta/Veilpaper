# Graphical GDM greeter qualification — evidence-capture stage

**Not a public installer. Do not run this on a physical workstation.**

The original real-GDM install, reboot, full-RPM restore, and four crash-checkpoint
recoveries were verified in disposable Fedora 44 guests. Those results confirm
the *file and journal behavior*, not the appearance of the GDM sign-in screen.

## Test environment and provenance

[Graphical GDM evidence workflow](../../.github/workflows/fedora44-vm-gdm-visual.yml)
boots a **full-machine Fedora 44 QEMU guest**, based on an official,
SHA-256-pinned *Fedora Cloud Base* image, then installs GNOME Shell, GDM,
GNOME session components and Mesa graphics **inside the guest**.

**Important:** This is a GNOME-equipped Cloud guest, **not** an installation
from the official Fedora Workstation Live ISO. That distinction must remain
explicit in reports. A separate Fedora Workstation ISO / installed-Workstation
test is still required for an edition-specific compatibility claim.

The guest has an isolated qcow2 overlay, a virtual GPU, a QMP UNIX socket on
the ephemeral CI runner, and no user laptop directories or drives mounted.
The runner never restarts its own GDM. QEMU screenshots are captured through
the [QMP read-only helper](../../scripts/qemu_capture_greeter.py).

## Acceptance and limits

The VM test must first demonstrate a real running gdm.service **and** a
GNOME Shell process belonging to the gdm user. A boot splash or ordinary
user desktop is not a greeter and must not be accepted as visual evidence.

Only after that guest identity check and pre-install screenshot does it
provision both root-owned, mode-0600 VM-only write markers, re-review the
stock RPM baseline and candidate, then install the custom wallpaper.

If GDM starts and QMP capture succeeds, the workflow stores four PNGs:

- stock-greeter.png — before any guest theme modification
- customized-greeter.png — after guest-only theme install/restart
- customized-after-reboot.png — modified theme after actual guest reboot
- restored-greeter.png — after guest-only original theme restoration

The workflow uploads these files under the
"fedora44-gnome-gdm-greeter-screenshots" GitHub Actions artifact name, with a
short retention period. It verifies exact package resource SHA-256 and metadata
and a clean final rpm -V gnome-shell, as in earlier VM gates.

**A green workflow can mean screenshot capture + system validation, but
cannot, alone, prove that the artwork is correctly visible or cropped.**
Screenshots must be independently inspected and checked for a real greeter,
not a desktop/TTY, all greeter controls, correct image coverage, and return
to stock appearance. QMP structural PNG checks never assert visual PASS.

## Remaining blockers

- A dedicated actual Fedora 44 Workstation image / installed GNOME greeter
  trial and reviewed before/after screenshots.
- Real user password login, lock/unlock and session return (not merely GDM
  service/process existence), and light/dark mode appearance.
- Emergency console recovery and machine hard-power-loss trials.
- Production-safe privilege separation and system administrator approval.

The laptop's original login-screen customization must remain unchanged.
The production GUI has no GDM Apply action and remains intentionally blocked.

[Open the graphical experiment workflow](https://github.com/tobiasGuta/Veilpaper/actions/workflows/fedora44-vm-gdm-visual.yml)
