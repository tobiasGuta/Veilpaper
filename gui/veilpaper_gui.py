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
    """Adaptive GNOME dashboard with image-first panels and safe actions."""

    def __init__(self, application):
        super().__init__(application=application, title='Veilpaper')
        self.set_default_size(1160, 760)
        self.set_size_request(430, 520)
        self._pending: Path | None = None
        self._install_styles()

        overlay = Adw.ToastOverlay()
        self.set_content(overlay)
        self._overlay = overlay

        toolbar = Adw.ToolbarView()
        overlay.set_child(toolbar)
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        refresh = Gtk.Button(icon_name='view-refresh-symbolic')
        refresh.set_tooltip_text('Refresh screen status')
        refresh.connect('clicked', lambda _: self._refresh())
        header.pack_end(refresh)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(scroll)

        self._content_clamp = Adw.Clamp()
        self._content_clamp.set_maximum_size(1210)
        self._content_clamp.set_tightening_threshold(950)
        scroll.set_child(self._content_clamp)

        viewport = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        viewport.set_margin_top(28)
        viewport.set_margin_bottom(26)
        viewport.set_margin_start(24)
        viewport.set_margin_end(24)
        self._content_clamp.set_child(viewport)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hero.add_css_class('veilpaper-hero')
        viewport.append(hero)
        eyebrow = _label('PERSONALIZE YOUR GNOME SCREENS', 'caption')
        eyebrow.add_css_class('dim-label')
        hero.append(eyebrow)
        hero.append(_label('Make every screen yours.', 'title-1', wrap=True))
        hero.append(_label(
            'Independent wallpapers for your lock screen and the screen you sign in to.',
            'dim-label', wrap=True))

        self._cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        viewport.append(self._cards)

        # libadwaita breakpoint: two columns on a wide display, one column on
        # narrow windows. No custom window size handlers or display polling.
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 920sp'))
        narrow.add_setter(self._cards, 'orientation', Gtk.Orientation.VERTICAL)
        self.add_breakpoint(narrow)

        lock, lock_content = self._card(
            self._cards, 'Lock screen', 'screen-locked-symbolic',
            'Your personal screen whenever you lock your device.', 'Ready')
        self._lock_badge = lock_content
        self._lock_picture, self._lock_icon = self._preview(
            lock, 'Complete preview of the lock-screen wallpaper')
        self._lock_status = _label('', 'dim-label', wrap=True)
        lock.append(self._lock_status)

        # A primary action to choose a picture, then an explicit, disabled
        # until staged Apply button. Restore remains a secondary action.
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._lock_actions = actions
        actions.add_css_class('veilpaper-actions')
        lock.append(actions)

        choose = Gtk.Button(label='Choose image…')
        choose.set_tooltip_text('Select a local image without applying it yet')
        choose.connect('clicked', self._choose_lock)
        actions.append(choose)

        self._apply = Gtk.Button(label='Apply wallpaper')
        self._apply.add_css_class('suggested-action')
        self._apply.set_sensitive(False)
        self._apply.connect('clicked', self._apply_lock)
        actions.append(self._apply)

        restore = Gtk.Button(label='Restore default')
        restore.connect('clicked', self._restore_lock)
        actions.append(restore)

        login, _login_badge = self._card(
            self._cards, 'Login screen', 'system-lock-screen-symbolic',
            'The background displayed before you sign in.', 'VIEW ONLY',
            muted=True)
        self._login_picture, self._login_icon = self._preview(
            login, 'Complete preview of the GDM login wallpaper')
        self._login_status = _label('', 'heading', wrap=True)
        login.append(self._login_status)
        self._login_detail = _label('', 'dim-label', wrap=True)
        login.append(self._login_detail)

        disabled_button = Gtk.Button(label='Editing available in a future version')
        disabled_button.set_sensitive(False)
        disabled_button.set_tooltip_text(
            'GDM editing requires a separately qualified, safely authorized installer')
        disabled_button.set_halign(Gtk.Align.START)
        login.append(disabled_button)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class('veilpaper-footer')
        viewport.append(footer)
        footer.append(Gtk.Image.new_from_icon_name('security-high-symbolic'))
        footer.append(_label(
            'Your desktop wallpaper stays unchanged. Login screen editing is read-only.',
            'dim-label', wrap=True))

        # Additional responsive rule for the lock action row when the window
        # is particularly narrow, avoiding hidden controls or horizontal scroll.
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 580sp'))
        compact.add_setter(self._lock_actions, 'orientation', Gtk.Orientation.VERTICAL)
        self.add_breakpoint(compact)

        self._refresh()

    def _install_styles(self):
        # Theme-aware styling: use GNOME's colors instead of fixed light/dark
        # backgrounds. Widgets remain usable with default system appearance.
        css = b"""
            .veilpaper-hero { padding: 16px 4px 8px 4px; }
            .veilpaper-hero .caption { font-weight: 700; letter-spacing: 1px; font-size: 0.8em; }
            .veilpaper-panel { border-radius: 14px; }
            .veilpaper-preview {
                background: alpha(@window_fg_color, 0.035);
                border: 1px solid alpha(@window_fg_color, 0.08);
                border-radius: 10px;
            }
            .veilpaper-status {
                padding: 4px 10px;
                border-radius: 99px;
                background: alpha(@accent_bg_color, 0.14);
                font-weight: 600;
                font-size: 0.82em;
            }
            .veilpaper-muted-status {
                background: alpha(@window_fg_color, 0.07);
            }
            .veilpaper-footer { padding: 2px 6px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_provider = provider

    def _card(self, parent, title, icon_name, description, status, *, muted=False):
        frame = Gtk.Frame()
        frame.add_css_class('card')
        frame.add_css_class('veilpaper-panel')
        frame.set_hexpand(True)
        parent.append(frame)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        frame.set_child(content)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.append(header)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(22)
        header.append(icon)
        name = _label(title, 'title-3')
        name.set_hexpand(True)
        header.append(name)

        pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        pill.add_css_class('veilpaper-status')
        if muted:
            pill.add_css_class('veilpaper-muted-status')
        badge_label = Gtk.Label(label=status)
        pill.append(badge_label)
        header.append(pill)

        content.append(_label(description, 'dim-label', wrap=True))
        return content, badge_label

    def _preview(self, parent, accessibility):
        border = Gtk.Frame()
        border.add_css_class('veilpaper-preview')
        parent.append(border)
        aspect = Gtk.AspectFrame(ratio=16 / 10, obey_child=False,
                                 xalign=0.5, yalign=0.5)
        aspect.set_hexpand(True)
        border.set_child(aspect)

        stack = Gtk.Stack()
        stack.set_size_request(-1, 255)
        aspect.set_child(stack)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_can_shrink(True)
        picture.set_alternative_text(accessibility)
        picture.set_tooltip_text(accessibility)
        stack.add_named(picture, 'image')

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name('preferences-desktop-wallpaper-symbolic')
        icon.set_pixel_size(52)
        placeholder.append(icon)
        message = Gtk.Label(label='No image preview available')
        message.add_css_class('dim-label')
        placeholder.append(message)
        stack.add_named(placeholder, 'placeholder')
        stack.set_visible_child_name('placeholder')
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
        active = current.extension_state == 'Extension active'
        self._lock_badge.set_text('ACTIVE' if active else 'CHECK EXTENSION')
        if self._pending is None:
            self._show_lock_preview(current.lock_image)
            self._apply.set_sensitive(False)
            name = current.lock_image.name if current.lock_image else 'System default'
            self._lock_status.set_text(f'Current wallpaper: {name}')
        else:
            self._lock_status.set_text(f'Not applied yet: {self._pending.name}')
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
                return
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
            self._lock_status.set_text(f'Not applied yet: {path.name}')
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
