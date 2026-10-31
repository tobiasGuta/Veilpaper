# Veilpaper

**Your screens. Your wallpapers.**

Veilpaper is an experimental GNOME wallpaper manager that controls **GDM login** and **lock-screen** backgrounds independently of the desktop wallpaper.

> **Development branch only. No supported installer or release yet.** This code modifies GNOME internals. Do not assume Fedora/GNOME-wide compatibility from one machine's success.

## Verified milestone — October 31, 2026

| Component | Current evidence |
| --- | --- |
| GDM login wallpaper | **Visual PASS** after reboot: Fedora 44, GNOME Shell 50.6, GDM 50.3 |
| Lock wallpaper extension | **Visual PASS** after `Super+L` on the same laptop; enabled and ACTIVE |
| Unified entry point | **CLI status PASS** on Fedora 44; lock image conversion completed; **6/6 CLI unit tests PASS** |
| Lock image handling | **Visual PASS** after real WebP-to-PNG conversion; resulting file identified as `image/png` |
| GDM portability preflight | Read-only structural inspection implemented; not a generic apply or restore mechanism |
| Install/restore across machines | **Not ready** |

The login tool requires a specific verified original GDM checksum. It will refuse unknown host originals, and that is intentional. **Do not apply the login theme tool on another system.**

The lock extension uses GNOME Shell private APIs. Full regression tests—including normal password unlock, extension disable, upgrade effects, and SELinux behavior—remain outstanding.

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

The new `login preflight` inspects compiled resources and CSS, reports any existing Veilpaper state, and **never modifies files**. A structurally valid resource is **not** proof that the file is an unmodified package original. The eventual installer needs a verified stock baseline and independent recovery design for each target system.

Two-phase GDM login customization, **only on the previously verified host**:

```bash
python3 veilpaper.py login preflight  # read-only, recognizes existing customizations
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
- `experiments/gdm/fedora_wallpaper_manager_v02.py`: validated, host-specific GDM backend
- `experiments/gdm/preflight.py`: read-only GNOME 50 theme structure/ownership-independent inspection
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
