"""GUI backend tests: no GTK or real GNOME session required."""
import importlib.util
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('veilpaper_gui_backend', ROOT / 'gui/backend.py')
backend = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


class GUIBackendTests(unittest.TestCase):
    def test_empty_lock_image(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            self.assertIsNone(backend.lock_image())

    def test_existing_png_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            p = Path(temp) / 'veilpaper'
            p.mkdir()
            image = p / 'lock-wallpaper.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\nPNG')
            self.assertEqual(backend.lock_image(), image)

    def test_lock_symlink_does_not_count(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            directory = Path(temp) / 'veilpaper'
            directory.mkdir()
            target = Path(temp) / 'actual.png'
            target.write_bytes(b'\x89PNG\r\n\x1a\nPNG')
            (directory / 'lock-wallpaper.png').symlink_to(target)
            self.assertIsNone(backend.lock_image())

    def test_set_restore_use_existing_cli(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_DATA_HOME': temp}):
            source = Path(temp) / 'picture.png'
            source.write_bytes(b'\x89PNG\r\n\x1a\n' + b'fixture-PNG-data')
            with patch('os.geteuid', return_value=1000):
                copied = backend.set_lock(source)
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                backend.restore_lock()
                self.assertIsNone(backend.lock_image())

    def test_extension_active_status(self):
        info = '  Enabled: Yes\n  State: ACTIVE\n'
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gnome-extensions'), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0, stdout=info)):
            self.assertEqual(backend.extension_status(), 'Extension active')

    def test_extension_not_installed(self):
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gnome-extensions'), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=1, stdout='')):
            self.assertIn('not installed', backend.extension_status())

    def test_login_custom_status_detected(self):
        inspector = SimpleNamespace(inspect=lambda: {
            'active_matches_rpm': False, 'backup_matches_rpm': True})
        with patch.object(backend, '_load', return_value=inspector):
            self.assertEqual(backend.login_status()[0], 'Custom login theme detected')

    def test_login_status_no_baseline(self):
        inspector = SimpleNamespace(inspect=lambda: {
            'active_matches_rpm': False, 'backup_matches_rpm': False})
        with patch.object(backend, '_load', return_value=inspector):
            self.assertIn('needs attention', backend.login_status()[0])

    def test_login_preview_identifies_resource_without_writes(self):
        png = b'\x89PNG\r\n\x1a\n' + b'preview image'
        with patch.object(backend.shutil, 'which', return_value='/usr/bin/gresource'), \
             patch.object(backend.LOGIN_RESOURCE.__class__, 'is_file', return_value=True), \
             patch.object(backend.LOGIN_RESOURCE.__class__, 'is_symlink', return_value=False), \
             patch.object(backend.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0, stdout=png)):
            self.assertEqual(backend.login_preview(), (png, 'png'))

    def _mock_login_builder(self, root, *, fail=False, webp=False):
        baseline = root / 'stock.gresource'
        baseline.write_bytes(b'stock fixture')
        rpm_sha = hashlib.sha256(b'stock fixture').hexdigest()
        def image_type(path, allow_other=False):
            if Path(path).suffix == '.webp' and allow_other:
                return None
            return 'png'
        def convert(src, out):
            out.write_bytes(b'\x89PNG\r\n\x1a\nconverted')
        cli = SimpleNamespace(image_type=image_type, convert_to_png=convert)
        def build(input_image, output):
            if webp:
                self.assertEqual(Path(input_image).name, 'normalized.png')
            output.write_bytes(b'compiled fixture')
        def diff(original, candidate):
            self.assertEqual(original, baseline)
            if fail:
                raise RuntimeError('unexpected GDM resource diff')
            return ('/org/gnome/shell/theme/fedora-login-wallpaper.png', 9)
        def digest(path):
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        portable = SimpleNamespace(
            select_baseline=lambda: (baseline, rpm_sha),
            build=build,
            gdm=SimpleNamespace(sha256=digest),
        )
        reviewer = SimpleNamespace(_resource_differences=diff)
        def loader(path, name):
            if path == backend.CLI:
                return cli
            if path == backend.PORTABLE:
                return portable
            if path == backend.REVIEW:
                return reviewer
            raise AssertionError(path)
        return loader

    def test_prepare_login_candidate_is_unprivileged_and_stays_in_user_cache(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}):
            root = Path(temp)
            source = root / 'wallpaper.png'
            source.write_bytes(b'\x89PNG\r\n\x1a\ninput')
            with patch.object(backend.os, 'geteuid', return_value=1000), \
                 patch.object(backend, '_load', side_effect=self._mock_login_builder(root)):
                result = backend.prepare_login_candidate(source)
            self.assertTrue(result.path.is_file())
            self.assertEqual(result.path.read_bytes(), b'compiled fixture')
            self.assertEqual(result.path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(result.path.is_relative_to(root / 'veilpaper/login-candidates'))
            self.assertEqual(result.digest, hashlib.sha256(b'compiled fixture').hexdigest())
            self.assertEqual(sorted(p.name for p in result.path.parent.iterdir()), ['candidate.gresource'])
            self.assertTrue(source.exists())

    def test_webp_is_normalized_only_in_private_staging(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}):
            root = Path(temp)
            source = root / 'wallpaper.webp'
            source.write_bytes(b'RIFFxxxxWEBP12345')
            with patch.object(backend.os, 'geteuid', return_value=1000), \
                 patch.object(backend, '_load', side_effect=self._mock_login_builder(root, webp=True)):
                result = backend.prepare_login_candidate(source)
            self.assertTrue(result.path.is_file())
            self.assertFalse((result.path.parent / 'normalized.png').exists())
            self.assertEqual(source.read_bytes(), b'RIFFxxxxWEBP12345')

    def test_failed_candidate_review_deletes_temporary_job(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}):
            root = Path(temp)
            source = root / 'wallpaper.png'
            source.write_bytes(b'\x89PNG\r\n\x1a\ninput')
            with patch.object(backend.os, 'geteuid', return_value=1000), \
                 patch.object(backend, '_load', side_effect=self._mock_login_builder(root, fail=True)):
                with self.assertRaisesRegex(RuntimeError, 'unexpected GDM resource diff'):
                    backend.prepare_login_candidate(source)
            self.assertEqual(list((root / 'veilpaper/login-candidates').iterdir()), [])
            self.assertTrue(source.exists())

    def test_login_candidate_refuses_root(self):
        with patch.object(backend.os, 'geteuid', return_value=0), \
             patch.object(backend, '_load') as loader:
            with self.assertRaisesRegex(RuntimeError, 'as root'):
                backend.prepare_login_candidate(Path('/tmp/test.png'))
            loader.assert_not_called()

    def test_symlink_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            actual = root / 'real-cache'
            actual.mkdir()
            alias = root / 'alias'
            alias.symlink_to(actual, target_is_directory=True)
            with patch.dict(os.environ, {'XDG_CACHE_HOME': str(alias)}):
                with self.assertRaisesRegex(RuntimeError, 'symlink'):
                    backend._candidate_parent()

    def test_view_state_does_not_modify_system(self):
        with patch.object(backend, 'login_status', return_value=('Custom', 'Verified backup')), \
             patch.object(backend, 'extension_status', return_value='Extension active'), \
             patch.object(backend, 'lock_image', return_value=None):
            snapshot = backend.state()
            self.assertEqual(snapshot.login_label, 'Custom')
            self.assertIsNone(snapshot.lock_image)


    def _staged_candidate(self, cache_root, *, content=b'fake-resource'):
        staging = cache_root / 'veilpaper' / 'login-candidates' / 'prepared-example123'
        staging.mkdir(parents=True, mode=0o700)
        staging.chmod(0o700)
        path = staging / 'candidate.gresource'
        path.write_bytes(content)
        path.chmod(0o600)
        return backend.LoginCandidate(
            path=path,
            digest=hashlib.sha256(content).hexdigest(),
            baseline_digest='b' * 64,
            resource='/org/gnome/shell/theme/fedora-login-wallpaper.png')

    def test_discard_verified_candidate_only_removes_its_private_job(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            root = Path(temp)
            candidate = self._staged_candidate(root)
            unrelated = root / 'personal-wallpaper.png'
            unrelated.write_bytes(b'untouched')
            backend.discard_login_candidate(candidate)
            self.assertFalse(candidate.path.parent.exists())
            self.assertTrue((root / 'veilpaper/login-candidates').is_dir())
            self.assertEqual(unrelated.read_bytes(), b'untouched')

    def test_discard_changed_candidate_refuses_without_deleting(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            candidate = self._staged_candidate(Path(temp))
            candidate.path.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                backend.discard_login_candidate(candidate)
            self.assertTrue(candidate.path.exists())

    def test_discard_refuses_extra_unrecognized_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            candidate = self._staged_candidate(Path(temp))
            extra = candidate.path.parent / 'notes'
            extra.write_text('leave this alone')
            with self.assertRaisesRegex(RuntimeError, 'Unexpected files'):
                backend.discard_login_candidate(candidate)
            self.assertTrue(candidate.path.exists())
            self.assertTrue(extra.exists())

    def test_discard_refuses_wrong_permissions(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            candidate = self._staged_candidate(Path(temp))
            candidate.path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, 'private owned regular file'):
                backend.discard_login_candidate(candidate)
            self.assertTrue(candidate.path.exists())

    def test_discard_refuses_root_and_foreign_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}):
            candidate = self._staged_candidate(Path(temp))
            with patch.object(backend.os, 'geteuid', return_value=0):
                with self.assertRaisesRegex(RuntimeError, 'as root'):
                    backend.discard_login_candidate(candidate)
            foreign = backend.LoginCandidate(
                path=Path(temp) / 'personal-wallpaper.png',
                digest=candidate.digest,
                baseline_digest=candidate.baseline_digest,
                resource=candidate.resource)
            with patch.object(backend.os, 'geteuid', return_value=1000):
                with self.assertRaisesRegex(RuntimeError, 'outside'):
                    backend.discard_login_candidate(foreign)
            self.assertTrue(candidate.path.exists())

    def test_discard_refuses_symlinked_candidate_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            root = Path(temp)
            candidate = self._staged_candidate(root)
            elsewhere = root / 'do-not-delete.txt'
            elsewhere.write_text('important')
            candidate.path.unlink()
            candidate.path.symlink_to(elsewhere)
            with self.assertRaises(OSError):
                backend.discard_login_candidate(candidate)
            self.assertTrue(candidate.path.is_symlink())
            self.assertEqual(elsewhere.read_text(), 'important')

    def test_discard_refuses_symlinked_staging_directory(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'XDG_CACHE_HOME': temp}), \
             patch.object(backend.os, 'geteuid', return_value=1000):
            root = Path(temp)
            candidate = self._staged_candidate(root)
            original_folder = candidate.path.parent
            other_folder = root / 'elsewhere'
            original_folder.rename(other_folder)
            original_folder.symlink_to(other_folder, target_is_directory=True)
            with self.assertRaises(OSError):
                backend.discard_login_candidate(candidate)
            self.assertTrue((other_folder / 'candidate.gresource').exists())
            self.assertTrue(original_folder.is_symlink())


    def _review_candidate(self):
        return backend.LoginCandidate(
            path=Path('/tmp/prepared-example/candidate.gresource'),
            digest='a' * 64, baseline_digest='b' * 64,
            resource='/org/gnome/shell/theme/fedora-login-wallpaper.png')

    def _review_evidence(self, candidate, **override):
        data = {
            'schema_version': 1, 'read_only': True,
            'authorization': 'NOT_GRANTED', 'privileged_helper_available': False,
            'action': 'install', 'candidate': str(candidate.path),
            'expected_sha256': candidate.digest,
            'candidate_sha256': candidate.digest,
            'existing_customization': 'NONE_DETECTED',
            'verdict': 'STRUCTURAL_REVIEW_ONLY',
            'issues': [],
        }
        data.update(override)
        return data

    def test_gui_readiness_clean_is_explicitly_not_install_approval(self):
        candidate = self._review_candidate()
        evidence = self._review_evidence(candidate)
        inspector = SimpleNamespace(inspect_action=lambda *a, **k: evidence)
        with patch.object(backend.os, 'geteuid', return_value=1000), \
             patch.object(backend, '_load', return_value=inspector) as loader:
            result = backend.review_login_candidate(candidate)
        loader.assert_called_once_with(backend.APPROVAL, 'veilpaper_gui_approval_review')
        self.assertEqual(result.verdict, 'STRUCTURAL_REVIEW_ONLY')
        self.assertIn('no installation approved', result.headline)
        self.assertIn('administrator authorization', result.explanation)
        self.assertEqual(result.issues, ())

    def test_gui_readiness_customized_theme_is_blocked_and_described(self):
        candidate = self._review_candidate()
        evidence = self._review_evidence(candidate,
            verdict='BLOCKED', existing_customization='CUSTOM_OR_UNKNOWN',
            issues=['Existing or unknown GDM customization must be preserved.'])
        with patch.object(backend.os, 'geteuid', return_value=1000), \
             patch.object(backend, '_load',
                          return_value=SimpleNamespace(inspect_action=lambda *a, **k: evidence)):
            result = backend.review_login_candidate(candidate)
        self.assertEqual(result.verdict, 'BLOCKED')
        self.assertIn('preserved', result.headline)
        self.assertIn('preserved.', result.issues[0])

    def test_gui_readiness_malformed_report_is_not_presented_as_clean(self):
        candidate = self._review_candidate()
        evidence = self._review_evidence(candidate, authorization='GRANTED')
        with patch.object(backend.os, 'geteuid', return_value=1000), \
             patch.object(backend, '_load',
                          return_value=SimpleNamespace(inspect_action=lambda *a, **k: evidence)):
            with self.assertRaisesRegex(RuntimeError, 'invalid evidence contract'):
                backend.review_login_candidate(candidate)

    def test_gui_readiness_contradictory_clean_evidence_rejected(self):
        candidate = self._review_candidate()
        evidence = self._review_evidence(candidate, existing_customization='CUSTOM_OR_UNKNOWN')
        with patch.object(backend.os, 'geteuid', return_value=1000), \
             patch.object(backend, '_load',
                          return_value=SimpleNamespace(inspect_action=lambda *a, **k: evidence)):
            with self.assertRaisesRegex(RuntimeError, 'Contradictory'):
                backend.review_login_candidate(candidate)

    def test_gui_readiness_refuses_root_and_invalid_candidate_before_import(self):
        candidate = self._review_candidate()
        with patch.object(backend.os, 'geteuid', return_value=0), \
             patch.object(backend, '_load') as loader:
            with self.assertRaisesRegex(RuntimeError, 'regular user'):
                backend.review_login_candidate(candidate)
            loader.assert_not_called()
        candidate = backend.LoginCandidate(
            path=candidate.path, digest='not-a-hash', baseline_digest='b'*64,
            resource=candidate.resource)
        with patch.object(backend.os, 'geteuid', return_value=1000), \
             patch.object(backend, '_load') as loader:
            with self.assertRaisesRegex(RuntimeError, 'exact SHA-256'):
                backend.review_login_candidate(candidate)
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
