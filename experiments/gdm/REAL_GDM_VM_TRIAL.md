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
It records original owner, group, file mode and readable SELinux metadata,
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
- Clean RPM file verification at the end.

See [guest CI harness](../../scripts/fedora44_vm_real_gdm_check.sh).

**Remaining blockers even if this test passes:** No graphical GDM login or
visible wallpaper is exercised in the headless Fedora Cloud Base guest.
The transaction has not yet qualified real SIGKILL interruptions at all write
points, sudden power loss, or independent console/TTY rescue. It is also not a
production privilege-separation design. The graphical Veilpaper application
does not use this guest-only tool; login Apply stays disabled.

Do not claim VM installation success until the specific guest CI run reports
successful post-reboot and RPM verification.
