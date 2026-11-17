import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('publish_update', TOOLS / 'publish_update.py')
pu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pu)
um = pu.um


class PublishOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            um.main(['keygen', '--id', 'pub-1', '--out', str(self.dir / 'keys')])
        key_id, public = out.getvalue().split()
        self.ring = self.dir / 'ring.json'
        self.ring.write_text(json.dumps({'keys': {key_id: public}}))
        self.pkg = self.dir / 'Maimusi-9.9.9.pkg'
        self.pkg.write_bytes(b'package bytes')
        self.local = (self.pkg.stat().st_size, um.sha256_file(self.pkg))
        self.build = int(json.loads((um.ROOT / 'versions.json').read_text())['build'])

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, remote, current=None):
        args = ['--platform', 'macos', '--file', str(self.pkg), '--key', str(self.dir / 'keys/pub-1.key'),
                '--keys', str(self.ring), '--out-dir', str(self.dir / 'out')]
        with mock.patch.object(pu, 'remote_sha256', return_value=remote), \
             mock.patch.object(pu, 'fetch', return_value=current), \
             mock.patch.object(pu.subprocess, 'run') as run, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = pu.main(args)
        return code, run

    def published(self, build):
        envelope = json.loads((self.dir / 'out/macos.json').read_text())
        payload = json.loads(base64.b64decode(envelope['payload']))
        payload['build'] = build
        body = json.dumps(payload).encode()
        key = json.loads((self.dir / 'keys/pub-1.key').read_text())
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        sig = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key['private'])).sign(um.DOMAIN + body)
        envelope.update(payload=base64.b64encode(body).decode(), signature=base64.b64encode(sig).decode())
        return json.dumps(envelope).encode()

    def test_installer_must_be_public_first(self):
        self.assertEqual(self.run_tool(remote=None)[0], 1)
        self.assertFalse((self.dir / 'out/macos.json').exists())

    def test_signing_key_must_be_explicit_before_any_external_request(self):
        with mock.patch.dict(pu.os.environ, {}, clear=True), \
             mock.patch.object(pu, 'remote_sha256') as remote, \
             mock.patch.object(pu.subprocess, 'run') as run, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                pu.main(['--platform', 'macos', '--file', str(self.pkg)])
        self.assertEqual(result.exception.code, 2)
        remote.assert_not_called()
        run.assert_not_called()

    def test_public_installer_must_match(self):
        self.assertEqual(self.run_tool(remote=(self.local[0], '0' * 64))[0], 1)

    def test_dry_run_signs_but_does_not_upload(self):
        code, run = self.run_tool(remote=self.local)
        self.assertEqual(code, 0)
        info = um.verify_manifest((self.dir / 'out/macos.json').read_bytes(), um.load_keys(self.ring), 'macos')
        self.assertEqual(info['file']['url'], pu.PUBLIC + self.pkg.name)
        self.assertEqual(info['minimum_os'], '13.0')
        uploads = [c for c in run.call_args_list if 'r2' in c.args[0]]
        self.assertEqual(uploads, [])

    def test_never_goes_below_published_build(self):
        self.assertEqual(self.run_tool(remote=self.local)[0], 0)
        higher = self.published(self.build + 5)
        self.assertEqual(self.run_tool(remote=self.local, current=higher)[0], 1)
        same = self.published(self.build)
        self.assertEqual(self.run_tool(remote=self.local, current=same)[0], 1)
        lower = self.published(self.build - 1)
        self.assertEqual(self.run_tool(remote=self.local, current=lower)[0], 0)


if __name__ == '__main__':
    unittest.main()
