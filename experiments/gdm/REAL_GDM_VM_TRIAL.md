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
The transaction has not yet qualified real SIGKILL interruptions at all write
points, sudden power loss, or independent console/TTY rescue. It is also not a
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

**This scenario is limited to SIGKILL immediately after the real install
swap.** Install-intent, restore-intent and restore-swap process kills against
the live guest resource remain separate, unqualified scenarios, as do sudden
power loss and visible GDM graphical sign-in. A successful run does not permit
the GUI to install GDM themes or authorize ordinary host writes.

[Check the first post-swap crash VM trial](https://github.com/tobiasGuta/Veilpaper/actions/runs/41247600260).
