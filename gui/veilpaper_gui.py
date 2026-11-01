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
from backend import (lock_image, login_preview, state, set_lock, restore_lock,
                     prepare_login_candidate, discard_login_candidate)

APP_ID = 'me.tobiasguta.Veilpaper'
APP_VERSION = '0.1.0-dev'
ICON_FILE = Path(__file__).resolve().parent / 'assets' / f'{APP_ID}.svg'
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
        self.set_default_size(1120, 740)
        self.set_size_request(430, 520)
        self._pending: Path | None = None
        self._pending_login: Path | None = None
        self._login_candidate = None
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
        about_button = Gtk.Button(icon_name='help-about-symbolic')
        about_button.set_tooltip_text('About Veilpaper')
        about_button.connect('clicked', self._show_about)
        header.pack_end(about_button)

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
            self._cards, 'Lock screen', 'system-lock-screen-symbolic',
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
        self._choose = choose
        choose.add_css_class('suggested-action')
        choose.set_tooltip_text('Select a local image without applying it yet')
        choose.connect('clicked', self._choose_lock)
        actions.append(choose)

        self._apply = Gtk.Button(label='Apply wallpaper')
        self._apply.set_sensitive(False)
        self._apply.connect('clicked', self._apply_lock)
        actions.append(self._apply)

        restore = Gtk.Button(label='Restore default')
        restore.add_css_class('flat')
        restore.connect('clicked', self._restore_lock)
        actions.append(restore)

        login, _login_badge = self._card(
            self._cards, 'Login screen', 'system-users-symbolic',
            'The background displayed before you sign in.', 'BUILD ONLY',
            muted=True)
        self._login_picture, self._login_icon = self._preview(
            login, 'Complete preview of the GDM login wallpaper')
        self._login_status = _label('', 'heading', wrap=True)
        login.append(self._login_status)
        self._login_detail = _label('', 'dim-label', wrap=True)
        login.append(self._login_detail)

        self._login_progress = _label(
            'Choose an image to preview and prepare a verified GDM candidate. '
            'Installing it is not available yet.',
            'dim-label', wrap=True)
        login.append(self._login_progress)

        # Technical details are selectable on demand, never stretched across
        # the two-card dashboard. No candidate data is sent anywhere.
        self._login_details = Gtk.MenuButton(label='View details')
        self._login_details.set_tooltip_text('Show candidate location and SHA-256')
        self._login_details.set_sensitive(False)
        self._login_details.set_halign(Gtk.Align.START)
        detail_popover = Gtk.Popover()
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail_box.set_margin_top(14)
        detail_box.set_margin_bottom(14)
        detail_box.set_margin_start(14)
        detail_box.set_margin_end(14)
        detail_box.set_size_request(340, -1)
        detail_box.append(_label('Verified candidate details', 'heading'))
        detail_box.append(_label('Saved locally — never installed', 'dim-label'))
        detail_box.append(_label('RESOURCE PATH', 'dim-label'))
        self._candidate_path_label = _label('', wrap=True)
        self._candidate_path_label.set_selectable(True)
        self._candidate_path_label.set_wrap_mode(Pango.WrapMode.CHAR)
        self._candidate_path_label.set_max_width_chars(45)
        detail_box.append(self._candidate_path_label)
        detail_box.append(_label('SHA-256', 'dim-label'))
        self._candidate_digest_label = _label('', wrap=True)
        self._candidate_digest_label.set_selectable(True)
        self._candidate_digest_label.set_wrap_mode(Pango.WrapMode.CHAR)
        self._candidate_digest_label.set_max_width_chars(45)
        detail_box.append(self._candidate_digest_label)
        self._copy_candidate_hash = Gtk.Button(label='Copy SHA-256')
        self._copy_candidate_hash.connect('clicked', self._copy_digest)
        detail_box.append(self._copy_candidate_hash)
        detail_popover.set_child(detail_box)
        self._login_details.set_popover(detail_popover)
        login.append(self._login_details)

        login_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._login_actions = login_actions
        login.append(login_actions)

        self._login_choose = Gtk.Button(label='Choose image…')
        self._login_choose.connect('clicked', self._choose_login)
        login_actions.append(self._login_choose)

        self._login_prepare = Gtk.Button(label='Build candidate')
        self._login_prepare.set_sensitive(False)
        self._login_prepare.set_tooltip_text(
            'Build and verify locally; never install or change the GDM theme')
        self._login_prepare.connect('clicked', self._prepare_login)
        login_actions.append(self._login_prepare)

        self._login_reset = Gtk.Button(label='Show current')
        self._login_reset.add_css_class('flat')
        self._login_reset.connect('clicked', self._show_current_login)
        login_actions.append(self._login_reset)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class('veilpaper-footer')
        viewport.append(footer)
        footer.append(Gtk.Image.new_from_icon_name('security-high-symbolic'))
        footer.append(_label(
            'Your desktop stays unchanged. Login candidates are build-only and never installed.',
            'dim-label', wrap=True))

        # Additional responsive rule for the lock action row when the window
        # is particularly narrow, avoiding hidden controls or horizontal scroll.
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 580sp'))
        compact.add_setter(self._lock_actions, 'orientation', Gtk.Orientation.VERTICAL)
        compact.add_setter(self._login_actions, 'orientation', Gtk.Orientation.VERTICAL)
        self.add_breakpoint(compact)

        self._refresh()

    def _show_about(self, _button):
        about = Adw.AboutWindow(
            transient_for=self,
            modal=True,
            application_name='Veilpaper',
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name='Veilpaper contributors',
            website='https://github.com/tobiasGuta/Veilpaper',
            issue_url='https://github.com/tobiasGuta/Veilpaper/issues',
        )
        about.present()
        self._about_window = about

    def _update_action_styles(self):
        # A single prominent action: choose first, apply only after selection.
        if self._pending is None:
            self._choose.add_css_class('suggested-action')
            self._apply.remove_css_class('suggested-action')
        else:
            self._choose.remove_css_class('suggested-action')
            self._apply.add_css_class('suggested-action')

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
        if self._pending_login is None:
            self._login_status.set_text(current.login_label)
        elif self._login_candidate is None:
            self._login_status.set_text('Preview only — not installed')
        else:
            self._login_status.set_text('Verified candidate ready — not installed')
        self._login_detail.set_text(current.login_detail)
        self._update_action_styles()
        if self._pending_login is not None:
            return  # Keep staged login preview and its explicit build-only status.
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

    def _choose_login(self, _button):
        dialog = Gtk.FileDialog(title='Choose a login wallpaper to prepare')
        image_filter = Gtk.FileFilter()
        image_filter.set_name('Images')
        image_filter.add_mime_type('image/*')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(image_filter)

        def finished(chooser, result):
            try:
                selected = chooser.open_finish(result)
            except GLib.Error:
                return
            if selected is None or not selected.get_path():
                self._toast('Choose a local image.')
                return
            path = Path(selected.get_path())
            try:
                paintable = _image_paintable(path)
            except (OSError, ValueError, GLib.Error) as error:
                self._toast(f'Unsupported login image: {error}')
                return
            # Remove only a previously verified private staging job. If it
            # has been altered or replaced, keep the current UI state intact
            # so the user can inspect it instead of silently deleting it.
            if self._login_candidate is not None:
                try:
                    discard_login_candidate(self._login_candidate)
                except (RuntimeError, OSError, ValueError) as error:
                    self._toast(f'Previous candidate was preserved: {error}')
                    return
            self._pending_login = path
            self._login_candidate = None
            self._login_reset.set_label('Show current')
            self._login_details.set_sensitive(False)
            self._candidate_path_label.set_text('')
            self._candidate_digest_label.set_text('')
            self._login_picture.set_paintable(paintable)
            self._login_icon.set_visible_child_name('image')
            self._login_prepare.set_sensitive(True)
            self._login_status.set_text('Preview only — not installed')
            self._login_progress.set_text(
                f'{path.name} selected. Prepare a candidate before installation can '
                'be considered in a future release.')
        dialog.open(self, None, finished)

    def _prepare_login(self, _button):
        if self._pending_login is None:
            return
        self._login_prepare.set_sensitive(False)
        self._login_progress.set_text('Building and checking candidate locally…')
        try:
            result = prepare_login_candidate(self._pending_login)
        except (RuntimeError, OSError, ValueError, GLib.Error) as error:
            self._login_prepare.set_sensitive(True)
            self._login_progress.set_text('Candidate preparation failed; installed login remains unchanged.')
            self._toast(f'GDM candidate could not be prepared: {error}')
            return
        self._login_candidate = result
        self._login_reset.set_label('Discard candidate')
        self._candidate_path_label.set_text(str(result.path))
        self._candidate_digest_label.set_text(result.digest)
        self._login_details.set_sensitive(True)
        self._login_progress.set_text(
            'Candidate verified — not installed. Your current login wallpaper '
            'and original recovery backup remain unchanged.')
        self._login_status.set_text('Verified candidate ready — not installed')
        self._toast('Login candidate verified. No system theme was changed.')

    def _copy_digest(self, _button):
        if self._login_candidate is None:
            return
        Gdk.Display.get_default().get_clipboard().set(self._login_candidate.digest)
        self._toast('Candidate SHA-256 copied.')

    def _show_current_login(self, _button):
        if self._login_candidate is not None:
            try:
                discard_login_candidate(self._login_candidate)
            except (RuntimeError, OSError, ValueError) as error:
                self._toast(f'Candidate was preserved; could not discard safely: {error}')
                return
        self._pending_login = None
        self._login_candidate = None
        self._login_reset.set_label('Show current')
        self._login_details.set_sensitive(False)
        self._candidate_path_label.set_text('')
        self._candidate_digest_label.set_text('')
        self._login_prepare.set_sensitive(False)
        self._login_progress.set_text(
            'Choose an image to preview and prepare a verified GDM candidate. '
            'Installing it is not available yet.')
        self._refresh()

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
            self._update_action_styles()
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
        if ICON_FILE.is_file():
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            theme.add_search_path(str(ICON_FILE.parent))
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
