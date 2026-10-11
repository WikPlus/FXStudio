"""Run portable behavior tests with disposable audio/catalogue, no user files.

Synthetic audio here tests trim/export/ranges; it is never a model-quality test
or an application generation result. Native model acceptance is separate.
"""
import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fixture_library(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / 'test.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<hh', *(int(32000 * math.sin(i * .04)),) * 2) for i in range(44100)))
    assets = []
    for i in range(1, 353):
        assets.append({'id': f'SFX{i:04}', 'title_en': f'Test regen plop {i}', 'path': 'test.wav',
            'category': 'Test fixtures', 'duration_seconds': 1,
            'source': {'original_filename': 'test_regen_plop.wav', 'provider': 'FX Studio test suite'},
            'license': {'status': 'documented_bundle' if i <= 347 else 'undocumented',
                        'name': 'Synthetic disposable test fixture', 'document': 'LICENSE.txt'}})
    (folder / 'katalog.json').write_text(json.dumps({'assets': assets}))
    (folder / 'LICENSE.txt').write_text('Synthetic test audio only. Not a bundled production sound library.\n')


def main():
    with tempfile.TemporaryDirectory(prefix='fx-behavior-') as temp:
        library = Path(temp) / 'library'
        fixture_library(library)
        os.environ.update(FX_LIBRARY_ROOT=str(library), FX_AUTO_SETUP='0',
                          HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                          HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
        # Do not link a developer's real HF cache into disposable test data.
        os.environ.pop('FX_MODEL_DIR', None)
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        report=ROOT/'.runtime/behavior-tests.json'
        report.parent.mkdir(exist_ok=True)
        report.write_text(json.dumps({'platform':sys.platform,'tests':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'passed':result.wasSuccessful(),'real_model_generation':False,'personal_library_used':False},indent=2)+'\n')
        if not result.wasSuccessful():
            raise SystemExit(1)


if __name__ == '__main__':
    main()
