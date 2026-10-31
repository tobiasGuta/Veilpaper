#!/usr/bin/env python3
"""Capture one QEMU display head through QMP; screenshot is EVIDENCE, not visual PASS.

This helper runs only on an ephemeral GitHub Actions runner. It cannot touch
the guest disk, apply a GDM theme, or operate on a workstation. Requires the
caller to supply an absolute UNIX socket path and an artifact PNG destination.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time

PNG = b'\x89PNG\r\n\x1a\n'


class CaptureBlocked(RuntimeError):
    pass


def _receive(stream, expected_id, *, limit=500):
    for _ in range(limit):
        line = stream.readline()
        if not line:
            raise CaptureBlocked('QMP closed before response')
        if len(line) > 262144:
            raise CaptureBlocked('Oversized QMP response')
        try:
            obj = json.loads(line)
        except (UnicodeError, ValueError) as error:
            raise CaptureBlocked(f'Invalid QMP response: {error}') from error
        if obj.get('id') == expected_id:
            if 'error' in obj:
                raise CaptureBlocked(f'QMP failed: {obj["error"]}')
            if 'return' not in obj:
                raise CaptureBlocked('QMP result not present')
            return obj['return']
    raise CaptureBlocked('QMP response deadline exceeded')


def capture(sock: Path, output: Path):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise CaptureBlocked('Screenshots permitted only on ephemeral GitHub Actions runner')
    sock = Path(sock)
    output = Path(output)
    if not sock.is_absolute() or not output.is_absolute():
        raise CaptureBlocked('Socket and screenshot paths must be absolute')
    if not sock.is_socket():
        raise CaptureBlocked('QMP socket missing or not a UNIX socket')
    if output.exists() or output.is_symlink():
        raise CaptureBlocked('Refusing to overwrite existing screenshot')
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(20)
        connection.connect(str(sock))
        with connection.makefile('rb') as incoming:
            line = incoming.readline()
            greeting = json.loads(line)
            if 'QMP' not in greeting:
                raise CaptureBlocked('Missing QMP handshake')
            connection.sendall(b'{"execute":"qmp_capabilities","id":"hello"}\r\n')
            _receive(incoming, 'hello')
            args = {'filename': str(output), 'format': 'png'}
            cmd = {'execute': 'screendump', 'arguments': args, 'id': 'screen'}
            connection.sendall((json.dumps(cmd) + '\r\n').encode())
            _receive(incoming, 'screen')
    # Screenshot can be nonblank without depicting GDM, so this is only a
    # structural artifact check, deliberately NOT a graphic success verdict.
    data = output.read_bytes()
    if len(data) < 512 or not data.startswith(PNG):
        raise CaptureBlocked('QEMU did not produce a valid PNG screenshot')
    if len(data) < 24:
        raise CaptureBlocked('PNG header truncated')
    w, h = struct.unpack('>II', data[16:24])
    if w < 640 or h < 480 or w > 8192 or h > 8192:
        raise CaptureBlocked(f'Unexpected QEMU display dimensions {w}x{h}')
    return w, h


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        w, h = capture(args.socket, args.output)
        print(f'SCREENSHOT_CAPTURED {w}x{h}: {args.output}')
        print('EVIDENCE ONLY: greeter identity and wallpaper visibility require separate verification.')
        return 0
    except (CaptureBlocked, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f'BLOCKED: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
