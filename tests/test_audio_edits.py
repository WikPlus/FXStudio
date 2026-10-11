import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from core import Studio


class AudioEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.studio = Studio(data_dir=self.folder / 'data', library_root=self.folder / 'library')
        self.source = self.folder / 'original.wav'
        self.rate = 48000
        time = np.arange(self.rate) / self.rate
        sf.write(self.source, np.column_stack((.35 + .2 * np.sin(2 * np.pi * 137 * time), np.full(self.rate, .2))), self.rate, subtype='PCM_24')
        self.original = hashlib.sha256(self.source.read_bytes()).digest()
        self.id = '0123456789ab'
        settings = self.studio.validate({'prompt': 'A mechanical click', 'seconds': 1})
        self.studio.execute('INSERT INTO items(id,title,prompt,settings,path,created,duration,favorite,seed) VALUES(?,?,?,?,?,?,?,?,?)',
                            (self.id, 'A mechanical / click', 'A mechanical click', json.dumps(settings), str(self.source), 1, 1, 1, 7))

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def test_sample_accurate_fades_channels_and_persistence(self):
        original, _ = sf.read(self.source, always_2d=True)
        item = self.studio.set_trim(self.id, {'start': .125, 'end': .725})
        path = self.studio.media_path(self.id)
        samples, rate = sf.read(path, always_2d=True)
        self.assertEqual(rate, self.rate)
        self.assertEqual(samples.shape, (28800, 2))
        self.assertEqual(sf.info(path).subtype, 'PCM_24')
        np.testing.assert_array_equal(samples[[0, -1]], 0)
        np.testing.assert_allclose(samples[240:-240], original[6000 + 240:34800 - 240], atol=2 / 2**23)
        self.assertLess(samples[1, 1], samples[120, 1])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        self.assertTrue(item['favorite'])
        self.assertAlmostEqual(item['duration'], .6)
        self.assertEqual(item['source_duration'], 1)
        self.studio.close()
        self.studio = Studio(data_dir=self.folder / 'data', library_root=self.folder / 'library')
        self.assertEqual(self.studio.media_path(self.id), path)
        self.assertAlmostEqual(self.studio.item(self.id)['duration'], .6)

    def test_invalid_ranges_failed_render_and_recovery(self):
        self.studio.set_trim(self.id, {'start': .1, 'end': .9})
        previous = self.studio.item(self.id)['trim']
        for raw in ([], {}, {'start': True, 'end': .8}, {'start': float('nan'), 'end': .8},
                    {'start': 0, 'end': float('inf')}, {'start': -.1, 'end': .8},
                    {'start': .7, 'end': .5}, {'start': .1, 'end': 1.1}, {'start': .1, 'end': .105}):
            with self.assertRaises(ValueError):
                self.studio.set_trim(self.id, raw)
            self.assertEqual(self.studio.item(self.id)['trim'], previous)
        with patch('core.render_trim', side_effect=ValueError('Failed to read audio')):
            with self.assertRaisesRegex(ValueError, 'read audio'):
                self.studio.set_trim(self.id, {'start': .2, 'end': .8})
        self.assertEqual(self.studio.item(self.id)['trim'], previous)
        self.assertAlmostEqual(self.studio.set_trim(self.id, {'start': .2, 'end': .8})['duration'], .6)

    def test_drag_files_survive_reset_and_later_edits(self):
        self.studio.set_trim(self.id, {'start': .1, 'end': .7})
        first = Path(self.studio.prepare_drag(self.id)['path'])
        data = first.read_bytes()
        self.assertNotIn('/', first.name)
        self.studio.set_trim(self.id, {'start': .2, 'end': .8})
        second = Path(self.studio.prepare_drag(self.id)['path'])
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), data)
        self.studio.set_trim(self.id, {'reset': True})
        self.assertIsNone(self.studio.item(self.id)['trim'])
        self.assertEqual(self.studio.media_path(self.id), self.source)
        self.assertEqual(first.read_bytes(), data)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        with self.assertRaises(KeyError):
            self.studio.prepare_drag('../../etc/passwd')

    def test_library_stays_read_only_and_retains_provenance(self):
        library_id = 'SFX0999'
        self.studio.library[library_id] = {'id': library_id, 'path': str(self.source), 'title': 'Library click',
            'duration': 1, 'kind': 'library', 'category': 'Foley', 'source': {'supplier': 'Test supplier'},
            'license': {'status': 'documented_bundle', 'document': 'LICENSE.txt'}}
        before = self.studio.item(library_id)
        self.assertEqual(self.studio.prepare_drag(library_id)['path'], str(self.source))
        self.assertFalse((self.studio.data / 'drag-exports').exists())
        after = self.studio.set_trim(library_id, {'start': .2, 'end': .8})
        self.assertEqual(after['source'], before['source'])
        self.assertEqual(after['license'], before['license'])
        self.assertEqual(self.studio.library_items()[0]['trim'], after['trim'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        self.assertTrue(self.studio.media_path(library_id).is_relative_to(self.studio.data))

    def test_missing_original_does_not_silently_use_cached_audio(self):
        self.studio.set_trim(self.id, {'start': .1, 'end': .9})
        self.source.unlink()
        self.assertTrue(self.studio.item(self.id)['missing'])
        for action in (self.studio.media_path, self.studio.prepare_drag):
            with self.assertRaises(KeyError):
                action(self.id)
