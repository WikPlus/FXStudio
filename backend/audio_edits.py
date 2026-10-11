"""Sample-aligned, non-destructive trims with short boundary fades."""
import math
import os
import secrets
from pathlib import Path

FADE_MS = 5
MIN_SECONDS = .01


def trim_bounds(source, raw):
    import soundfile as sf
    info = sf.info(str(source))
    duration = info.frames / info.samplerate
    values = []
    for key in ('start', 'end'):
        value = raw.get(key)
        if isinstance(value, bool):
            raise ValueError('Trim positions must be finite numbers.')
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError('Trim positions must be finite numbers.') from None
        if not math.isfinite(value):
            raise ValueError('Trim positions must be finite numbers.')
        values.append(value)
    start, end = values
    if start < 0 or end > duration + 1 / info.samplerate or end <= start:
        raise ValueError('Choose a trim range inside the original sound.')
    first, last = round(start * info.samplerate), min(info.frames, round(end * info.samplerate))
    if last - first < min(info.frames, math.ceil(MIN_SECONDS * info.samplerate)):
        raise ValueError('Keep at least 10 ms of audio.')
    return {'start': first / info.samplerate, 'end': last / info.samplerate,
            'source_duration': duration, 'fade_ms': FADE_MS}


def render_trim(source, target, trim):
    import numpy as np
    import soundfile as sf
    target = Path(target)
    partial = target.with_name(target.name + '.' + secrets.token_hex(6) + '.partial')
    try:
        with sf.SoundFile(str(source)) as reader:
            first = round(trim['start'] * reader.samplerate)
            last = round(trim['end'] * reader.samplerate)
            if not 0 <= first < last <= len(reader):
                raise ValueError('The source changed. Reset the trim and try again.')
            count = last - first
            fade = min(max(2, round(reader.samplerate * FADE_MS / 1000)), count // 2)
            subtype = reader.subtype if reader.subtype in ('PCM_16', 'PCM_24', 'PCM_32', 'FLOAT', 'DOUBLE') else 'PCM_16'
            reader.seek(first)
            with sf.SoundFile(str(partial), 'w', samplerate=reader.samplerate,
                              channels=reader.channels, format='WAV', subtype=subtype) as writer:
                offset = 0
                while offset < count:
                    samples = reader.read(min(65536, count - offset), dtype='float64', always_2d=True)
                    if not len(samples):
                        raise ValueError('The source ended before the trim range.')
                    if not np.isfinite(samples).all():
                        raise ValueError('The source contains invalid audio samples.')
                    indexes = np.arange(offset, offset + len(samples))
                    gain = np.minimum(1, np.minimum(indexes, count - 1 - indexes) / max(1, fade - 1))
                    writer.write(samples * gain[:, None])
                    offset += len(samples)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
