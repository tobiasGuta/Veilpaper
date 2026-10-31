/* Veilpaper lock-screen proof of concept.
 * GNOME 50 private UnlockDialog API. Fail closed if interface changes.
 * No key handlers, no authentication changes, no system writes.
 */
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {UnlockDialog} from 'resource:///org/gnome/shell/ui/unlockDialog.js';

function selectedWallpaper() {
    const dir = GLib.build_filenamev([GLib.get_user_data_dir(), 'veilpaper']);
    for (const name of ['lock-wallpaper.png', 'lock-wallpaper.jpg']) {
        const path = GLib.build_filenamev([dir, name]);
        if (GLib.file_test(path, GLib.FileTest.IS_REGULAR))
            return Gio.File.new_for_path(path).get_uri();
    }
    return null;
}

function cssEscape(value) {
    return value.replaceAll('\\', '\\\\').replaceAll('"', '\\"')
        .replaceAll('\n', '');
}

export default class VeilpaperLockExtension extends Extension {
    enable() {
        // Preserve GNOME's original background handler and authentication UI.
        if (this._createBackgroundPatch)
            return;
        const proto = UnlockDialog.prototype;
        if (typeof proto._createBackground !== 'function') {
            console.warn('[Veilpaper] Unsupported GNOME unlock-dialog implementation');
            return;
        }

        this._originalCreateBackground = proto._createBackground;
        const original = this._originalCreateBackground;
        this._createBackgroundPatch = function (monitorIndex) {
            original.call(this, monitorIndex);
            const uri = selectedWallpaper();
            const monitor = Main.layoutManager.monitors[monitorIndex];
            if (!uri || !monitor || !this._backgroundGroup)
                return;
            try {
                const overlay = new St.Widget({
                    reactive: false,
                    can_focus: false,
                    x: monitor.x,
                    y: monitor.y,
                    width: monitor.width,
                    height: monitor.height,
                    style: 'background-image: url("' + cssEscape(uri) + '"); ' +
                        'background-size: cover; ' +
                        'background-position: center; ' +
                        'background-repeat: no-repeat;',
                });
                // BackgroundGroup stays behind clock/password actors.
                // Do not register this actor as a GNOME background manager.
                this._backgroundGroup.add_child(overlay);
            } catch (error) {
                console.warn('[Veilpaper] Could not draw wallpaper: ' + error);
            }
        };
        proto._createBackground = this._createBackgroundPatch;

        try {
            Main.screenShield?._dialog?._updateBackgrounds?.();
        } catch (error) {
            console.warn('[Veilpaper] Background refresh failed: ' + error);
        }
    }

    disable() {
        // Required in unlock-dialog mode to preserve the background while locked.
        // No keyboard/input/authentication event handlers are installed.
        if (!this._createBackgroundPatch)
            return;
        const proto = UnlockDialog.prototype;
        if (proto._createBackground === this._createBackgroundPatch) {
            proto._createBackground = this._originalCreateBackground;
            try {
                Main.screenShield?._dialog?._updateBackgrounds?.();
            } catch (error) {
                console.warn('[Veilpaper] Could not refresh default background: ' + error);
            }
        } else {
            console.warn('[Veilpaper] Another extension replaced the hook; not overwriting it');
        }
        this._createBackgroundPatch = null;
        this._originalCreateBackground = null;
    }
}
