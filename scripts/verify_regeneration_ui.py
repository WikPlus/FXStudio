"""Exercise the real UI with disposable audio, never the user's catalogue."""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'tests')]
from core import Studio
from run_behavior_tests import fixture_library
from processes import process_options, terminate_tree

with tempfile.TemporaryDirectory(prefix='fx-regeneration-ui-') as temp:
    folder = Path(temp)
    library = folder / 'library'
    fixture_library(library)
    os.environ['FX_LIBRARY_ROOT'] = str(library)
    studio = Studio(data_dir=folder, command_factory=lambda *args: [])
    project = studio.create_project({'name': 'Regeneration UI test'})
    settings = studio.validate({'prompt': 'A camera shutter clicking once.', 'seconds': 1, 'seed': 42, 'project_id': project['id']})
    for i in range(45):
        sound_id = f'{i:012x}'
        studio.execute('INSERT INTO items(id,job_id,title,prompt,settings,seed,path,created,duration,variant) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (sound_id, 'test-original', f'Test sound {i+1}', settings['prompt'], json.dumps(settings), 42, str(library / 'test.wav'), i, 1, 1))
        studio.set_project_sound(project['id'], sound_id)
    studio.close()
    (folder / 'ready').write_text('Synthetic UI test; no model download.')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    token = secrets.token_hex(24)
    output = Path(os.environ.get('FX_UI_TEST_OUTPUT', ROOT / '.runtime/regeneration'))
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'FX_DATA_DIR': str(folder), 'FX_PORT': str(port), 'FX_SESSION_TOKEN': token,
           'FX_AUTO_SETUP': '0', 'FX_UI_TEST_URL': base, 'FX_UI_TEST_OUTPUT': str(output),
           'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    with (output / 'ui-service.log').open('w') as log:
        service = subprocess.Popen([sys.executable, str(ROOT / 'tests/http_service_fixture.py')], env=env, stdout=log, stderr=log, **process_options())
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(urllib.request.Request(base + '/api/status', headers={'X-FX-Token': token}), timeout=1).close()
                    break
                except OSError:
                    time.sleep(.05)
            executable = ROOT / 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron'
            subprocess.run([str(executable), str(ROOT / 'tests/regenerate_ui.cjs')], env=env, check=True, timeout=60)
        finally:
            terminate_tree(service)
            service.wait(timeout=10)
