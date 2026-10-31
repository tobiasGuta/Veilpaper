# Veilpaper

**Your screens. Your wallpapers.**

Veilpaper is an experimental GNOME wallpaper manager that controls **GDM login** and **lock-screen** backgrounds independently of the desktop wallpaper.

> **Development branch only. No supported installer or release yet.** This code modifies GNOME internals. Do not assume Fedora/GNOME-wide compatibility from one machine's success.

## Verified milestone — October 31, 2026

| Component | Current evidence |
| --- | --- |
| GDM login wallpaper | **Visual PASS** after reboot: Fedora 44, GNOME Shell 50.6, GDM 50.3 |
| Lock wallpaper extension | **Visual PASS** after `Super+L` on the same laptop; enabled and ACTIVE |
| Unified entry point | **CLI status PASS** on Fedora 44; lock image conversion completed; **68/68 CLI/backend tests PASS and user-installed command verified on Fedora 44** |
| Lock image handling | **Visual PASS** after real WebP-to-PNG conversion; resulting file identified as `image/png` |
| GDM portability preflight | Read-only structural inspection implemented; not a generic apply or restore mechanism |
| RPM baseline comparison | Read-only active/backup SHA-256 comparison against installed package metadata; **18/18 tests PASS** on Fedora 44 |
| Portable GDM candidate builder | **PASS** on Fedora 44 stock RPM in container and full VM; unprivileged build only |
| GDM transaction simulation | Five disposable fixture recovery cases and four process-SIGKILL fixture cases **PASS** in Fedora full VM |
| First-time GDM install review | New read-only, fail-closed resource/RPM verification; no live installer or authorization |
| One-command user launcher | **PASS:** installed `~/.local/bin/veilpaper` on Fedora 44, ran status, lock set, and RPM baseline with no GDM writes |
| Fedora 44 stock-RPM integration | **PASS** in isolated container: stock RPM, portable candidate build, first-time install-check, five transaction simulations, unchanged GDM theme |
| Native GNOME GUI (GTK4 + libadwaita) | **Lock workflow and login build-only preview/details visually PASS** on Fedora 44 GNOME Wayland |
| Disposable Fedora VM admission | **PASS** in disposable Fedora 44 full VM; read-only RPM review, five recoveries, four SIGKILL fixture tests |
| Real GDM install/reboot/restore (guest-only) | **PASS** in disposable Fedora 44 VM, including original SHA-256, mode, SELinux label, timestamp and clean RPM verification |
| Real GDM SIGKILL recovery (all four journal/swap checkpoints) | **PASS** in disposable Fedora 44 full VMs, including reboot, recovery and clean RPM verification; standard desktop Apply remains disabled |
| Install/restore across machines | **Not ready** |

The login tool requires a specific verified original GDM checksum. It will refuse unknown host originals, and that is intentional. **Do not apply the login theme tool on another system.**

The lock extension uses GNOME Shell private APIs. Full regression tests—including normal password unlock, extension disable, upgrade effects, and SELinux behavior—remain outstanding.

## VM-only qualification and candidate details (experimental)

**Verified CI checkpoint (October 31, 2026):** [Fedora full-VM admission and fixture SIGKILL recovery PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41240345815), followed by [real GDM install, reboot and byte-for-byte restore PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41245722339). [Real-theme install-swap SIGKILL recovery PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41247600260) and [all three remaining real SIGKILL checkpoints PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41248524267). The production GUI still cannot install a login wallpaper; graphical GDM and power-loss qualifications remain outstanding.



The Login screen card now stays compact after building a candidate. Instead of
printing the long filesystem path and 64-character SHA-256 into the main card,
it shows a short **candidate verified — not installed** confirmation. The
**View details** control exposes the full selectable path, SHA-256 and a copy
action; it is disabled if nothing has been verified, and clears on reset.

