# Veilpaper

**Your screens. Your wallpapers.**

Experimental GNOME wallpaper customization for an independent **GDM login wallpaper** and **lock-screen wallpaper**, without changing the desktop background.

## Project status — October 31, 2026

- **Login screen:** visually verified after reboot on Fedora 44, GNOME Shell 50.6, GDM 50.3.
- **Lock screen:** separate image visually verified on the same system after `Super+L`.
- **Unified command:** initial `veilpaper.py` CLI implemented and offline-tested on the [experimental development branch](https://github.com/tobiasGuta/Veilpaper/tree/experimental/gnome50-lockscreen).
- **Public release:** **not yet ready**. Multi-machine compatibility, a safer generic GDM backup scheme, regression/recovery testing and a license are still needed.

> **Important:** The GDM backend currently contains a SHA-256 checksum specific to the system on which it was tested. It is not a generic installer. Editing a GNOME system theme can break graphical login. The lock-screen extension uses GNOME private interfaces, which can change in updates.

## Development

[View the experimental branch, source, commands and safety instructions](https://github.com/tobiasGuta/Veilpaper/tree/experimental/gnome50-lockscreen).

The planned user experience is one command for both wallpaper systems, although GNOME requires a separate extension JavaScript file for the lock screen.

This repository is public for transparency and early development; it is not yet a supported open-source release. License selection remains pending.
