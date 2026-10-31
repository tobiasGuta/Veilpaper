# Veilpaper

**Your screens. Your wallpapers.**

Independent **GDM login** and **GNOME lock-screen** wallpaper customization without replacing your desktop wallpaper.

> **Experimental source, not a released application.** Do not treat this repository as a supported one-command installer.

## Status

| Component | State |
| --- | --- |
| GDM login screen | Verified on one Fedora 44 / GNOME Shell 50.6 / GDM 50.3 laptop |
| Lock-screen extension | Source prototype; **not runtime-tested** |
| Unified `veilpaper` CLI | Planned |
| Universal installation and recovery | Not yet implemented |

Development files are being prepared on [`experimental/gnome50-lockscreen`](https://github.com/tobiasGuta/Veilpaper/tree/experimental/gnome50-lockscreen).

The existing GDM Python tool uses a checksum specific to the one machine where it was tested. It is reference material only until generalized. System-theme changes can break the graphical login; keep an independently verified original and TTY recovery access.

The lock-screen extension uses GNOME Shell **private** interfaces. It intentionally leaves authentication untouched, but must pass real lock/unlock/rollback tests before being recommended to others.

## Planned single interface

```text
veilpaper set-login IMAGE
veilpaper set-lock IMAGE
veilpaper status
veilpaper restore-login
veilpaper restore-lock
```

These commands are **design goals, not available yet**.

**Licensing:** no license has been chosen; please do not assume redistribution rights until one is added.
