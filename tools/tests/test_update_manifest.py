import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('update_manifest', Path(__file__).resolve().parents[1] / 'update_manifest.py')
um = importlib.util.module_from_spec(spec)
spec.loader.exec_module(um)


class UpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            um.main(['keygen', '--id', 'test-1', '--out', str(self.dir / 'keys')])
        key_id, public = out.getvalue().split()
        self.ring = self.dir / 'ring.json'
        self.ring.write_text(json.dumps({'keys': {key_id: public}}))
        self.pkg = self.dir / 'Maimusi-9.9.9.pkg'
        self.pkg.write_bytes(b'not really a package')
        self.notes = self.dir / 'notes.txt'
        self.notes.write_text('- 첫 번째\n\n* 두 번째\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def sign(self, *extra):
        out = self.dir / 'macos.json'
        um.main(['sign', '--platform', 'macos', '--file', str(self.pkg), '--key', str(self.dir / 'keys/test-1.key'),
                 '--keys', str(self.ring), '--notes', str(self.notes), '--out', str(out), *extra])
        return out

    def test_round_trip(self):
        info = um.verify_manifest(self.sign('--minimum-os', '13.0').read_bytes(), um.load_keys(self.ring), 'macos')
        self.assertEqual(info['platform'], 'macos')
        self.assertEqual(info['notes'], ['첫 번째', '두 번째'])
        self.assertEqual(info['file']['bytes'], len(b'not really a package'))
        self.assertEqual(info['file']['url'], 'https://dl.sebansios.com/maimusi/Maimusi-9.9.9.pkg')
        self.assertEqual(info['minimum_os'], '13.0')
        self.assertEqual(info['channel'], 'stable')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(um.main(['verify', str(self.dir / 'macos.json'), '--file', str(self.pkg),
                                      '--keys', str(self.ring)]), 0)

    @unittest.skipUnless(os.name == 'posix', 'POSIX mode bits; release signing runs on macOS')
    def test_private_key_posix_permissions(self):
        self.assertEqual((self.dir / 'keys/test-1.key').stat().st_mode & 0o777, 0o600)

    def test_keygen_does_not_overwrite_existing_key(self):
        with self.assertRaises(SystemExit):
            um.main(['keygen', '--id', 'test-1', '--out', str(self.dir / 'keys')])

    def test_tampered_payload_rejected(self):
        envelope = json.loads(self.sign().read_text())
        payload = json.loads(base64.b64decode(envelope['payload']))
        payload['build'] += 1
        envelope['payload'] = base64.b64encode(json.dumps(payload).encode()).decode()
        with self.assertRaisesRegex(ValueError, 'signature'):
            um.verify_manifest(json.dumps(envelope).encode(), um.load_keys(self.ring))

    def test_key_outside_ring_refused(self):
        with contextlib.redirect_stdout(io.StringIO()):
            um.main(['keygen', '--id', 'stray', '--out', str(self.dir / 'keys')])
        with self.assertRaisesRegex(SystemExit, 'not in'):
            um.main(['sign', '--platform', 'macos', '--file', str(self.pkg), '--key', str(self.dir / 'keys/stray.key'),
                     '--keys', str(self.ring), '--out', str(self.dir / 'x.json')])

    def test_wrong_platform_and_file_mismatch(self):
        data = self.sign().read_bytes()
        with self.assertRaisesRegex(ValueError, 'platform'):
            um.verify_manifest(data, um.load_keys(self.ring), 'windows')
        self.pkg.write_bytes(b'changed')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(um.main(['verify', str(self.dir / 'macos.json'), '--file', str(self.pkg),
                                      '--keys', str(self.ring)]), 1)

    def test_loopback_url_only_for_tests(self):
        with contextlib.redirect_stderr(io.StringIO()):
            data = self.sign('--url', 'http://127.0.0.1:8000/Maimusi-9.9.9.pkg').read_bytes()
        with self.assertRaisesRegex(ValueError, 'file'):
            um.verify_manifest(data, um.load_keys(self.ring))
        self.assertEqual(um.verify_manifest(data, um.load_keys(self.ring), allow_loopback=True)['build'] > 0, True)
        with self.assertRaises(SystemExit):
            self.sign('--url', 'http://dl.sebansios.com/x.pkg')

    def test_shipped_ring_is_valid(self):
        keys = um.load_keys(um.ROOT / 'packaging/update-keys.json')
        ring = json.loads((um.ROOT / 'packaging/update-keys.json').read_text())
        self.assertIn(ring['signing'], keys)
        self.assertGreaterEqual(len(keys), 2, 'keep a backup key for rotation')


if __name__ == '__main__':
    unittest.main()
