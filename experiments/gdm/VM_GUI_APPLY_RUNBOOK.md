# Veilpaper — VM-only graphical Apply integration

Status: **CODE AND UNIT TESTS IMPLEMENTED; REAL GRAPHICAL/POLKIT ACCEPTANCE NOT YET PASSED**.

This workflow is only for a disposable full Fedora 44 VM with a recovery
snapshot and an operator-controlled console. It must **never** be used to
provision a production laptop or copy the root-only test markers to a host.

## Architecture

The native GTK Login screen now has an **Apply in disposable VM…** button.
It only becomes sensitive after:

1. An unprivileged prepared wallpaper candidate is built.
2. **Review readiness** reports `STRUCTURAL_REVIEW_ONLY`, not authorization.
3. A separate VM-only preflight finds Fedora 44, a full non-container VM,
   both independent root-owned marker files, a complete root-owned helper
   bundle, `/usr/bin/pkexec`, and a dedicated trusted Polkit policy.

Clicking prompts a second GTK confirmation and then invokes the *fixed*
root-owned path `/usr/libexec/veilpaper-guest/scripts/gdm_guest_installer.py`
through Polkit (no shell and no user-writable Python interpreter/script).
The administrator may deny authentication. The root helper independently
repeats **both VM-only marker-content checks** and the full VM guard, then
revalidates the exact expected candidate SHA-256 under the transaction lock.
The existing VM journal/backup transaction writer performs the install.

**No GDM restart is triggered automatically.** The guest's graphical greeter
must be independently inspected. Neither GTK confirmation nor Polkit
authentication implies the graphical appearance passed.

## Manual VM-only preparation (not performed automatically)

Only after creating a new, isolated Fedora 44 VM, taking its snapshot and
verifying the GDM greeter and a separate guest administrator account should
the operator use the prior VM qualification runbook to create BOTH required
root-owned marker files **inside that guest**.

From a verified project checkout **inside that same disposable VM**, and
only with the exact VM markers already provisioned, a human operator can run:

```bash
sudo /usr/bin/python3 scripts/provision_vm_guest_helper.py
```

This manual script calls the existing full VM/marker gate **before any
system write**, refuses to overwrite a pre-existing helper or Polkit policy,
and installs only its explicit allowlisted root-owned helper code under
`/usr/libexec/veilpaper-guest` and the dedicated Polkit action. The GUI
bundle does **not** contain or deploy the privileged helper.

Afterward, run the GTK app **as an ordinary account in the VM**, build a
candidate, request the read-only readiness review, and choose the VM-only
Apply action. Polkit may request guest administrator authentication.

If the action is denied, interrupted, or reports an unexpected result,
do not repeat it blindly. Preserve the VM journal and backup, and recover
using the disposable VM snapshot or the independently reviewed guest
transaction procedure. Do **not** use the host's login configuration.

## Release blockers

- **Interactive Fedora Workstation** GDM wallpaper/login/reboot/restoration
  still needs direct visual and usability testing.
- Real Polkit authorization and denial behavior in the interactive VM
  remains unqualified; current tests mock the authorization process.
- The GUI does not yet offer a production Restore operation. Existing
  guest transaction restore remains separately tested and guarded.
- A **general Fedora production installer** does not yet exist.
  Never provision the VM markers on the developer laptop.

Relevant files: `gui/vm_install_bridge.py`,
`scripts/gdm_guest_installer.py`,
`scripts/provision_vm_guest_helper.py`,
`packaging/me.tobiasguta.Veilpaper.Guest.policy`.
