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

## First graphical CI attempt: BLOCKED (October 31, 2026)

[Graphical run 41249966043](https://github.com/tobiasGuta/Veilpaper/actions/runs/41249966043) **FAILED**, specifically at the **greeter-process identity check**. Fedora GNOME packages, RPM verification, wallpaper candidate preparation, and previous read-only fixture recovery checks passed. The guest reported a running `gdm.service` but did **not** create a GNOME Shell process under the GDM account. No pre-install screenshot was captured and no real resource swap was reached. This does **not** invalidate the independently passing GDM installation/recovery full-VM tests.

Likely setup factor, not yet proven as root cause: this experiment installed GNOME packages into an already booted Fedora Cloud guest and enabled GDM without first rebooting into its new `graphical.target` default.

A [second isolated run](https://github.com/tobiasGuta/Veilpaper/actions/runs/41252582148) now requires a full clean VM reboot **after graphical packages are installed and before any theme write**, with a different kernel boot ID, before testing GDM. If the greeter still fails to start, the harness collects guest `loginctl` seat status, DRM devices, GDM user processes, system and GDM journals, and one **diagnostic-no-greeter.png** capture through QMP if possible. That diagnostic image must **never** be called a passing greeter screenshot.

Graphical PASS remains withheld until the actual guest's GDM greeter is visible, the four original stage screenshots are captured and independently reviewed, and the original theme is restored and RPM-verified.

## Second graphical attempt: greeter identity false negative (October 31, 2026)

[Run 41252582148](https://github.com/tobiasGuta/Veilpaper/actions/runs/41252582148) **FAILED** at the initial real-greeter identity check, but the additional diagnostic logs conclusively showed that the Fedora GNOME greeter **was running** after reboot. Its `loginctl` session `c1` had class `greeter`, belonged to `seat0`, and used the dynamically allocated `gdm-greeter` Linux account (UID 60578). The process list also contained `/usr/bin/gnome-shell --mode=gdm` under that same account.

The harness had incorrectly checked `pgrep -u gdm`, so the running graphical greeter was rejected. The diagnostic-only QMP screenshot was successfully captured (1280 × 800) and uploaded; **no normal before/after wallpaper screenshots or guest GDM theme write occurred** in that failed run.

The corrected [guest greeter identity helper](../../scripts/verify_qemu_gdm_greeter.py) instead verifies a `gdm.service`, a `loginctl` session with `Class=greeter` and `Seat=seat0`, a GDM-specific account (`gdm` or `gdm-greeter`), and an actual `gnome-shell --mode=gdm` process with the identical numeric user ID. Ordinary GNOME desktop sessions are rejected. Regression tests cover both Fedora account conventions and false-positive conditions.

[The new QEMU graphical rerun](https://github.com/tobiasGuta/Veilpaper/actions/runs/41254281217) was started from that corrected code. **No graphical wallpaper acceptance can be claimed until four stage screenshots are captured and visually inspected, with clean final RPM restoration.**

## Third graphical attempt: numbered greeter account after restart (October 31, 2026)

[Run 41254281217](https://github.com/tobiasGuta/Veilpaper/actions/runs/41254281217) **FAILED** after the guest's actual GDM theme replacement. This time the initial real `seat0` greeter identity check passed (`gdm-greeter`), and the QMP **stock-greeter.png** was captured at 1280×800. The VM-installed candidate passed checksum and metadata verification, but after `systemctl restart gdm.service`, the harness rejected the newly created greeter session.

Diagnostics identified a **different GNOME Shell GDM greeter identity**: `loginctl` session `c3`, `Class=greeter`, `Seat=seat0`, `Name=gdm-greeter-2`, UID `60579`, and a matching `/usr/bin/gnome-shell --mode=gdm` process. The helper's previous exact allow-list only accepted `gdm` and `gdm-greeter`. GDM also emitted early `Session never registered` lines, so visual usability cannot be inferred from the process list alone.

The correction accepts only `gdm`, `gdm-greeter`, or strictly numbered `gdm-greeter-N` names (N positive integer without leading zero), still requiring an active GDM service, a real `seat0` `Class=greeter` session, and a matching same-UID GDM-mode GNOME Shell. Unit regressions include `gdm-greeter-2` and spoofed lookalikes. A new [independent graphical CI run](https://github.com/tobiasGuta/Veilpaper/actions/runs/41256181716) was triggered by adding the greeter helper to workflow path filters.

**Status: graphical wallpaper acceptance still pending.** Raw screenshot evidence must be collected for all four stages and visually reviewed; restoring the RPM original and authenticating a user remain separate gates. Previous VM install/recovery PASS results are unchanged.
