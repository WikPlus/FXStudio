import asyncio
import http.client
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from core import Studio
from agent_access import AgentAccess
from agent_api import AgentAPI, Conflict
from test_core import fixture, wait


class AgentOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.studio = Studio(self.temp.name, command_factory=fixture)
        self.access = AgentAccess(self.studio.data)
        self.api = AgentAPI(self.studio, self.access)

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def asset(self, name='camera', **values):
        return {'prompt': 'test', 'seconds': .5, 'seed': 42, 'asset_name': name, **values}

    def create(self, request='take1', **values):
        return self.api.generate({'request_id': request, 'settings': self.asset(**values)})

    def test_opt_in_private_key_rotation_and_persistence(self):
        self.assertFalse(self.access.authorized('Bearer ' + self.access.config['token']))
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(self.access.path.stat().st_mode), 0o600)
        self.access.configure({'enabled': True}, self.studio)
        old = self.access.config['token']
        self.assertTrue(self.access.authorized('Bearer ' + old))
        self.assertNotIn('token', self.access.status())
        self.access.configure({'rotate': True}, self.studio)
        self.assertFalse(self.access.authorized('Bearer ' + old))
        new = AgentAccess(self.studio.data)
        self.assertTrue(new.authorized('Bearer ' + self.access.config['token']))
        self.access.configure({'enabled': False}, self.studio)
        self.assertFalse(self.access.authorized('Bearer ' + self.access.config['token']))

    def test_atomic_pack_and_capacity_and_duplicate_names(self):
        for assets in ([self.asset(), self.asset('bad', seconds=99)], [self.asset(), self.asset()], [self.asset()] * 9):
            with self.assertRaises(ValueError):
                self.api.generate({'request_id': 'bad', 'name': 'pack', 'assets': assets}, pack=True)
        self.assertEqual(self.studio.rows('SELECT * FROM jobs'), [])
        with self.studio.lock:
            self.studio.enqueue_many([self.asset(str(i)) for i in range(7)])
            before = len(self.studio.rows('SELECT * FROM jobs'))
            with self.assertRaises(ValueError):
                self.api.generate({'request_id': 'full', 'name': 'pack', 'assets': [self.asset(), self.asset('two')]}, pack=True)
            self.assertEqual(len(self.studio.rows('SELECT * FROM jobs')), before)
            self.assertEqual(self.studio.rows('SELECT * FROM agent_packs'), [])

    def test_idempotency_survives_restart_and_settings_conflict(self):
        one = self.create()
        self.assertEqual(self.create(), one)
        with self.assertRaises(Conflict):
            self.create(seconds=1)
        wait(self.studio, one['id'])
        self.studio.close()
        self.studio = Studio(self.temp.name, command_factory=fixture)
        self.api = AgentAPI(self.studio, self.access)
        self.assertEqual(self.create(), one)
        self.assertEqual(len(self.studio.rows('SELECT * FROM jobs')), 1)

    def test_failed_pack_cancel_recovery_and_complete_export(self):
        bad = self.api.generate({'request_id': 'bad', 'name': 'badpack', 'assets': [self.asset('bad', prompt='failure'), self.asset('ok')]}, pack=True)
        for job in bad['jobs']:
            wait(self.studio, job['id'])
        self.assertEqual(self.api.pack(bad['id'])['state'], 'incomplete')
        self.assertIn('process failure', self.api.pack(bad['id'])['jobs'][0]['error'])
        with self.assertRaises(ValueError):
            self.api.export_pack({'pack_id': bad['id']})
        one = self.create('cancel', prompt='stubborn')
        self.studio.cancel(one['id'])
        self.assertEqual(wait(self.studio, one['id'])['state'], 'cancelled')
        pack = self.api.generate({'request_id': 'good', 'name': 'editor', 'assets': [self.asset('shutter', variants=2), self.asset('whoosh')]}, pack=True)
        for job in pack['jobs']:
            wait(self.studio, job['id'])
        result = self.api.pack(pack['id'])
        self.assertEqual(result['state'], 'completed')
        sound = result['jobs'][0]['sounds'][0]
        self.api.post('/trim', {'sound_id': sound['id'], 'start': .1, 'end': .3})
        out = self.api.export_pack({'pack_id': pack['id']})
        self.assertEqual(len(out['sounds']), 3)
        import soundfile as sf
        audio, rate = sf.read(out['sounds'][0]['path'], always_2d=True)
        self.assertEqual(len(audio), round(.2 * rate))
        self.assertLess(abs(audio[[0, -1]]).max(), .01)
        manifest = json.loads(Path(out['manifest']).read_text())
        self.assertEqual(manifest['sounds'][0]['seed'], 42)
        self.assertIn('Community License', manifest['sounds'][0]['license']['name'])
        ogg_pack = self.api.export_pack({'pack_id': pack['id'], 'format': 'ogg', 'folder': 'ogg'})
        ogg_manifest = json.loads(Path(ogg_pack['manifest']).read_text())
        self.assertEqual(len(ogg_manifest['sounds']), 3)
        self.assertTrue(all(sound['format'] == 'ogg' and sf.info(sound['path']).subtype == 'VORBIS' for sound in ogg_manifest['sounds']))
        self.assertEqual(sf.info(ogg_pack['sounds'][0]['path']).frames, round(.2 * 44100))
        with self.assertRaises(FileExistsError):
            self.api.export_pack({'pack_id': pack['id']})
        trimmed = self.api.sound(sound['id'])
        self.assertNotEqual(trimmed['original_path'], trimmed['audio_path'])
        self.assertEqual(self.api.job(pack['jobs'][0]['id'])['settings']['origin'], 'agent')

    def test_export_boundaries_no_overwrite_and_library_provenance(self):
        for folder in ('../escape', '/tmp', 'C:/tmp', 'nested/../../escape', 'folder\\escape'):
            with self.assertRaises(ValueError):
                self.api.export_directory(folder)
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        root = Path(self.access.config['export_root'])
        root.mkdir()
        (root / 'escape').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.api.export_directory('escape')
        with self.assertRaises(ValueError):
            self.access.configure({'export_root': str(self.studio.library_root)}, self.studio)
        original = self.studio.item('SFX0001')
        out = self.api.export_sound({'sound_id': 'SFX0001', 'name': 'library_copy'})
        self.assertEqual(out['license'], original['license'])
        self.assertEqual(out['source'], original['source'])
        size = Path(out['path']).stat().st_size
        with self.assertRaises(FileExistsError):
            self.api.export_sound({'sound_id': 'SFX0001', 'name': 'library_copy'})
        self.assertEqual(Path(out['path']).stat().st_size, size)
        for name in ('../x', 'NUL', 'CON', 'with space'):
            with self.assertRaises(ValueError):
                self.api.export_sound({'sound_id': 'SFX0001', 'name': name})

    def test_long_names_export_uniquely_and_missing_audio_retains_job(self):
        pack = self.api.generate({'request_id': 'long', 'name': 'long_names',
                                 'assets': [self.asset('a' * 79 + 'x'), self.asset('a' * 79 + 'y')]}, pack=True)
        for job in pack['jobs']:
            wait(self.studio, job['id'])
        out = self.api.export_pack({'pack_id': pack['id']})
        self.assertEqual(len({sound['path'] for sound in out['sounds']}), 2)
        sound = self.api.job(pack['jobs'][0]['id'])['sounds'][0]
        Path(sound['original_path']).unlink()
        saved = self.api.job(pack['jobs'][0]['id'])
        self.assertEqual(saved['state'], 'completed')
        self.assertIsNone(saved['sounds'][0]['audio_path'])
        with self.assertRaisesRegex(ValueError, 'original audio file is missing'):
            self.api.export_sound({'sound_id': sound['id']})

    def test_agent_kit_contains_portable_skill_and_no_credentials(self):
        from agent_kit import save_kit
        import zipfile
        target = Path(self.temp.name) / 'kit.zip'
        save_kit(target)
        with zipfile.ZipFile(target) as kit:
            self.assertIn('fx-studio/SKILL.md', kit.namelist())
            self.assertIn('fx-studio/scripts/fxstudio.py', kit.namelist())
            self.assertIn('codex-mcp.toml', kit.namelist())
            for name in kit.namelist():
                self.assertNotIn(self.access.config['token'].encode(), kit.read(name))


class AgentProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.token = secrets.token_hex(20)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.env = {**os.environ, 'FX_PORT': str(cls.port), 'FX_DATA_DIR': cls.temp.name,
                   'FX_SESSION_TOKEN': cls.token, 'FX_AUTO_SETUP': '0', 'FX_AGENT_NO_LAUNCH': '1'}
        cls.service = subprocess.Popen([sys.executable, str(ROOT / 'tests/agent_service_fixture.py')], env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                if cls.request('GET', '/api/status')[0] == 200:
                    break
            except OSError:
                time.sleep(.05)
        else:
            raise AssertionError('Agent fixture service not ready.')
        cls.agent_token = json.loads((Path(cls.temp.name) / 'agent-access.json').read_text())['token']

    @classmethod
    def tearDownClass(cls):
        cls.service.terminate()
        cls.service.wait(timeout=8)
        cls.temp.cleanup()

    @classmethod
    def request(cls, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=5)
        values = {'X-FX-Token': cls.token, **(headers or {})}
        body = None if data is None else json.dumps(data)
        if body is not None:
            values['Content-Type'] = 'application/json'
        conn.request(method, path, body, values)
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()))
        conn.close()
        return result

    def test_auth_namespaces_origin_host_and_disabled_access(self):
        self.request('POST', '/api/agents', {'enabled': False})
        agent = {'X-FX-Token': '', 'Authorization': 'Bearer ' + self.agent_token}
        self.assertEqual(self.request('GET', '/agent/v1/status', headers=agent)[0], 401)
        self.request('POST', '/api/agents', {'enabled': True})
        self.assertEqual(self.request('GET', '/agent/v1/status', headers=agent)[0], 200)
        self.assertEqual(self.request('GET', '/agent/v1/status')[0], 401)
        self.assertEqual(self.request('GET', '/api/agent-credentials', headers=agent)[0], 401)
        self.assertEqual(self.request('POST', '/api/agents', {'enabled': False}, headers=agent)[0], 401)
        self.assertEqual(self.request('GET', '/agent/v1/status', headers={**agent, 'Host': 'bad.test'})[0], 403)
        self.assertEqual(self.request('POST', '/agent/v1/generate', {}, headers={**agent, 'Origin': 'https://bad.test'})[0], 403)
        self.assertNotIn(self.agent_token, json.dumps(self.request('GET', '/api/status')[1]))

    def test_real_mcp_stdio_and_cli_pack_trim_export(self):
        self.request('POST', '/api/agents', {'enabled': True})
        async def run():
            from mcp import Client, StdioServerParameters
            params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'backend/mcp_server.py')], env=self.env, cwd=self.temp.name)
            async with Client(params) as client:
                tools = await client.list_tools()
                names = [t.name for t in tools.tools]
                self.assertIn('create_sound_pack', names)
                generation_tool = next(t for t in tools.tools if t.name == 'generate_sound')
                self.assertIn('format', generation_tool.input_schema['properties'])
                self.assertEqual(len(names), 22)
                self.assertTrue(next(t for t in tools.tools if t.name == 'delete_project').annotations.destructive_hint)
                disposable = (await client.call_tool('create_project', {'name': 'Disposable MCP project'})).structured_content
                preview = await client.call_tool('preview_project_deletion', {'project_id': disposable['id']})
                self.assertFalse(preview.is_error)
                blocked_delete = await client.call_tool('delete_project', {'project_id': disposable['id'], 'confirm_name': 'wrong'})
                self.assertTrue(blocked_delete.is_error)
                deleted = await client.call_tool('delete_project', {'project_id': disposable['id'], 'confirm_name': disposable['name'], 'revision': preview.structured_content['revision']})
                self.assertTrue(deleted.structured_content['deleted'])
                guide = await client.call_tool('get_prompt_guide')
                self.assertFalse(guide.is_error)
                self.assertIn('Camera shutter', str(guide.structured_content))
                project = (await client.call_tool('create_project', {'name': 'MCP game', 'description': 'Game sound review'})).structured_content
                repeated = (await client.call_tool('create_project', {'name': 'mcp game'})).structured_content
                self.assertEqual(repeated['id'], project['id'])
                invalid = await client.call_tool('generate_sound', {'request_id': 'invalid', 'prompt': 'test', 'seconds': 99})
                self.assertTrue(invalid.is_error)
                self.assertIn('seconds must be', str(invalid.content))
                result = await client.call_tool('create_sound_pack', {'request_id': 'mcp_pack1', 'name': 'mcp_editor', 'project_id': project['id'],
                    'assets': [{'asset_name': 'click', 'prompt': 'test', 'seconds': .5, 'seed': 42}, {'asset_name': 'swish', 'prompt': 'test', 'seconds': .5}]})
                self.assertFalse(result.is_error)
                pack = result.structured_content
                # The server's dict returns as direct structured output.
                self.assertIn('id', pack)
                duplicate = await client.call_tool('create_sound_pack', {'request_id': 'mcp_pack1', 'name': 'mcp_editor', 'project_id': project['id'],
                    'assets': [{'asset_name': 'click', 'prompt': 'test', 'seconds': .5, 'seed': 42}, {'asset_name': 'swish', 'prompt': 'test', 'seconds': .5}]})
                self.assertEqual(duplicate.structured_content['id'], pack['id'])
                for _ in range(100):
                    state = (await client.call_tool('get_pack', {'pack_id': pack['id']})).structured_content
                    if state['state'] == 'completed':
                        break
                    await asyncio.sleep(.05)
                self.assertEqual(state['state'], 'completed')
                saved_project = (await client.call_tool('get_project', {'project_id': project['id']})).structured_content
                self.assertEqual(saved_project['total'], 2)
                updated = await client.call_tool('update_project', {'project_id': project['id'], 'name': 'Renamed MCP game'})
                self.assertEqual(updated.structured_content['sound_count'], 2)
                sound = state['jobs'][0]['sounds'][0]
                removed = await client.call_tool('set_project_sound', {'project_id': project['id'], 'sound_id': sound['id'], 'included': False})
                self.assertFalse(removed.structured_content['included'])
                await client.call_tool('set_project_sound', {'project_id': project['id'], 'sound_id': sound['id']})
                trimmed = await client.call_tool('trim_sound', {'sound_id': sound['id'], 'start': .1, 'end': .3})
                self.assertAlmostEqual(trimmed.structured_content['duration'], .2)
                exported = await client.call_tool('export_pack', {'pack_id': pack['id']})
                self.assertFalse(exported.is_error)
                self.assertTrue(Path(exported.structured_content['manifest']).is_file())
                self.assertEqual(exported.structured_content['sounds'][0]['format'], 'ogg')
                import soundfile as sf
                self.assertEqual(sf.info(exported.structured_content['sounds'][0]['path']).subtype, 'VORBIS')
                wav = await client.call_tool('export_sound', {'sound_id': sound['id'], 'name': 'wav_delivery', 'format': 'wav'})
                self.assertFalse(wav.is_error)
                self.assertEqual(sf.info(wav.structured_content['path']).format, 'WAV')
                for explicit, expected in [(True, 'wav'), (False, 'mp3')]:
                    self.request('POST', '/api/generation-format', {'format': 'mp3'})
                    arguments = {'request_id': 'mcp_format_' + expected, 'prompt': 'test', 'seconds': .5}
                    if explicit:
                        arguments['format'] = expected
                    generated = await client.call_tool('generate_sound', arguments)
                    self.assertFalse(generated.is_error)
                    self.assertEqual(generated.structured_content['settings']['format'], expected)
                    for _ in range(100):
                        format_job = (await client.call_tool('get_job', {'job_id': generated.structured_content['id']})).structured_content
                        if format_job['state'] == 'completed':
                            break
                        await asyncio.sleep(.04)
                    self.assertEqual(format_job['state'], 'completed')
                    self.assertEqual(sf.info(format_job['sounds'][0]['original_path']).format, expected.upper())
                self.request('POST', '/api/generation-format', {'format': 'ogg'})
                self.request('POST', '/api/agents', {'enabled': False})
                blocked = await client.call_tool('get_status')
                self.assertTrue(blocked.is_error)
                self.assertIn('enable access', str(blocked.content))
                self.request('POST', '/api/agents', {'enabled': True})
                ready = await client.call_tool('get_status')
                self.assertFalse(ready.is_error)
            # Existing MCP clients use the initialize/initialized handshake.
            async with Client(params, mode='legacy') as legacy:
                tools = await legacy.list_tools()
                self.assertEqual(len(tools.tools), 22)
                ready = await legacy.call_tool('get_status')
                self.assertFalse(ready.is_error)
                self.assertEqual(ready.structured_content['service'], 'fx-studio')
        asyncio.run(run())
        result = subprocess.run([sys.executable, str(ROOT / 'backend/agent_cli.py'), 'history', '{"q":"click"}'], env=self.env, cwd=self.temp.name, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(json.loads(result.stdout)['total'], 1)


if __name__ == '__main__':
    unittest.main()
