#!/usr/bin/env bash
# Isolated Fedora 44 GNOME GUI startup smoke test; no host display access.
set -euo pipefail

if [[ ! -f /.dockerenv && ! -f /run/.containerenv ]]; then
  echo "ERROR: GUI smoke test is container-only." >&2
  exit 1
fi
if [[ ! -r /src/gui/veilpaper_gui.py || -w /src/gui/veilpaper_gui.py ]]; then
  echo "ERROR: Veilpaper checkout must be mounted read-only at /src." >&2
  exit 1
fi
if ! grep -qE '^Fedora release 44' /etc/fedora-release; then
  echo "ERROR: Fedora 44 required." >&2
  exit 1
fi
dnf install -y --setopt=install_weak_deps=False \
  python3 python3-gobject gtk4 libadwaita cairo-gobject xorg-x11-server-Xvfb xorg-x11-xauth
command -v xvfb-run

# Test actual GTK/libadwaita widget creation on an isolated virtual display.
GDK_BACKEND=x11 xvfb-run -a python3 - <<'PY'
import sys
sys.path.insert(0, '/src/gui')
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk
assert hasattr(Gtk, 'FileDialog'), 'GTK4 FileDialog is required'
from veilpaper_gui import VeilpaperApp, VeilpaperWindow
app = VeilpaperApp()
assert app.register(None), 'GTK app registration failed'
window = VeilpaperWindow(app)
assert window.get_title() == 'Veilpaper'
assert not window._apply.get_sensitive(), 'Apply must be disabled without selection'
assert 'login' in window._login_detail.get_text().lower() or window._login_detail.get_text()
window.close()
print('PASS: Fedora 44 GTK4/libadwaita UI created and validated via virtual display.')
print('NOTE: no actual GNOME Wayland desktop, GDM, or wallpaper modification was tested.')
PY
