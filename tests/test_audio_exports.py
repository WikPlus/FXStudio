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
from agent_access import AgentAccess
from agent_api import AgentAPI
from test_core import fixture, wait


class AudioExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'original.wav'
        self.rate = 48000
        t = np.arange(self.rate * 3) / self.rate
        self.samples = np.column_stack((.4 * np.sin(2 * np.pi * 237 * t), .3 * np.sin(2 * np.pi * 517 * t)))
        sf.write(self.source, self.samples, self.rate, subtype='PCM_24')
        self.original = hashlib.sha256(self.source.read_bytes()).digest()

    def tearDown(self):
        self.temp.cleanup()

    def test_real_vorbis_stream_preserves_rate_channels_duration_and_original(self):
        target = self.folder / 'stereo.ogg'
        with patch('core.ffmpeg_binary', return_value=None):
            Studio.convert(self.source, target, 'ogg')
        self.assertEqual(target.read_bytes()[:4], b'OggS')
        info = sf.info(target)
        self.assertEqual((info.format, info.subtype), ('OGG', 'VORBIS'))
        self.assertEqual((info.frames, info.samplerate, info.channels), (144000, self.rate, 2))
        audio, _ = sf.read(target, always_2d=True)
        self.assertTrue(np.isfinite(audio).all())
        self.assertLess(np.sqrt(np.mean((audio - self.samples) ** 2)), .015)
        self.assertLess(target.stat().st_size, self.source.stat().st_size / 4)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        mono = self.folder / 'mono.wav'
        sf.write(mono, self.samples[:, 0], self.rate)
        Studio.convert(mono, self.folder / 'mono.ogg', 'ogg')
        self.assertEqual(sf.info(self.folder / 'mono.ogg').channels, 1)

    def test_failure_preserves_existing_file_and_retry_works(self):
        target = self.folder / 'safe.ogg'
        target.write_bytes(b'previous export')
        with patch('audio_exports.ogg_available', return_value=False):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                Studio.convert(self.source, target, 'ogg')
        with patch.object(sf.SoundFile, 'write', side_effect=RuntimeError('encoder failed')):
            with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
                Studio.convert(self.source, target, 'ogg')
        self.assertEqual(target.read_bytes(), b'previous export')
        self.assertEqual(list(self.folder.glob('.fx-ogg-*')), [])
        with self.assertRaises(ValueError):
            Studio.convert(self.source, self.source, 'ogg')
        with self.assertRaises(ValueError):
            Studio.convert(self.source, target, 'exe')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        Studio.convert(self.source, target, 'ogg')
        self.assertEqual(sf.info(target).subtype, 'VORBIS')

    def test_agent_ogg_uses_saved_crop_fades_and_preserves_provenance_no_overwrite(self):
        studio = Studio(self.folder / 'data', library_root=self.folder / 'library')
        try:
            api = AgentAPI(studio, AgentAccess(studio.data))
            settings = studio.validate({'prompt': 'A clean mechanical click.', 'seconds': 3})
            studio.execute('INSERT INTO items(id,title,prompt,settings,path,created,duration,seed) VALUES(?,?,?,?,?,?,?,?)',
                           ('0123456789ab', 'Click', settings['prompt'], json.dumps(settings), str(self.source), 1, 3, 7))
            studio.set_trim('0123456789ab', {'start': .25, 'end': 2.25})
            export = api.export_sound({'sound_id': '0123456789ab', 'name': 'click', 'format': 'ogg'})
            audio, rate = sf.read(export['path'], always_2d=True)
            self.assertEqual((len(audio), rate), (96000, self.rate))
            saved, _ = sf.read(studio.media_path('0123456789ab'), always_2d=True)
            self.assertLess(np.sqrt(np.mean((audio - saved) ** 2)), .015)
            self.assertLess(np.max(np.abs(audio[[0, -1]])), .03)
            self.assertEqual(export['format'], 'ogg')
            self.assertEqual(export['trim']['fade_ms'], 5)
            self.assertEqual(export['seed'], 7)
            self.assertIn('Community License', export['license']['name'])
            exported_hash = hashlib.sha256(Path(export['path']).read_bytes()).digest()
            with self.assertRaises(FileExistsError):
                api.export_sound({'sound_id': '0123456789ab', 'name': 'click', 'format': 'ogg'})
            self.assertEqual(hashlib.sha256(Path(export['path']).read_bytes()).digest(), exported_hash)
            with patch.object(studio, 'convert', side_effect=RuntimeError('encoder failed')):
                with self.assertRaises(RuntimeError):
                    api.export_sound({'sound_id': '0123456789ab', 'name': 'retry', 'format': 'ogg'})
            self.assertFalse((Path(export['path']).parent / 'retry.ogg').exists())
            self.assertEqual(api.export_sound({'sound_id': '0123456789ab', 'name': 'retry', 'format': 'ogg'})['format'], 'ogg')
            self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)
        finally:
            studio.close()

    def test_generation_saves_only_ogg_and_encoder_failure_recovers(self):
        studio = Studio(self.folder / 'generated', library_root=self.folder / 'library', command_factory=fixture)
        try:
            with patch('core.export_ogg', side_effect=ValueError('OGG encoder failed')):
                job = studio.enqueue({'prompt': 'test', 'seconds': .5, 'seed': 42})
                failed = wait(studio, job['id'])
            self.assertEqual(failed['state'], 'failed')
            self.assertIn('OGG encoder failed', failed['error'])
            self.assertEqual(studio.items(), [])
            self.assertEqual(list(studio.audio.glob('*')), [])
            job = studio.enqueue({'prompt': 'test', 'seconds': .5, 'seed': 42})
            self.assertEqual(wait(studio, job['id'])['state'], 'completed')
            item = studio.items()[0]
            self.assertEqual(Path(item['path']).suffix, '.ogg')
            self.assertEqual(sf.info(item['path']).subtype, 'VORBIS')
            self.assertEqual(list(studio.audio.glob('*.wav')), [])
            studio.set_trim(item['id'], {'start': .1, 'end': .3})
            crop = studio.media_path(item['id'])
            self.assertEqual(crop.suffix, '.ogg')
            self.assertEqual(sf.info(crop).frames, 8820)
            self.assertEqual(studio.prepare_drag(item['id'])['format'], 'ogg')
            self.assertEqual(list((studio.data / 'edits').glob('*.wav')), [])
        finally:
            studio.close()