A new **read-only VM admission** tool lives at
[experiments/gdm/vm_gate.py](experiments/gdm/vm_gate.py). It requires:
a full Fedora 44 VM (not the physical host or container), an exact root-owned,
mode-0600 qualification marker, clean RPM-matching GDM theme, no existing
manager state or backup, exact candidate-diff validation and five temporary
recovery simulations. It outputs a report with install_performed: False.

See [the disposable VM qualification runbook](experiments/gdm/VM_QUALIFICATION.md)
for an isolated guest-only procedure. **It must not be run or marked on the
main laptop. The only privileged writer is a **separately marked,
disposable-VM-only experiment**; it is NOT a general installer and the GUI
still cannot install a login wallpaper. Even a successful guest test will
not prove graphical GDM operation, emergency recovery, or power-loss safety.

## Build a login wallpaper candidate through the GUI (experimental)

The GUI now offers a new, **build-only** workflow under the Login screen card:
**Choose image → Build candidate**. It accepts PNG/JPEG and GNOME-readable
images such as WebP (normalized to real PNG), previews the selected image and
builds an independently checked GDM resource from a theme matching the
installed RPM database. No root privileges are requested.

A successful build saves a candidate to a private path such as:
`~/.cache/veilpaper/login-candidates/prepared-*/candidate.gresource`,
mode `0600`. The GUI displays that path and its SHA-256 digest. The
application does **not** install this candidate, replace GDM, restart the
display manager, or modify any existing GDM backup/state. The prior
login-screen image remains active until a separately reviewed and authorized
installer is qualified.

This works even when the development host already has a customized login
screen, provided an independent backup still matches the installed RPM. The
candidate is checked *against the stock baseline*, not treated as a
first-time installation authorization. Old candidate files remain in the
user cache; remove them manually when no longer needed. Do not use the
legacy host-specific `login apply` to install one of these candidates.

The GUI bundle manifest is now **v3** and bundles the portable builder and
candidate reviewer. Its installer remains able to safely uninstall v1/v2
application bundles before upgrading.

**Integration result:** [Fedora 44 stock-RPM GUI candidate test — PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41238287285). An unprivileged user prepared and verified a real compiled GDM candidate in a disposable Fedora container, and the package-owned GDM theme remained unchanged. This is not a real graphical login or privileged installation test.

## Native GNOME GUI prototype

Veilpaper now includes a **GTK4/libadwaita** application. It uses the existing
Veilpaper CLI backend for lock-screen writes; login/GDM controls remain
**read-only** until a separate portable, privileged installer is qualified.
The GUI offers an image preview before applying, a default-lock reset,
current lock extension status, a login image preview (when present) and GDM
baseline status. It does not require sudo and cannot modify the desktop wallpaper.

Fedora package prerequisites:

```bash
sudo dnf install python3-gobject gtk4 libadwaita
```

Preview directly from the repository, before installing:

```bash
python3 gui/veilpaper_gui.py
```

Add **Veilpaper** to the GNOME Applications menu using the separate optional
GUI launcher (this **does not** replace the working `veilpaper` CLI):

```bash
python3 scripts/gui_install.py install
python3 scripts/gui_install.py status
```

After installation, open **Veilpaper** from GNOME's application overview, or
run `~/.local/bin/veilpaper-gui`. The initial Fedora Wayland screenshot confirmed
that both backgrounds render, but the lock preview was heavily cropped and the
main cards stretched to the full maximized window width. The subsequent
experimental refinement uses **GTK ContentFit.CONTAIN** for whole-image
previews and a centered **Adw.Clamp** for readable, responsive layouts.

### Adaptive two-panel interface (experimental)

**CI:** [Responsive GUI smoke PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41236769207), including width clamp, horizontal two-panel structure, whole-image preview and status checks. GTK4/libadwaita window creation and all 90 Python backend/installer tests passed.

Before updating the no-overwrite installed GUI bundle, close Veilpaper and preview the latest checkout with:

