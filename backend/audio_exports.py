"""Streamed OGG encoding for generated sounds and delivery files."""
from functools import lru_cache
import os
from pathlib import Path
import tempfile


@lru_cache(maxsize=1)
def ogg_available():
    try:
        import soundfile as sf
        return sf.check_format('OGG', 'VORBIS')
    except (ImportError, OSError, RuntimeError):
        return False


def export_ogg(source, target):
    import soundfile as sf
    if not ogg_available():
        raise ValueError('OGG Vorbis export is unavailable. Reinstall FX Studio to restore the bundled encoder.')
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError('Export to a different file to preserve the original audio.')
    # Render beside the target, then replace only a complete, readable file.
    with tempfile.TemporaryDirectory(prefix='.fx-ogg-', dir=target.parent) as temp:
        rendered = Path(temp) / 'sound.ogg'
        with sf.SoundFile(source) as original:
            if not original.frames:
                raise ValueError('The original audio file is empty.')
            with sf.SoundFile(rendered, 'w', samplerate=original.samplerate,
                              channels=original.channels, format='OGG', subtype='VORBIS',
                              compression_level=.5) as output:
                # Vorbis VBR quality 5. Stream blocks to bound memory for long library clips.
                for block in original.blocks(blocksize=65536, dtype='float32', always_2d=True):
                    output.write(block)
            info = sf.info(rendered)
            if (info.frames, info.samplerate, info.channels) != (original.frames, original.samplerate, original.channels):
                raise ValueError('The OGG export is incomplete. The original audio is unchanged.')
        os.replace(rendered, target)
