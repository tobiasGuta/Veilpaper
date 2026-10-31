# Veilpaper guest-only GDM installation trial

**Experimental. Never run on a workstation or use as a general installer.**

The [isolated Fedora VM workflow](../../.github/workflows/fedora44-vm-real-gdm.yml)
uses an ephemeral Fedora 44 full-machine QEMU guest. Its qcow2 overlay is
destroyed after the job. No laptop directories are mounted into the guest.

The prototype [VM real transaction](vm_real_transaction.py) requires:

- Root *inside* a Fedora 44 full VM, rejecting containers and physical hosts.
- Two separately provisioned root-owned, mode-0600 marker files, including
  a second marker specifically authorizing disposable guest GDM writes.
- The exact VM-only confirmation phrase on each operation.
- A stock GDM resource matching the installed RPM database, independently
  reviewed candidate and no pre-existing legacy manager state or backup.
- Exclusive lock, root-owned private lab directory and journal.

## Guest installation sequence

First-time installation re-runs resource/RPM review in the privileged process.
It records original owner, group, file mode, nanosecond modification time and readable SELinux metadata,
then writes and fsyncs a new original backup, without overwriting anything.
After persisting the install journal, it replaces the actual package-owned
GDM resource atomically and checks the new checksum and original metadata.
It then persists the installed phase. Unknown third-party changes block.

## Guest restoration sequence

Restoration requires a valid journal, matching original backup and an active
theme with one of the known original/candidate checksums. A restore intent is
persisted before atomic replacement. The original checksum, owner, mode and
SELinux label are checked and the journal is marked restored. Both backup and
journal remain for audit. There is no general update or removal feature.

## CI acceptance criteria

- Verified original checksum and metadata before installation.
- Verified candidate resource and same owner/mode/SELinux label after installation.
- A real guest reboot, validated by a changed Linux kernel boot ID.
- Candidate GDM theme still installed after reboot.
- Verified original GDM checksum and metadata after restoration.
- Clean RPM file verification at the end, including the original modification timestamp.

See [guest CI harness](../../scripts/fedora44_vm_real_gdm_check.sh).

**Remaining blockers even if this test passes:** No graphical GDM login or
visible wallpaper is exercised in the headless Fedora Cloud Base guest.
The four planned real-resource SIGKILL checkpoints have now passed in isolated
Fedora VMs, but sudden power loss and independent console/TTY rescue remain unqualified. It is also not a
production privilege-separation design. The graphical Veilpaper application
does not use this guest-only tool; login Apply stays disabled.

Do not claim VM installation success until the specific guest CI run reports
successful post-reboot and RPM verification.

## RPM timestamp regression — October 31, 2026

The first real-VM install/reboot/restore run, [41244248252](https://github.com/tobiasGuta/Veilpaper/actions/runs/41244248252), **failed** at the final `rpm -V gnome-shell` check. Candidate installation, reboot persistence, and byte-for-byte resource restoration succeeded. RPM reported `.......T.` for the theme resource: its file modification timestamp changed during atomic replacement, even though the SHA-256 and owner/mode/SELinux context matched.

The correction stores the packaged original's `st_mtime_ns` in the durable version-2 transaction record, stamps the staging inode before atomic publication for both install and restore, and verifies the restored timestamp. The full-VM script now checks nanosecond timestamp equality before/after the reboot. The corrected [real-GDM install/reboot/restore run passed](https://github.com/tobiasGuta/Veilpaper/actions/runs/41245722339), including clean RPM verification and the original modification time.

## Separate real-resource SIGKILL qualification (post-swap)

The normal transaction API still has **no failure-injection switch**.
The independent, dual-marker-gated [VM-only crash injector](vm_real_crash_injector.py)
intercepts only publication of the actual theme in a disposable Fedora 44 VM.
After the underlying atomic rename and directory fsync succeed, the injector
sends SIGKILL to its own process, before the journal transitions from
install-prepared to installed.

The [independent QEMU workflow](../../.github/workflows/fedora44-vm-real-gdm-crash.yml)
executes [the crash harness](../../scripts/fedora44_vm_real_gdm_crash_check.sh)
in a fresh Fedora guest, never on the host or laptop. It requires child exit
status 137, install-prepared journal plus original backup, candidate checksum
and resource verification, preserved ownership/mode/SELinux/timestamp, a full
Fedora reboot with a changed kernel boot ID, then a separate, authorized
restoration command. Final acceptance also requires a clean
`rpm -V gnome-shell` and exact original theme hash.

**This specific scenario is limited to SIGKILL immediately after the real install
swap.** The other three checkpoints were independently qualified later.
Sudden power loss and visible GDM graphical sign-in remain unqualified. A
successful VM run does not permit the GUI to install GDM themes or authorize
ordinary host writes.

[Check the first post-swap crash VM trial](https://github.com/tobiasGuta/Veilpaper/actions/runs/41247600260).

## Remaining real-resource interruption checkpoints

The [three-checkpoint QEMU workflow](../../.github/workflows/fedora44-vm-remaining-crash.yml) now starts a **separate Fedora 44 full VM and overlay for each** of these scenarios: `install-intent` (original resource + prepared install journal), `restore-intent` (candidate resource + prepared restore journal), and `restore-swap` (original resource + prepared restore journal). The previously passing `install-swap` recovery is retained as a separate workflow, unchanged.

Each real-resource trial checks privileged-process SIGKILL (exit 137), exact journal phase, verified immutable original backup, original-owner/mode/SELinux/mtime, the expected resource SHA-256 **before and after a full VM reboot**, and a fresh-process restoration followed by `rpm -V gnome-shell`. Tests are limited to disposable guests with both root-owned markers and explicit guest-only confirmation; the normal GUI still cannot invoke the injector.

**PASS — All three real-resource SIGKILL checkpoints qualified** in [GitHub run 41248524267](https://github.com/tobiasGuta/Veilpaper/actions/runs/41248524267). Each independent Fedora VM verified SIGKILL, persisted journal and backup, reboot, fresh-process restoration, and clean `rpm -V gnome-shell`. Together with the earlier [install-swap PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41247600260), all four planned process-crash checkpoints have VM evidence. Physical disk power-loss recovery is not established by SIGKILL.

## Graphical GDM qualification — next acceptance gate

A headless Fedora Cloud VM cannot prove what a person sees at the GDM greeter. Graphical qualification must use a separate **disposable Fedora 44 GNOME Workstation full VM** with a genuine GDM greeter under a real virtual display, never the user's laptop. The experiment should:

1. Capture a clean stock greeter image in the virtual display for comparison, without exposing passwords or personal information.
2. Validate login candidate CSS and wallpaper resource on the stock GNOME Shell 50 and GDM package versions, with matching RPM preflight and VM-only guard.
3. Install the candidate **only** inside the VM, boot to the real graphical GDM greeter, then independently confirm the wallpaper is visible and properly cropped in the greeter, rather than assuming resource integrity implies a visual pass.
4. Verify user login, lock, unlock, session return, reboot, and both light/dark style behavior; avoid confusing the GNOME lock screen with the GDM login greeter.
5. Restore the original GDM theme via the VM-only transaction, reboot and verify the stock graphical greeter and clean `rpm -V gnome-shell`.
6. Ensure an independent hypervisor snapshot rollback and accessible emergency console exist if GDM is unusable. Do not run these tests against an existing customized GDM installation.

**Until graphical evidence and full interruption/recovery qualifications are verified, Apply to login screen stays disabled.**
