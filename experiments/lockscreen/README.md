# Veilpaper — lock-screen prototype (GNOME 50)

**Status: experimental.** Only the existing GDM login wallpaper was verified on the
original Fedora 44 / GNOME Shell 50.6 machine. The separate lock wallpaper extension
has **not yet been runtime-tested on GNOME**. Do not tag a stable release until successful lock/unlock and disable/restore tests.

The extension wraps GNOME Shell's private `UnlockDialog._createBackground` method,
asks GNOME to draw the stock wallpaper first, and then overlays one non-interactive
image inside the dialog's background group. The image stays *behind* clock/password
actors. It never intercepts input or modifies authentication.

## Test (user session only; no sudo)

1. Clone the experimental branch and enter the prototype directory:

   ```bash
   git clone --branch experimental/gnome50-lockscreen \
     https://github.com/tobiasGuta/Veilpaper.git
   cd Veilpaper/experiments/lockscreen
   python3 -m unittest discover -s tests -v
   ```

   The tests verify source structure only; they do **not** prove a successful
   lock/unlock cycle.
2. Copy a PNG to the designated private per-user data path:

   ```bash
   mkdir -p "$HOME/.local/share/veilpaper"
   cp "$HOME/Pictures/wallpaper/lock.png" "$HOME/.local/share/veilpaper/lock-wallpaper.png"
   chmod 644 "$HOME/.local/share/veilpaper/lock-wallpaper.png"
   ```

   For JPEG instead, use `lock-wallpaper.jpg` and **remove** any previous
   `lock-wallpaper.png` to avoid ambiguity. The extension checks PNG first.
3. Install the extension source into your per-user GNOME extension folder:

   ```bash
   UUID='lockscreen@veilpaper.tobiasguta'
   DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"
   mkdir -p "$DEST"
   cp lockscreen/extension.js lockscreen/metadata.json "$DEST/"
   ```

4. **Log out and log back in** if `gnome-extensions` doesn't detect it yet.
   This is normal on GNOME Wayland and does not restart GDM.
5. Enable and inspect:

   ```bash
   gnome-extensions enable 'lockscreen@veilpaper.tobiasguta'
   gnome-extensions info 'lockscreen@veilpaper.tobiasguta'
   ```

6. Press **Super+L**. Confirm that the image appears, and test password
   entry/unlock. The existing GDM login wallpaper is untouched.

## Rollback

```bash
gnome-extensions disable 'lockscreen@veilpaper.tobiasguta'
# If necessary, after logging in again:
rm -rf "$HOME/.local/share/gnome-shell/extensions/lockscreen@veilpaper.tobiasguta"
```

To restore the stock lock-screen background while leaving the extension installed,
remove the Veilpaper user image and lock again (or disable/re-enable the extension):

```bash
rm -f "$HOME/.local/share/veilpaper/lock-wallpaper.png" \
      "$HOME/.local/share/veilpaper/lock-wallpaper.jpg"
```

**Safety:** Keep a live TTY escape path (`Ctrl+Alt+F3`) and don't experiment on
an unattended machine. Avoid enabling two extensions that customize the GNOME
lockscreen background at once. This is a GNOME 50 private API and GNOME upgrades
may require code changes. The extension does not update the system resource.

## Later integration

Merge the already proven GDM Python manager (v0.2) and the lock-screen installer
into a single `veilpaper` CLI, with separate `login` and `lock` subcommands.
Generalize the original Fedora GDM checksum and add package-update handling
before a public release. Do not publish hard-coded, device-specific SHA-256 values
as generic compatibility claims.

## Design references

- https://gjs.guide/extensions/topics/session-modes.html
- https://gjs.guide/extensions/overview/anatomy.html
- https://github.com/GNOME/gnome-shell/blob/main/js/ui/unlockDialog.js