```bash
python3 gui/veilpaper_gui.py
```

If the design is satisfactory, close the preview and run the separate GUI uninstall/install commands below. **Do not** update or restore GDM to try this layout.


After the user's first GUI walkthrough, the lock picker, apply operation,
screen lock, and persistence across reopening were confirmed working on a
Fedora 44 GNOME Wayland desktop. The next UI version retains those operations
while replacing the vertically stacked utility layout with:

- **Two image-first cards side by side** when the window is wide enough.
- A native **libadwaita breakpoint** that stacks them on smaller windows,
  and stacks lock-screen action buttons on particularly narrow windows.
- Larger **uncropped, aspect-framed** wallpaper previews and clearer status
  badges (lock extension active / GDM viewing only).
- A simplified heading and a single safety note.

The GUI still cannot modify the login theme; editing GDM remains intentionally
blocked. The UI changes require refreshing the installed private GUI bundle.

The development GUI installer is intentionally **no-overwrite**. To test new
GUI revisions after `git pull --ff-only`, close the GUI, uninstall the prior
GUI bundle, then install the updated copy as your normal user:

```bash
python3 scripts/gui_install.py uninstall
python3 scripts/gui_install.py install
```

This updates only the GUI launcher and its private bundle. It leaves the CLI,
current wallpaper files, GNOME extension, GDM theme, and backups unchanged.
To remove *only* the GUI launcher and GUI bundle
(without touching the CLI, images, GDM files, or lock extension):

```bash
python3 scripts/gui_install.py uninstall
```

