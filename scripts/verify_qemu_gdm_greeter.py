#!/usr/bin/env python3
"""Read-only identity proof for a real Fedora GNOME Display Manager greeter.

Reject a running gdm.service without a seat0 Class=greeter loginctl session
and a matching GNOME Shell process owned by its session UID. This tool does
not change any guest/host configuration or authenticate a user.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import subprocess
import sys


class GreeterNotReady(RuntimeError):
    pass


def _command(*args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, check=False,
                           timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GreeterNotReady(f'Command failed: {args[0]}: {exc}') from exc
    if p.returncode:
        raise GreeterNotReady(f'{args[0]} returned {p.returncode}: {p.stderr.strip()}')
    return p.stdout


def _properties(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def _shell_for_uid(uid, *, proc=Path('/proc')):
    for p in proc.iterdir():
        if not p.name.isdecimal():
            continue
        try:
            if p.stat().st_uid != uid:
                continue
            args = (p / 'cmdline').read_bytes().split(b'\x00')
            if not args or Path(os.fsdecode(args[0])).name != 'gnome-shell':
                continue
            if b'--mode=gdm' in args:
                return int(p.name)
        except (OSError, UnicodeError, ValueError):
            continue
    return None


def verify(*, command=_command, proc=Path('/proc')):
    command('systemctl', 'is-active', '--quiet', 'gdm.service')
    sessions = command('loginctl', 'list-sessions', '--no-legend')
    for line in sessions.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        sid = tokens[0]
        if not sid.replace('_', '').isalnum():
            continue
        props = _properties(command('loginctl', 'show-session', sid,
                                     '--property=Class',
                                     '--property=Seat',
                                     '--property=Name',
                                     '--property=User'))
        if props.get('Class') != 'greeter' or props.get('Seat') != 'seat0':
            continue
        # Fedora's dynamic-user GDM sessions may be suffixed after a
        # display-manager restart: gdm-greeter, gdm-greeter-2, etc.
        # Do not accept arbitrary similarly named desktop accounts.
        name = props.get('Name', '')
        if not (name == 'gdm' or
                re.fullmatch(r'gdm-greeter(?:-[1-9][0-9]*)?', name)):
            continue
        try:
            uid = int(props['User'])
        except (KeyError, ValueError):
            continue
        pid = _shell_for_uid(uid, proc=proc)
        if pid is not None:
            return {'session': sid, 'user': props['Name'], 'uid': uid, 'pid': pid}
    raise GreeterNotReady('No seat0 GDM greeter session with matching gnome-shell --mode=gdm')


def main():
    try:
        found = verify()
    except GreeterNotReady as exc:
        print('GREETER_NOT_READY: ' + str(exc), file=sys.stderr)
        return 1
    print('GREETER_IDENTITY_PASS: session={session} name={user} uid={uid} '
          'gnome-shell-pid={pid}'.format(**found))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
