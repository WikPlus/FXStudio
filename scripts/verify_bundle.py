"""Exercise the packaged runtime from a temporary working directory.

Run only while FX Studio is closed: this performs a real MLX generation, with
temporary history/output, a minimal PATH and no source environment imports.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECK = r'''
import json, os, sys, time
from pathlib import Path
app = Path(sys.argv[1])
sys.path.insert(0, str(app / 'backend'))
import numpy as np
import soundfile as sf
import sentencepiece, huggingface_hub, mlx.core as mx
from mcp import Client, StdioServerParameters
for module in (np, sf, sentencepiece, huggingface_hub, mx):
    assert Path(module.__file__).resolve().is_relative_to(app), module.__file__
assert Path(sys.prefix).resolve().is_relative_to(app)
assert mx.metal.is_available()
from core import Studio
studio = Studio(data_dir=sys.argv[2])
try:
    status = studio.status()
    assert status['packaged'] and status['model']['ready'], status['model']
    assert status['export_mp3']
    started = time.monotonic()
    job_id = studio.enqueue({'model': 'medium', 'prompt': 'One clean professional camera shutter click. Dry isolated mechanical snap with a sharp transient and a very short decay. No room ambience, no music, no voices.', 'seconds': 1, 'steps': 8, 'cfg': 1, 'seed': 52611})['id']
    while True:
        job = next(job for job in studio.status()['jobs'] if job['id'] == job_id)
        if job['state'] not in ('queued', 'running', 'cancelling'): break
        time.sleep(.2)
    assert job['state'] == 'completed', job
    item = studio.items(job_id=job_id)[0]
    samples, rate = sf.read(item['path'], always_2d=True)
    assert rate == 44100 and samples.shape == (44100, 2)
    assert np.isfinite(samples).all() and np.max(np.abs(samples)) > .001
    mp3 = Path(sys.argv[2]) / 'acceptance.mp3'
    studio.convert(Path(item['path']), mp3, 'mp3')
    assert mp3.stat().st_size > 1000
    # Confirm the bundled exporter can decode its MP3 without Homebrew on PATH.
    decoded = Path(sys.argv[2]) / 'decoded.wav'
    studio.convert(mp3, decoded, 'wav')
    decoded_samples, decoded_rate = sf.read(decoded, always_2d=True)
    assert decoded_rate == 44100 and decoded_samples.shape[1] == 2
    assert np.isfinite(decoded_samples).all()
    print(json.dumps({'standalone': True, 'metal': True, 'model': 'medium', 'generation_seconds': round(time.monotonic()-started, 2), 'sample_rate': rate, 'frames': len(samples), 'channels': samples.shape[1], 'peak': round(float(np.max(np.abs(samples))), 5), 'mp3_bytes': mp3.stat().st_size, 'history_is_temporary': True}))
finally:
    studio.close()
'''


def main():
    bundle = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'dist/FX Studio.app').resolve()
    app = bundle / 'Contents/Resources/app'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'FX_', 'DYLD_'))}
    env.update(PATH='/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
               FX_PACKAGED_RUNTIME='1', FX_FFMPEG_PATH=str(app / 'tools/ffmpeg'))
    with tempfile.TemporaryDirectory(prefix='fx-bundle-check-') as temp:
        env['FX_MODEL_DIR'] = str(Path(temp) / 'models/mlx')
        result = subprocess.run([str(app / 'python/bin/python3'), '-I', '-B', '-c', CHECK, str(app), temp],
                                cwd=temp, env=env, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        report = json.loads(result.stdout.splitlines()[-1])
        destination = ROOT / '.runtime/bundle-acceptance.json'
        destination.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
