"""Writable model storage and tools for source and standalone app launches."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def runtime_kind():
    return 'tflite' if sys.platform == 'win32' else 'mlx'


def runtime_folder():
    if runtime_kind() == 'tflite':
        return ROOT / '.runtime/stable-audio-3-windows/optimized/tflite'
    return ROOT / '.runtime/stable-audio-3/optimized/mlx'


def default_data_dir(platform=None):
    platform = platform or sys.platform
    if platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'FX Studio'
    if platform == 'darwin':
        return Path.home() / 'Library/Application Support/FX Studio'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'FX Studio'


def model_folder():
    return Path(os.environ.get('FX_MODEL_DIR') or runtime_folder() / 'models' / runtime_kind())


def library_folder(data_dir):
    """Optional external catalog; keep machine-specific paths out of releases."""
    if os.environ.get('FX_LIBRARY_ROOT'):
        return Path(os.environ['FX_LIBRARY_ROOT']).expanduser()
    config = Path(data_dir) / 'library-root.txt'
    if config.is_file():
        value = config.read_text(encoding='utf-8').strip()
        if value and Path(value).expanduser().is_absolute():
            return Path(value).expanduser()
    return Path.home() / 'Music/FX Studio Library'


def expose_cached_model(cached, target):
    """Windows normally forbids symlinks; hardlinks work without admin rights."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    try:
        target.symlink_to(cached)
    except OSError:
        try:
            os.link(cached, target)
        except OSError:
            shutil.copy2(cached, target)


def link_cached_models():
    # A standalone bundle is read-only. Reuse only the pinned local cache here;
    # Network downloads belong to the background setup worker.
    if not os.environ.get('FX_MODEL_DIR'):
        return
    from huggingface_hub import try_to_load_from_cache
    from models import MODELS, weight_spec
    folder = model_folder()
    folder.mkdir(parents=True, exist_ok=True)
    for model_id in MODELS:
        spec = weight_spec(model_id)
        for file in spec['files']:
            name, size = file['name'], file['size']
            target = folder / name
            if target.is_file():
                continue
            cached = try_to_load_from_cache(spec['repo'], file['remote'], revision=spec['revision'])
            if not isinstance(cached, str) or not Path(cached).is_file() or Path(cached).stat().st_size != size:
                continue
            expose_cached_model(Path(cached), target)


def ffmpeg_binary():
    bundled = os.environ.get('FX_FFMPEG_PATH')
    if bundled:
        return bundled if Path(bundled).is_file() and os.access(bundled, os.X_OK) else None
    return shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').is_file() else None)
