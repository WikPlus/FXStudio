"""Release packaging must never silently omit license/source materials."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect_licenses import validate_license_bundle


class ReleaseLicenseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / 'LICENSE').write_text('Fixture license notice\n')
        (self.folder / 'source.tar.gz').write_bytes(b'fixture corresponding source archive')
        self.manifest = {'schema': 1, 'components': [{'name': 'Fixture LGPL component', 'license_files': ['LICENSE']}],
                         'files': [{'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                                   for p in (self.folder / 'LICENSE', self.folder / 'source.tar.gz')]}
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.folder / 'inventory.json').write_text(json.dumps(self.manifest))

    def test_missing_corresponding_source_blocks_packaging(self):
        validate_license_bundle(self.folder)
        (self.folder / 'source.tar.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'source.tar.gz'):
            validate_license_bundle(self.folder)

    def test_changed_notice_blocks_packaging(self):
        (self.folder / 'LICENSE').write_text('Changed notice\n')
        with self.assertRaisesRegex(ValueError, 'LICENSE'):
            validate_license_bundle(self.folder)

    def test_component_without_license_blocks_packaging(self):
        self.manifest['components'].append({'name': 'Unlicensed dependency', 'license_files': []})
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unlicensed dependency'):
            validate_license_bundle(self.folder)

    def test_external_material_cannot_replace_bundled_source(self):
        self.manifest['files'][1]['path'] = '../source.tar.gz'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            validate_license_bundle(self.folder)


if __name__ == '__main__':
    unittest.main()
