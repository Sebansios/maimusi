import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('versions', Path(__file__).resolve().parents[1] / 'versions.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class VersionTests(unittest.TestCase):
    def test_generated_files_are_current(self):
        for name, expected in v.outputs(v.ROOT, v.load()).items():
            self.assertEqual((v.ROOT / name).read_text(encoding='utf-8'), expected, name)

    def test_only_core_package_version_changes(self):
        data = dict(v.load(), product='0.6.0', engine='0.2.0')
        files = v.outputs(v.ROOT, data)
        self.assertIn('version = "0.6.0"', files['core/Cargo.lock'])
        self.assertIn('version = "1.12.0"', files['core/Cargo.lock'])
        self.assertIn('ENGINE_VERSION = "0.2.0"', files['engine/hangul_ime/_version.py'])

    def test_invalid_metadata_rejected(self):
        for key, value in [('product', '01.2.3'), ('engine', 'bad'), ('build', True),
                           ('build', 0), ('release_suffix', '$(id)'), ('release_label', 'Beta 1')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'versions.json').write_text(json.dumps(dict(v.load(), **{key: value})), encoding="utf-8")
                with self.assertRaises(ValueError):
                    v.load(root)
