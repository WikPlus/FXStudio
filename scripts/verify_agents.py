"""Real packaged MCP acceptance. Adds two clearly named demo sounds to history.

Run with FX Studio idle; access must already be enabled in Setup. If the app
is closed the installed skill helper starts it. No fixture audio is used.
"""
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
    bundle = Path(sys.argv[1] if len(sys.argv) > 1 else '/Applications/FX Studio.app')
    app = bundle / 'Contents/Resources/app'
    python = app / 'python/bin/python3'
    helper = Path.home() / '.codex/skills/fx-studio/scripts/fxstudio.py'
    env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'FX_', 'DYLD_'))}
    env.update(PATH='/usr/bin:/bin', DO_NOT_TRACK='1', HF_HUB_DISABLE_TELEMETRY='1')
    started = time.monotonic()
    status = subprocess.run([str(python), '-s', '-B', str(helper), 'status'], check=True,
                            capture_output=True, text=True, cwd='/private/tmp', env=env)
    ready = json.loads(status.stdout)
    assert ready['model']['ready'], ready['model']
    assert not any(job['state'] in ('queued', 'running', 'cancelling') for job in ready['jobs']), 'Wait for active user jobs.'
    print(json.dumps({'standalone_skill_cli': True, 'app_ready': True,
                      'startup_seconds': round(time.monotonic() - started, 2)}), flush=True)
    params = StdioServerParameters(command=str(python), args=['-s', '-B', str(app / 'backend/mcp_server.py')],
                                   cwd='/private/tmp', env=env)
    async with Client(params, mode='legacy') as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 20
        guide = await client.call_tool('get_prompt_guide')
        assert not guide.is_error and 'Camera shutter' in guide.structured_content['guide']
        request = {'request_id': 'real_mcp_' + str(time.time_ns()), 'name': 'agent_video_demo', 'assets': [
            {'asset_name': 'agent_camera_shutter', 'prompt': 'A DSLR camera shutter firing once. A crisp mechanical snap followed by a tiny spring click, with a compact midrange body and a very fast decay. Recorded close to the mechanism in an acoustically dead room.',
             'seconds': 1, 'steps': 8, 'cfg': 1, 'seed': 52611},
            {'asset_name': 'agent_transition_whoosh', 'prompt': 'A single synthesized transition whoosh. A smooth, quick air sweep resolves into a compact soft impact, followed by a fast decay. An airy high end and a restrained low-mid finish, dry and isolated.',
             'seconds': 2, 'steps': 8, 'cfg': 1, 'seed': 52612}]}
        started = time.monotonic()
        created = await client.call_tool('create_sound_pack', request)
        assert not created.is_error, created.content
        pack = created.structured_content
        again = await client.call_tool('create_sound_pack', request)
        assert again.structured_content['id'] == pack['id']
        print(json.dumps({'real_pack': pack['id'], 'job_ids': [j['id'] for j in pack['jobs']], 'duplicate_suppression': True}), flush=True)
        previous = None
        while True:
            result = await client.call_tool('get_pack', {'pack_id': pack['id']})
            assert not result.is_error, result.content
            state = result.structured_content
            signature = [(j['state'], j['message']) for j in state['jobs']]
            if signature != previous:
                print(json.dumps({'jobs': signature}), flush=True)
                previous = signature
            if state['state'] not in ('running', 'queued'):
                break
            await asyncio.sleep(2)
        assert state['state'] == 'completed', state
        whoosh = state['jobs'][1]['sounds'][0]
        trimmed = await client.call_tool('trim_sound', {'sound_id': whoosh['id'], 'start': .05, 'end': 1.95})
        assert not trimmed.is_error, trimmed.content
        exported = await client.call_tool('export_pack', {'pack_id': pack['id']})
        assert not exported.is_error, exported.content
        output = exported.structured_content
        checks = []
        for sound in output['sounds']:
            audio, rate = sf.read(sound['path'], always_2d=True)
            assert rate == 44100 and audio.shape[1] == 2 and np.isfinite(audio).all()
            assert len(audio) == round(sound['duration'] * rate)
            assert np.max(np.abs(audio)) > .001
            if sound['trim']:
                assert (audio[[0, -1]] == 0).all()
            checks.append({'path': sound['path'], 'frames': len(audio), 'sample_rate': rate, 'channels': 2,
                           'peak': round(float(np.max(np.abs(audio))), 5), 'trim': sound['trim']})
        camera = state['jobs'][0]['sounds'][0]
        mp3 = await client.call_tool('export_sound', {'sound_id': camera['id'], 'name': 'camera_' + camera['id'],
                                                    'format': 'mp3', 'folder': 'mcp-demo-mp3'})
        assert not mp3.is_error, mp3.content
        assert Path(mp3.structured_content['path']).is_file()
        final = await client.call_tool('get_status')
        assert not any(j['state'] in ('queued', 'running', 'cancelling') for j in final.structured_content['jobs'])
        report = {'mcp_tools': len(tools.tools), 'legacy_handshake': True, 'standalone_cli': True,
                  'real_model': 'Stable Audio 3 Medium', 'pack_id': pack['id'], 'export': output,
                  'audio_checks': checks, 'mp3': mp3.structured_content,
                  'generation_and_export_seconds': round(time.monotonic() - started, 2),
                  'auditioned_by_model': False}
        (ROOT / '.runtime/agent-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'complete': True, 'model': report['real_model'], 'mcp_tools': len(tools.tools),
                          'seconds': report['generation_and_export_seconds'], 'manifest': output['manifest'],
                          'audio_checks': checks, 'mp3_path': mp3.structured_content['path']}), flush=True)


if __name__ == '__main__':
    asyncio.run(check())
