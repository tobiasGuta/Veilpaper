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
  python3 python3-gobject gtk4 libadwaita cairo-gobject gobject-introspection libglvnd-gles xorg-x11-server-Xvfb xorg-x11-xauth
command -v xvfb-run
rpm -q --whatprovides /usr/lib64/girepository-1.0/cairo-1.0.typelib
rpm -q --whatprovides /usr/lib64/libGLESv2.so.2

# Test actual GTK/libadwaita widget creation on an isolated virtual display.
GDK_BACKEND=x11 xvfb-run -a python3 - <<'PY'
import sys
sys.path.insert(0, '/src/gui')
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk
assert hasattr(Gtk, 'FileDialog'), 'GTK4 FileDialog is required'
from veilpaper_gui import VeilpaperApp, VeilpaperWindow, ICON_FILE, APP_VERSION
from pathlib import Path
assert ICON_FILE.is_file(), 'Branded application icon must be packaged'
app = VeilpaperApp()
assert app.register(None), 'GTK app registration failed'
window = VeilpaperWindow(app)
assert window.get_title() == 'Veilpaper'
assert window.get_default_size() == (1120, 740), 'Default GNOME window sizing changed'
assert window._choose.has_css_class('suggested-action'), 'Choose image should be primary by default'
assert not window._apply.has_css_class('suggested-action'), 'Apply should not be primary without a new selection'
window._pending = Path('/tmp/veilpaper-gui-staged-fixture.png')
window._update_action_styles()
assert window._apply.has_css_class('suggested-action'), 'Apply should become primary once an image is staged'
assert not window._choose.has_css_class('suggested-action'), 'Only one primary action at a time'
window._pending = None
window._update_action_styles()
window._show_about(None)
assert window._about_window.get_application_name() == 'Veilpaper', 'About window title'
assert window._about_window.get_version() == APP_VERSION, 'About window version'
window._about_window.close()
assert not window._apply.get_sensitive(), 'Apply must be disabled without selection'
assert window._content_clamp.get_maximum_size() == 1210, 'Dashboard must have a readable maximum width'
assert window._content_clamp.get_child() is not None, 'Content must be attached to clamp'
assert window._cards.get_orientation() == Gtk.Orientation.HORIZONTAL, 'Wide layout must be two-column'
assert window._lock_badge.get_text(), 'Lock extension badge must display a status'
assert not window._apply.get_sensitive(), 'Applying without a chosen image must stay disabled'
for preview in (window._lock_picture, window._login_picture):
    assert preview.get_content_fit() == Gtk.ContentFit.CONTAIN, 'Wallpaper must not be cropped'
    assert preview.get_can_shrink(), 'Image must fit smaller displays'
    assert preview.get_alternative_text(), 'Preview needs accessible text'
assert not window._login_details.get_sensitive(), 'Details must be hidden until verified'
assert not window._candidate_path_label.get_text(), 'No stale path before building'
assert not window._login_prepare.get_sensitive(), 'Login candidate build requires explicit image selection'
assert 'candidate' in window._login_progress.get_text().lower(), 'Build-only guidance required'
assert window._login_choose.get_label() == 'Choose image…', 'Login image picker missing'
window._pending_login = Path('/tmp/veilpaper-staged-login-image.png')
window._login_prepare.set_sensitive(True)
from types import SimpleNamespace
from unittest.mock import patch
with patch('veilpaper_gui.prepare_login_candidate', return_value=SimpleNamespace(
        path=Path('/tmp/test-candidate.gresource'),
        digest='a' * 64,
        baseline_digest='b' * 64,
        resource='/org/gnome/shell/theme/fedora-login-wallpaper.png')):
    window._prepare_login(None)
assert window._login_details.get_sensitive(), 'Verification should enable details'
assert window._candidate_path_label.get_text() == '/tmp/test-candidate.gresource'
assert window._candidate_digest_label.get_text() == 'a' * 64
assert 'not installed' in window._login_progress.get_text().lower()
window._show_current_login(None)
assert window._pending_login is None, 'Show current must discard the pending selection'
assert not window._login_prepare.get_sensitive(), 'Reset must disable preparation'
assert window._login_candidate is None, 'Reset must clear selected candidate'
assert not window._login_details.get_sensitive(), 'Reset must disable candidate details'
assert not window._candidate_digest_label.get_text(), 'Reset must clear stale candidate hash'

assert window._login_detail.get_text(), 'Login status must be visible'
window.close()
print('PASS: Fedora 44 GTK4/libadwaita UI created and validated via virtual display.')
print('NOTE: no actual GNOME Wayland desktop, GDM, or wallpaper modification was tested.')
PY
