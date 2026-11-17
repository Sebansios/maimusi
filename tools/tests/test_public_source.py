"""Publication boundary regressions: tracked private files and safe clean exports."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import public_source as ps


class PublicationTests(unittest.TestCase):
    def test_private_files_are_rejected_even_when_tracked(self):
        rules = ps.policy(TOOLS.parent)
        for name in ('nested/.Claude/settings.json', 'windows/AGENTS.md', 'core/AGENTS.override.md', 'internal/handoff.md',
                     '.github/copilot-instructions.md', '.env.production', 'models/secret.npz',
                     'docs/spacing-evaluation/corpus.json', 'new-root/file.py'):
            with self.subTest(name=name):
                self.assertIsNotNone(ps.path_error(name, rules))

    def test_product_public_keys_and_vendor_notices_are_allowed(self):
        rules = ps.policy(TOOLS.parent)
        for name in ('packaging/update-keys.json', 'core/vendor/example/LICENSE',
                     'engine/hangul_ime/converter_data/sources.json', 'linux/README.md'):
            self.assertIsNone(ps.path_error(name, rules))

    def test_personal_paths_and_credentials_fail_without_value_output(self):
        for raw in ('/Users/' + 'example/private/file', 'C:\\Users\\' + 'Example\\file',
                    '-----BEGIN ' + 'PRIVATE KEY-----', 'ghp_' + 'a' * 36):
            for data in (raw.encode(), raw.encode('utf-16-le')):
                self.assertIsNotNone(ps.content_error(data, []))
        self.assertIsNone(ps.content_error(b'/Users/$user', []))

    def test_symlink_is_rejected(self):
        failures = ps.audit([('core/link', b'', '120000')], ps.policy(TOOLS.parent), [])
        self.assertEqual(len(failures), 1)

    def test_force_tracked_ignored_file_still_fails_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('internal/\n')
            (root / 'internal').mkdir()
            (root / 'internal/private.md').write_text('private')
            subprocess.run(['git', '-C', str(root), 'add', '-f', 'internal/private.md'], check=True)
            failures = ps.audit(ps.worktree_entries(root), ps.policy(TOOLS.parent), [])
            self.assertEqual([name for name, reason in failures], ['internal/private.md'])

    def test_head_export_ignores_untracked_private_material_and_has_no_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'; root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'README.md').write_text('hello\n')
            for args in (('add', 'README.md'), ('-c', 'user.name=Test', '-c',
                         'user.email=test@example.invalid', 'commit', '-qm', 'test')):
                subprocess.run(['git', '-C', str(root), *args], check=True)
            (root / 'internal').mkdir()
            (root / 'internal/private.md').write_text('private')
            entries = ps.head_entries(root)
            dest = Path(tmp) / 'public'
            ps.export(root, dest, entries)
            self.assertEqual([p.name for p in dest.iterdir()], ['README.md'])
            with self.assertRaises(ValueError):
                ps.export(root, dest, entries)


if __name__ == '__main__':
    unittest.main()
