#!/usr/bin/env python3
"""Veilpaper's experimental native GNOME 50 UI (GTK4/libadwaita).

The lock wallpaper is editable using the existing non-root CLI backend.
GDM is read-only: no root helpers, installer, login changes or session restart.
"""
from __future__ import annotations

from pathlib import Path
import sys

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as error:
    raise SystemExit(
        f'Veilpaper GUI needs GTK4, libadwaita and PyGObject: {error}\n'
        'On Fedora: sudo dnf install python3-gobject gtk4 libadwaita'
    )

# Allow running from repository checkout and from the user-installed bundle.
from backend import lock_image, login_preview, state, set_lock, restore_lock

APP_ID = 'me.tobiasguta.Veilpaper'
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 32_000_000


def _label(text: str, css: str | None = None, *, wrap=False) -> Gtk.Label:
    result = Gtk.Label(label=text, xalign=0)
    result.set_wrap(wrap)
    if css:
        result.add_css_class(css)
    return result


def _image_paintable(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Choose a regular image file (not a symbolic link).')
    if not 10 <= path.stat().st_size <= MAX_SOURCE_BYTES:
        raise ValueError('The image must be smaller than 25 MiB.')
    info, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
    if info is None or width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError('Unsupported image or dimensions above 32 megapixels.')
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 1440, 900, True)
    return Gdk.Texture.new_for_pixbuf(pixbuf)


def _embedded_paintable(payload: bytes, mime: str):
    loader = GdkPixbuf.PixbufLoader.new_with_type(mime)
    loader.write(payload)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        return None
    return Gdk.Texture.new_for_pixbuf(pixbuf)


class VeilpaperWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title='Veilpaper')
        self.set_default_size(780, 790)
        self.set_size_request(420, 470)
        self._pending: Path | None = None

        overlay = Adw.ToastOverlay()
        self.set_content(overlay)
        self._overlay = overlay

        toolbar = Adw.ToolbarView()
        overlay.set_child(toolbar)
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        refresh = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh.set_tooltip_text('Refresh wallpaper status')
        refresh.connect('clicked', lambda _: self._refresh())
        header.pack_end(refresh)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(scroll)
        viewport = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        viewport.set_margin_top(28)
        viewport.set_margin_bottom(30)
        viewport.set_margin_start(26)
        viewport.set_margin_end(26)
        scroll.set_child(viewport)

        heading = _label('Your screens. Your wallpapers.', 'title-1', wrap=True)
        viewport.append(heading)
        subtitle = _label(
            'Choose a lock-screen image independently from your desktop and login backgrounds.',
            'dim-label', wrap=True)
        viewport.append(subtitle)

        # Lock screen — fully functional user-level actions.
        lock = self._card(viewport, 'Lock screen',
            'Choose, preview and apply an image. The desktop wallpaper stays unchanged.')
        self._lock_picture, self._lock_icon = self._preview(lock, 'Lock screen wallpaper preview')
        self._lock_status = _label('', 'dim-label', wrap=True)
        lock.append(self._lock_status)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.START)
        lock.append(actions)

        choose = Gtk.Button(label='Choose image…')
        choose.connect('clicked', self._choose_lock)
        actions.append(choose)

        self._apply = Gtk.Button(label='Apply to lock screen')
        self._apply.add_css_class('suggested-action')
        self._apply.set_sensitive(False)
        self._apply.connect('clicked', self._apply_lock)
        actions.append(self._apply)

        restore = Gtk.Button(label='Restore default')
        restore.connect('clicked', self._restore_lock)
        actions.append(restore)

        # Login screen — intentionally read-only until the system installer
        # is qualified in a real isolated Fedora VM.
        login = self._card(viewport, 'Login screen',
            'GDM uses a system resource. Viewing it is safe; applying changes is not ready.')
        self._login_picture, self._login_icon = self._preview(login, 'Login wallpaper preview')
        self._login_status = _label('', wrap=True)
        login.append(self._login_status)
        self._login_detail = _label('', 'dim-label', wrap=True)
        login.append(self._login_detail)
        disabled_button = Gtk.Button(label='Login wallpaper editing — coming later')
        disabled_button.set_sensitive(False)
        disabled_button.set_halign(Gtk.Align.START)
        disabled_button.set_tooltip_text(
            'Requires a portable GDM installer with verified rollback and safe privileges')
        login.append(disabled_button)

        footnote = _label(
            'Experimental GNOME 50 application • No GDM changes, admin password or reboot.',
            'dim-label', wrap=True)
        viewport.append(footnote)
        self._refresh()

    def _card(self, parent, title, description):
        frame = Gtk.Frame()
        frame.add_css_class('card')
        parent.append(frame)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        frame.set_child(box)
        box.append(_label(title, 'title-3'))
        box.append(_label(description, 'dim-label', wrap=True))
        return box

    def _preview(self, parent, accessibility):
        container = Gtk.Frame()
        parent.append(container)
        stack = Gtk.Stack()
        container.set_child(stack)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_size_request(-1, 185)
        picture.set_tooltip_text(accessibility)
        stack.add_named(picture, 'image')
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        placeholder.set_size_request(-1, 185)
        placeholder.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name('preferences-desktop-wallpaper-symbolic')
        icon.set_pixel_size(56)
        placeholder.append(icon)
        message = Gtk.Label(label='No image preview available')
        message.add_css_class('dim-label')
        placeholder.append(message)
        stack.add_named(placeholder, 'placeholder')
        stack.set_visible_child_name('placeholder')
        # Use the stack as the handle for selecting the placeholder/image.
        return picture, stack

    def _toast(self, message):
        self._overlay.add_toast(Adw.Toast.new(str(message)))

    def _show_lock_preview(self, path):
        if path is None:
            self._lock_icon.set_visible_child_name('placeholder')
            return
        try:
            self._lock_picture.set_paintable(_image_paintable(path))
            self._lock_icon.set_visible_child_name('image')
        except (ValueError, OSError, GLib.Error) as error:
            self._lock_icon.set_visible_child_name('placeholder')
            self._toast(f'Cannot preview wallpaper: {error}')

    def _refresh(self):
        current = state()
        if self._pending is None:
            self._show_lock_preview(current.lock_image)
            self._apply.set_sensitive(False)
            name = current.lock_image.name if current.lock_image else 'System default'
            self._lock_status.set_text(f'{name}  •  {current.extension_state}')
        else:
            self._lock_status.set_text(f'Ready to apply: {self._pending.name}')
        self._login_status.set_text(current.login_label)
        self._login_detail.set_text(current.login_detail)
        data = login_preview()
        if data:
            try:
                paintable = _embedded_paintable(*data)
                if paintable:
                    self._login_picture.set_paintable(paintable)
                    self._login_icon.set_visible_child_name('image')
                else:
                    self._login_icon.set_visible_child_name('placeholder')
            except (GLib.Error, ValueError) as error:
                self._login_icon.set_visible_child_name('placeholder')
                self._toast(f'Login preview could not be loaded: {error}')
        else:
            self._login_icon.set_visible_child_name('placeholder')

    def _choose_lock(self, _button):
        dialog = Gtk.FileDialog(title='Choose a lock-screen wallpaper')
        file_filter = Gtk.FileFilter()
        file_filter.set_name('Images')
        file_filter.add_mime_type('image/*')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)

        def finished(chooser, result):
            try:
                selected = chooser.open_finish(result)
            except GLib.Error:
                return  # Dismissed/cancelled file selection, no changes.
            if selected is None or not selected.get_path():
                self._toast('Please choose a local image file.')
                return
            path = Path(selected.get_path())
            try:
                paintable = _image_paintable(path)
            except (OSError, ValueError, GLib.Error) as error:
                self._toast(f'Unsupported image: {error}')
                return
            self._pending = path
            self._lock_picture.set_paintable(paintable)
            self._lock_icon.set_visible_child_name('image')
            self._apply.set_sensitive(True)
            self._lock_status.set_text(f'Ready to apply: {path.name}')
        dialog.open(self, None, finished)

    def _apply_lock(self, _button):
        if self._pending is None:
            return
        self._apply.set_sensitive(False)
        try:
            result = set_lock(self._pending)
            if result is None:
                raise RuntimeError('No installed lock wallpaper was detected.')
        except (RuntimeError, OSError, ValueError, GLib.Error) as error:
            self._apply.set_sensitive(True)
            self._toast(f'Could not apply lock wallpaper: {error}')
            return
        self._pending = None
        self._refresh()
        self._toast('Lock wallpaper applied. Lock your screen to see it.')

    def _restore_lock(self, _button):
        try:
            restore_lock()
        except (RuntimeError, OSError, ValueError) as error:
            self._toast(f'Could not restore default wallpaper: {error}')
            return
        self._pending = None
        self._refresh()
        self._toast('Default lock wallpaper restored.')


class VeilpaperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._window = None

    def do_activate(self):
        if self._window is None:
            self._window = VeilpaperWindow(self)
        self._window.present()


def main(argv=None):
    if hasattr(GLib, 'get_user_name') and __import__('os').geteuid() == 0:
        print('ERROR: Run the Veilpaper GUI as your regular user, never with sudo.',
              file=sys.stderr)
        return 1
    return VeilpaperApp().run(argv if argv is not None else sys.argv)


if __name__ == '__main__':
    raise SystemExit(main())
