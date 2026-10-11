import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import runtime_paths


class PackagedStorageTests(unittest.TestCase):
    def test_cache_reuse_and_broken_link_repair_without_download(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'Application Support/models'
            cache = Path(temp) / 'cached.npz'
            cache.write_bytes(b'cached weights')
            folder.mkdir(parents=True)
            (folder / 'ready.npz').write_bytes(cache.read_bytes())
            (folder / 'link.npz').symlink_to(Path(temp) / 'no-longer-present')
            files = [('ready.npz', 14), ('link.npz', 14), ('missing.npz', 14), ('incomplete.npz', 15)]
            def cached(repo, name, revision):
                return None if name.endswith('missing.npz') else str(cache)
            with patch.dict(os.environ, {'FX_MODEL_DIR': str(folder)}), \
                 patch('runtime_paths.runtime_kind', return_value='mlx'), \
                 patch('models.MODELS', {'medium': {'files': files}}), \
                 patch('huggingface_hub.try_to_load_from_cache', side_effect=cached) as lookup, \
                 patch('huggingface_hub.hf_hub_download', side_effect=AssertionError('Unexpected network download')):
                runtime_paths.link_cached_models()
                self.assertEqual(runtime_paths.model_folder(), folder)
                self.assertFalse((folder / 'ready.npz').is_symlink())
                self.assertEqual((folder / 'link.npz').resolve(), cache.resolve())
                self.assertFalse((folder / 'missing.npz').exists())
                self.assertFalse((folder / 'incomplete.npz').exists())
                self.assertEqual(lookup.call_count, 3)

    def test_missing_bundled_exporter_does_not_use_host_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp, patch('runtime_paths.shutil.which') as which:
            binary = Path(temp) / 'ffmpeg'
            with patch.dict(os.environ, {'FX_FFMPEG_PATH': str(binary)}):
                self.assertIsNone(runtime_paths.ffmpeg_binary())
                binary.write_text('#!/bin/sh\nexit 0\n')
                binary.chmod(0o644)
                if os.name != 'nt':
                    self.assertIsNone(runtime_paths.ffmpeg_binary())
                binary.chmod(0o755)
                self.assertEqual(runtime_paths.ffmpeg_binary(), str(binary))
                which.assert_not_called()


class LibraryConfigurationTests(unittest.TestCase):
    def test_saved_local_path_and_environment_override(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            data = Path(temp)
            external = data / 'external library'
            (data / 'library-root.txt').write_text(str(external))
            self.assertEqual(runtime_paths.library_folder(data), external)
            with patch.dict(os.environ, {'FX_LIBRARY_ROOT': str(data / 'override')}):
                self.assertEqual(runtime_paths.library_folder(data), data / 'override')

    def test_invalid_relative_config_uses_portable_default(self):
        home_environment = {name: os.environ[name] for name in ('USERPROFILE', 'HOMEDRIVE', 'HOMEPATH') if name in os.environ}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, home_environment, clear=True):
            (Path(temp) / 'library-root.txt').write_text('../../personal')
            self.assertEqual(runtime_paths.library_folder(temp), Path.home() / 'Music/FX Studio Library')