This is an experimental app, not a final Fedora RPM/Flatpak. The launcher
bundles a separate copy of the shared Python backend so existing installed
development CLIs remain untouched. The final packaging plan will combine
these into one updateable distribution. The [Fedora 44 GUI smoke test](https://github.com/tobiasGuta/Veilpaper/actions/runs/41236164174)
**PASSED**, creating the GTK4/libadwaita window under Xvfb in an isolated
container. A real GNOME Wayland visual and interaction test is still required.

### Visual polish checkpoint

**Verification:** [Fedora 44 About/icon smoke — PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41237413019). The GUI window, custom icon file, About window and primary-action switch were exercised on an isolated virtual display; **90/90 Python tests passed**. A full GNOME Wayland visual review remains pending.

The next development preview retains the **tested two-panel GNOME UI** and
improves the small details rather than redesigning the layout:

- Original Veilpaper **SVG application icon**, used by the desktop launcher and
  the About window; bundled with the GUI, not written into system directories.
- A recognizable **padlock** for Lock Screen and a separate users icon for the
  login screen.
- A single primary button at a time: **Choose image** is emphasized before
  selection; **Apply wallpaper** becomes emphasized when a new image is staged.
  Applying still requires the user's click.
- A balanced 1120 × 740 default window size (the adaptive breakpoints remain).
- Native **About Veilpaper** window with development version, project site and
  issue tracker, opened by the About icon in the header.

The installer uses manifest format **v2** for the icon asset and still accepts
v1 manifests for safe uninstall-and-upgrade. Existing wallpapers, the GDM
theme, GNOME extension and terminal CLI are not touched by a GUI update.

Close the old GUI, pull the branch, preview with
`python3 gui/veilpaper_gui.py`, and only if satisfied run
`python3 scripts/gui_install.py uninstall` followed by
`python3 scripts/gui_install.py install`.

## Isolated Fedora 44 stock-theme integration

The [Fedora 44 integration workflow](.github/workflows/fedora44-integration.yml)
starts an ephemeral `fedora:44` container with the source tree mounted **read-only**.
It installs GNOME Shell **inside the container**, then exercises:
- RPM verification and stock theme preflight;
- building a portable GDM candidate as an unprivileged container user;
- `install-check` against the pristine RPM theme;
- the five disposable transaction simulation scenarios;
- unchanged package-owned theme checksum after the test.

**CI validation:** [isolated Fedora 44 GDM integration — PASS](https://github.com/tobiasGuta/Veilpaper/actions/runs/41235462860). The pristine RPM theme had eight resources; a candidate with one additional wallpaper asset passed the read-only installation review. All five disposable recovery scenarios passed. The packaged theme hash was unchanged.

This provides stronger evidence than mock-only tests, but is **not** a graphical
GDM login test, a privileged live install, or a recovery qualification.

The workflow is manually dispatchable and automatically checks its own workflow
changes. To run the same isolated test using your existing Docker Engine, from
the repository root:

```bash
docker run --rm \
  --mount type=bind,src="$PWD",dst=/src,readonly \
  fedora:44 /bin/bash /src/scripts/fedora44_container_check.sh
```

This does not require Docker Desktop or a second Docker Engine. Package
installation occurs **inside the disposable container**.

## Install the single Veilpaper command (experimental, per-user)

Once the development branch's tests pass, you can install the **CLI launcher only**:

```bash
cd Veilpaper
python3 scripts/user_install.py install
~/.local/bin/veilpaper status
```

If `~/.local/bin` is already on your `PATH`, use `veilpaper status` instead.
The installer copies an **allowlist of source files** into
`~/.local/lib/veilpaper-dev` and creates `~/.local/bin/veilpaper`.
It refuses to overwrite an existing install or command and requires a regular
user, **not `sudo`**. It does **not** install the GNOME Shell extension, change
wallpaper images, touch GDM, change package-manager state, or restart sessions.

Check or remove **only** the CLI launcher and installed source:

```bash
python3 scripts/user_install.py status
python3 scripts/user_install.py uninstall
```

Uninstallation refuses files altered since installation and leaves existing
GDM customizations, backups, lock-screen images and the GNOME extension intact.
The command currently requires the repository to install or uninstall; packaging
as a proper distro package remains future work.

## Experimental unified commands

From the repository root (development branch):

```bash
git switch experimental/gnome50-lockscreen
python3 -m unittest discover -s tests -v
python3 veilpaper.py status
python3 veilpaper.py lock status
```

Per-user wallpaper management (PNG/JPEG are copied as-is; other GNOME-readable image formats are converted to real PNG using the system GdkPixbuf library and PyGObject, when available):

```bash
python3 veilpaper.py lock set /absolute/path/to/lock.png
python3 veilpaper.py lock restore
python3 veilpaper.py lock install
```

The `lock set` operation leaves any existing lock image intact if conversion fails. Conversion requires `python3-gobject` on Fedora; it is the standard GNOME Python binding, not a separate wallpaper manager. For troubleshooting, inspect the true image type with `file --mime-type IMAGE`.

The `lock install` subcommand copies the packaged GNOME extension into the user extension directory, but **does not enable it or restart GNOME**. If an existing extension differs, it refuses to overwrite it.

The new `login preflight` inspects compiled resources and CSS, reports any existing Veilpaper state, and **never modifies files**.

The new `login install-check` command is a **read-only admission review** for *first-time* Fedora installs. It verifies an RPM-matching live theme, a nonconflicting backup/state, and an exact two-CSS/one-image candidate resource diff. It rejects systems that are already customized (including the machine where Veilpaper first succeeded), instead of overwriting their existing working login theme. A structural PASS is **not** authorization to install. Run without `sudo`. This is the next validation gate, not the final installer.

The new `login transaction-check` command simulates installation, restoration, and interrupted operations in **fresh temporary test directories**. It reads, but never writes, the two supplied source resource files. It cannot install to a real GDM theme. All five simulated scenarios must return PASS before we consider a live installer design; this alone is **not sufficient** for general availability. Do not use `sudo` with it.

The new `login portable-build` command uses the installed RPM metadata to select a stock GDM theme or RPM-matching independent backup. It compiles and validates a **new candidate file only**, never changes `/usr/share` or `/var/backups`, and refuses to overwrite an existing output. **Do not use `sudo` with this command.** It currently accepts genuine PNG/JPEG files only. This does not implement portable installation or recovery; do not use the old `login apply` to install a portable candidate on another machine.

The additional `login baseline` command checks whether the active theme or its independent backup matches the digest and size recorded by the installed RPM database. It is **not** an installer or a complete authenticity check: locally altered RPM metadata or an untrusted package may still be misleading. A mismatch must not trigger automatic rewriting or an automatic baseline adoption. A structurally valid resource is **not** proof that the file is an unmodified package original. The eventual installer needs a verified stock baseline and independent recovery design for each target system.

Two-phase GDM login customization, **only on the previously verified host**:

```bash
python3 veilpaper.py login preflight  # read-only, recognizes existing customizations
python3 veilpaper.py login baseline   # read-only, compare active and backup to RPM DB
python3 veilpaper.py login portable-build /absolute/path/to/login.png \
  --output "$HOME/Downloads/veilpaper-new-candidate.gresource"
python3 veilpaper.py login transaction-check \
  /absolute/path/to/original.gresource \
  /absolute/path/to/veilpaper-new-candidate.gresource
python3 veilpaper.py login install-check /absolute/path/to/veilpaper-new-candidate.gresource
python3 veilpaper.py login status
python3 veilpaper.py login build /absolute/path/to/login.png --output /tmp/veilpaper-candidate.gresource
# Carefully review and back up first. Applying writes a system file:
sudo python3 veilpaper.py login apply /tmp/veilpaper-candidate.gresource
# On explicit rollback:
sudo python3 veilpaper.py login restore
```

The CLI deliberately does **not** automatically log users out, restart GDM, or install a system package. Be aware that the original login manager won't overwrite an existing managed GDM patch; restore explicitly before changing it. Existing users with a working wallpaper should **not** reapply the GDM resource merely to try the new CLI.

## Project layout

- `veilpaper.py`: unified development CLI (one user command)
- `scripts/user_install.py`: install/verify/remove an unprivileged `veilpaper` command with an allowlisted source bundle
- `gui/veilpaper_gui.py`: GTK4/libadwaita desktop UI with preview and lock actions
- `gui/backend.py`: portable non-GTK adapter to the existing lock/GDM backends
- `scripts/gui_install.py`: optional user-only Applications menu launcher, independently uninstallable
- `experiments/gdm/fedora_wallpaper_manager_v02.py`: validated, host-specific GDM backend
- `experiments/gdm/preflight.py`: read-only GNOME 50 theme structure/ownership-independent inspection
- `experiments/gdm/rpm_baseline.py`: read-only installed RPM digest/size comparison
- `experiments/gdm/portable_build.py`: RPM-qualified GDM candidate builder, no system writes
- `experiments/gdm/fixture_transaction.py`: private disposable GDM install/rollback transaction simulator
- `experiments/gdm/install_review.py`: strict read-only first-time candidate review
- `experiments/lockscreen/lockscreen/`: GNOME 50 extension JavaScript and metadata
- `tests/test_cli.py`: isolated CLI regression tests
- `experiments/lockscreen/tests/`: extension static tests

One user-facing CLI does **not** mean a single source file: GNOME requires a separate JavaScript extension and metadata to operate at the lock screen.

## Recovery and safety

- Preserve `/var/backups/fedora-gdm-wallpaper/original.gresource` and the original checksum.
- If a broken GNOME theme prevents GUI login, switch to a TTY and restore the known original.
- To disable the prototype extension after unlocking, run `gnome-extensions disable lockscreen@veilpaper.tobiasguta`.
- Do not remove or overwrite working files before making a backup.
- System package updates may undo the GDM theme and private GNOME interfaces can change.

**Licensing:** an open-source license has not yet been selected; do not treat this development branch as a published redistributable release.
