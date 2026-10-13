"""Real encoders and queue behavior using disposable synthetic audio."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import soundfile as sf

from test_core import Studio, fixture, wait
from agent_access import AgentAccess
from agent_api import AgentAPI


class GenerationFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.studio = Studio(self.temp.name, library_root=Path(self.temp.name) / 'library', command_factory=fixture)

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def generate(self, **settings):
        job = self.studio.enqueue({'prompt': 'A dry camera click.', 'seconds': .5, 'seed': 42, **settings})
        self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        return self.studio.items(job_id=job['id'])[0]

    def test_all_formats_store_readable_audio_without_temporary_wavs(self):
        for format, container in [('ogg', 'OGG'), ('wav', 'WAV'), ('mp3', 'MP3')]:
            with self.subTest(format=format):
                item = self.generate(format=format)
                info = sf.info(item['path'])
                self.assertEqual(item['settings']['format'], format)
                self.assertEqual(Path(item['path']).suffix, '.' + format)
                self.assertEqual((info.format, info.samplerate, info.channels, info.frames), (container, 44100, 2, 22050))
                self.assertEqual(self.studio.prepare_drag(item['id'])['format'], format)
        self.assertEqual(len(list(self.studio.audio.glob('*'))), 3)
        self.assertEqual(len(list(self.studio.audio.glob('*.wav'))), 1)

    def test_default_persists_and_explicit_format_overrides_it(self):
        self.assertEqual(self.studio.status()['generation_format'], 'ogg')
        self.studio.set_generation_format('wav')
        self.assertEqual(Path(self.generate()['path']).suffix, '.wav')
        self.assertEqual(Path(self.generate(format='ogg')['path']).suffix, '.ogg')
        self.assertEqual(self.studio.generation_format(), 'wav')
        self.studio.close()
        self.studio = Studio(self.temp.name, library_root=Path(self.temp.name) / 'library', command_factory=fixture)
        self.assertEqual(self.studio.status()['generation_format'], 'wav')

    def test_invalid_or_unavailable_format_does_not_queue_or_change_preference(self):
        for format in ('WAV', 'flac', '', '../wav', True, None, [], {}):
            with self.assertRaises(ValueError):
                self.studio.enqueue({'prompt': 'test', 'format': format})
            with self.assertRaises(ValueError):
                self.studio.set_generation_format(format)
        for format, encoder in [('ogg', 'core.ogg_available'), ('mp3', 'core.ffmpeg_binary')]:
            with patch(encoder, return_value=False):
                with self.assertRaisesRegex(ValueError, 'encoder is unavailable'):
                    self.studio.enqueue({'prompt': 'test', 'format': format})
                with self.assertRaises(ValueError):
                    self.studio.set_generation_format(format)
                # WAV can still be generated when compressed encoders are missing.
                self.assertEqual(self.studio.validate({'prompt': 'test', 'format': 'wav'})['format'], 'wav')
        self.assertEqual(self.studio.rows('SELECT * FROM jobs'), [])
        self.assertEqual(self.studio.generation_format(), 'ogg')

    def test_queue_captures_format_and_regenerate_keeps_it_after_default_changes(self):
        for format in ('wav', 'mp3', 'ogg'):
            self.studio.set_generation_format(format)
            item = self.generate()
            self.studio.set_generation_format('wav' if format != 'wav' else 'ogg')
            job = self.studio.regenerate(item['id'])
            self.assertEqual(job['settings']['format'], format)
            self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
            replaced = self.studio.item(item['id'])
            self.assertNotEqual(replaced['seed'], item['seed'])
            self.assertEqual(Path(replaced['path']).suffix, '.' + format)
            self.assertTrue(Path(item['path']).is_file())

    def test_mp3_crop_drag_and_failed_regenerate_preserve_original(self):
        item = self.generate(format='mp3')
        original = hashlib.sha256(Path(item['path']).read_bytes()).digest()
        self.studio.set_trim(item['id'], {'start': .1, 'end': .4})
        crop = self.studio.media_path(item['id'])
        self.assertEqual((crop.suffix, sf.info(crop).frames), ('.mp3', 13230))
        self.assertEqual(self.studio.prepare_drag(item['id'])['format'], 'mp3')
        before = self.studio.rows('SELECT * FROM items')
        with patch.object(self.studio, 'convert', side_effect=RuntimeError('MP3 encoding failed')):
            job = self.studio.regenerate(item['id'])
            self.assertEqual(wait(self.studio, job['id'])['state'], 'failed')
        self.assertEqual(self.studio.rows('SELECT * FROM items'), before)
        self.assertEqual(hashlib.sha256(Path(item['path']).read_bytes()).digest(), original)
        self.assertEqual(len(list(self.studio.audio.glob('*'))), 1)
        self.assertEqual(list((self.studio.data / 'edits').glob('.fx-trim-*')), [])
        self.assertEqual(wait(self.studio, self.studio.regenerate(item['id'])['id'])['state'], 'completed')
        self.assertEqual(self.studio.media_path(item['id']).suffix, '.mp3')

    def test_agent_pack_mixes_formats_and_omitted_format_uses_app_selection(self):
        self.studio.set_generation_format('wav')
        api = AgentAPI(self.studio, AgentAccess(self.studio.data))
        data = {'request_id': 'formats_pack', 'name': 'Formats', 'assets': [
            {'asset_name': 'lossless', 'prompt': 'click', 'seconds': .5},
            {'asset_name': 'compact', 'prompt': 'click', 'seconds': .5, 'format': 'ogg'},
            {'asset_name': 'mp3', 'prompt': 'click', 'seconds': .5, 'format': 'mp3'}]}
        pack = api.generate(data, pack=True)
        self.studio.set_generation_format('ogg')
        for job in pack['jobs']:
            self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        stored = api.pack(pack['id'])
        self.assertEqual([job['settings']['format'] for job in stored['jobs']], ['wav', 'ogg', 'mp3'])
        self.assertEqual([Path(job['sounds'][0]['original_path']).suffix for job in stored['jobs']], ['.wav', '.ogg', '.mp3'])
        # Retry still returns the original pack even when the app's default changes.
        self.assertEqual(api.generate(data, pack=True)['id'], pack['id'])
