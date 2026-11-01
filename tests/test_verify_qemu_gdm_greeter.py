"""Read-only greeter identity recognition: Fedora gdm-greeter vs ordinary GNOME."""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'veilpaper_guest_greeter_identity', ROOT / 'scripts/verify_qemu_gdm_greeter.py')
greeter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(greeter)


class GreeterIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='veilpaper-gdm-greeter-unit-')
        self.addCleanup(self.temp.cleanup)
        self.proc = Path(self.temp.name)
        self.uid = os.getuid()
        directory = self.proc / '1218'
        directory.mkdir()
        (directory / 'cmdline').write_bytes(b'/usr/bin/gnome-shell\x00--mode=gdm\x00')

    def cmd(self, *, session_class='greeter', seat='seat0', name='gdm-greeter',
            uid=None, running=True, sessions='c1'):
        uid = self.uid if uid is None else uid
        def command(*args):
            if args[0] == 'systemctl':
                if not running:
                    raise greeter.GreeterNotReady('GDM inactive')
                return ''
            if args[:2] == ('loginctl', 'list-sessions'):
                return sessions + ' ' + str(uid) + ' ' + name + ' ' + seat + '\n'
            if args[:2] == ('loginctl', 'show-session'):
                return ('Class=' + session_class + '\nSeat=' + seat +
                        '\nName=' + name + '\nUser=' + str(uid) + '\n')
            raise AssertionError(args)
        return command

    def test_fedora_dynamic_gdm_greeter_passes(self):
        result = greeter.verify(command=self.cmd(), proc=self.proc)
        self.assertEqual(result['user'], 'gdm-greeter')
        self.assertEqual(result['pid'], 1218)
        self.assertEqual(result['session'], 'c1')

    def test_fedora_second_dynamic_greeter_after_restart_passes(self):
        # Actual Fedora 44 graphical VM diagnostic: c3, gdm-greeter-2.
        result = greeter.verify(
            command=self.cmd(name='gdm-greeter-2', sessions='c3'),
            proc=self.proc)
        self.assertEqual(result['user'], 'gdm-greeter-2')
        self.assertEqual(result['session'], 'c3')

    def test_dynamic_greeter_with_larger_numeric_suffix_passes(self):
        result = greeter.verify(
            command=self.cmd(name='gdm-greeter-12'), proc=self.proc)
        self.assertEqual(result['user'], 'gdm-greeter-12')

    def test_greeter_prefix_spoof_rejected(self):
        for username in ('gdm-greeter-extra', 'gdm-greeter-2-admin',
                         'gdm-greeter-0', 'gdm-greeter-02',
                         'gdm-greeter-', 'gdm-greeter+2'):
            with self.subTest(username=username):
                with self.assertRaises(greeter.GreeterNotReady):
                    greeter.verify(command=self.cmd(name=username), proc=self.proc)

    def test_legacy_gdm_account_passes_only_when_session_is_greeter(self):
        result = greeter.verify(command=self.cmd(name='gdm'), proc=self.proc)
        self.assertEqual(result['user'], 'gdm')

    def test_ordinary_desktop_session_not_greeter(self):
        with self.assertRaises(greeter.GreeterNotReady):
            greeter.verify(command=self.cmd(session_class='user', name='gdm'), proc=self.proc)

    def test_greeter_on_non_console_seat_is_denied(self):
        with self.assertRaises(greeter.GreeterNotReady):
            greeter.verify(command=self.cmd(seat='seat1'), proc=self.proc)

    def test_wrong_shell_user_rejected(self):
        with self.assertRaises(greeter.GreeterNotReady):
            greeter.verify(command=self.cmd(uid=self.uid + 10000), proc=self.proc)

    def test_gdm_service_inactive_denied(self):
        with self.assertRaises(greeter.GreeterNotReady):
            greeter.verify(command=self.cmd(running=False), proc=self.proc)

    def test_shell_without_gdm_mode_rejected(self):
        (self.proc / '1218' / 'cmdline').write_bytes(b'/usr/bin/gnome-shell\x00--wayland\x00')
        with self.assertRaises(greeter.GreeterNotReady):
            greeter.verify(command=self.cmd(), proc=self.proc)


if __name__ == '__main__':
    unittest.main()
