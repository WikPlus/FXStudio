"""Installed-app project acceptance; adds two real UI-tap variants to Project demo."""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def check():
    from mcp import Client, StdioServerParameters
    import numpy as np
    import soundfile as sf
    app = Path('/Applications/FX Studio.app/Contents/Resources/app')
    python = app / 'python/bin/python3'
    helper = Path.home() / '.codex/skills/fx-studio/scripts/fxstudio.py'
    env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'FX_', 'DYLD_'))}
    env.update(PATH='/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    params = StdioServerParameters(command=str(python), args=['-s', '-B', str(app / 'backend/mcp_server.py')], cwd='/private/tmp', env=env)
    async with Client(params, mode='legacy') as client:
        async def call(name, data=None):
            result = await client.call_tool(name, data or {})
            assert not result.is_error, (name, result.content)
            return result.structured_content
        ready = await call('get_status')
        assert ready['model']['ready']
        assert not any(j['state'] in ('queued', 'running', 'cancelling') for j in ready['jobs']), 'Wait for active user jobs.'
        tools = await client.list_tools()
        assert len(tools.tools) == 20
        project = await call('create_project', {'name': 'Project demo', 'description': 'Local agent generation and sound review.'})
        repeat = await call('create_project', {'name': 'PROJECT DEMO'})
        assert repeat['id'] == project['id']
        request = {'request_id': 'project_acceptance_' + str(time.time_ns()), 'name': 'project_ui_demo',
                   'project_id': project['id'], 'assets': [{'asset_name': 'project_ui_select',
                       'prompt': 'A single soft synthesized UI tap. A rounded midrange tick with a delicate bright attack and a very short, smooth decay. Dry and isolated, suitable for a subtle interface selection.',
                       'seconds': 1, 'variants': 2, 'steps': 8, 'cfg': 1, 'seed': 52613}]}
        started = time.monotonic()
        pack = await call('create_sound_pack', request)
        assert (await call('create_sound_pack', request))['id'] == pack['id']
        print(json.dumps({'project_id': project['id'], 'project': project['name'], 'pack_id': pack['id'], 'job_id': pack['jobs'][0]['id']}), flush=True)
        previous = None
        while True:
            state = await call('get_pack', {'pack_id': pack['id']})
            progress = [(j['state'], j['message']) for j in state['jobs']]
            if progress != previous:
                print(json.dumps({'progress': progress}), flush=True)
                previous = progress
            if state['state'] not in ('queued', 'running'):
                break
            await asyncio.sleep(2)
        assert state['state'] == 'completed', state
        saved = await call('get_project', {'project_id': project['id']})
        sounds = state['jobs'][0]['sounds']
        assert len(sounds) == 2
        assert {s['id'] for s in sounds}.issubset({s['id'] for s in saved['items']})
        assert all(s['projects'][0]['id'] == project['id'] for s in sounds)
        export = await call('export_pack', {'pack_id': pack['id']})
        checks = []
        for sound in export['sounds']:
            samples, rate = sf.read(sound['path'], always_2d=True)
            assert samples.shape == (44100, 2) and rate == 44100
            assert np.isfinite(samples).all() and np.max(np.abs(samples)) > .001
            checks.append({'sound_id': sound['sound_id'], 'frames': len(samples), 'sample_rate': rate, 'peak': float(np.max(np.abs(samples)))})
        manifest = json.loads(Path(export['manifest']).read_text())
        assert manifest['project']['id'] == project['id']
        cli = subprocess.run([str(python), '-s', '-B', str(helper), 'project', project['id']], check=True,
                             capture_output=True, text=True, cwd='/private/tmp', env=env)
        assert json.loads(cli.stdout)['id'] == project['id']
        report = {'project_id': project['id'], 'name': project['name'], 'pack_id': pack['id'],
                  'sound_ids': [s['id'] for s in sounds], 'mcp_tools': len(tools.tools), 'installed_skill_cli': True,
                  'model': 'Stable Audio 3 Medium', 'manifest': export['manifest'], 'audio_checks': checks,
                  'seconds': round(time.monotonic() - started, 2), 'auditioned_by_model': False}
        (ROOT / '.runtime/project-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    asyncio.run(check())
