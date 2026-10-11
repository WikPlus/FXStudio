"""Persistent projects, real generation associations and nondestructive reuse."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from test_core import Studio, fixture, wait
from agent_access import AgentAccess
from agent_api import AgentAPI


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.studio = Studio(self.temp.name, command_factory=fixture)
        self.api = AgentAPI(self.studio, AgentAccess(self.studio.data))

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def test_unicode_names_retries_and_rename_keep_identity(self):
        one = self.studio.create_project({'name': '  Wald – Spiel  ', 'description': 'Wooden foley'})
        again = self.studio.create_project({'name': 'WALD – SPIEL', 'description': 'Do not overwrite'})
        self.assertEqual(one['id'], again['id'])
        self.assertFalse(again['created_new'])
        self.assertEqual(again['description'], 'Wooden foley')
        self.assertEqual(len(self.studio.projects('Wald foley')), 1)
        two = self.studio.create_project({'name': 'Second game'})
        with self.assertRaises(ValueError):
            self.studio.update_project(two['id'], {'name': 'wald – spiel'})
        changed = self.studio.update_project(one['id'], {'name': 'Forest game'})
        self.assertEqual(changed['id'], one['id'])
        for raw in ({'name': ''}, {'name': 'x' * 81}, {'name': 'a\nb'}, {'name': 'x', 'description': []}):
            with self.assertRaises(ValueError):
                self.studio.create_project(raw)
        self.assertEqual(len(self.studio.projects()), 2)

    def test_project_pack_all_variants_isolation_and_manifest(self):
        project = self.studio.create_project({'name': 'Game'})
        other = self.studio.create_project({'name': 'Video'})
        pack = self.api.generate({'request_id': 'game1', 'name': 'game_assets', 'project_id': project['id'],
                                 'assets': [{'asset_name': 'jump', 'prompt': 'test', 'seconds': .5, 'variants': 2},
                                            {'asset_name': 'land', 'prompt': 'test', 'seconds': .5}]}, pack=True)
        for job in pack['jobs']:
            wait(self.studio, job['id'])
        plain = self.studio.enqueue({'prompt': 'unassigned', 'seconds': .5})
        wait(self.studio, plain['id'])
        self.assertEqual(len(self.studio.project_items(project['id'])), 3)
        self.assertEqual(self.studio.project_items(other['id']), [])
        self.assertEqual(len(self.studio.items()), 4)
        self.assertEqual(len(self.studio.project_items(project['id'], 'land')), 1)
        self.assertEqual({j['settings']['project_id'] for j in self.studio.project_jobs(project['id'])}, {project['id']})
        result = self.api.get('/projects/' + project['id'], {'offset': ['1'], 'limit': ['1']})
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['active_jobs'], 0)
        exported = self.api.export_pack({'pack_id': pack['id']})
        manifest = json.loads(Path(exported['manifest']).read_text())
        self.assertEqual(manifest['project']['id'], project['id'])
        self.assertTrue(all(s['projects'][0]['id'] == project['id'] for s in manifest['sounds']))

    def test_invalid_pack_project_has_no_partial_queue_or_memberships(self):
        project = self.studio.create_project({'name': 'One'})
        other = self.studio.create_project({'name': 'Two'})
        for target, asset_target, error in [('missing', None, KeyError), (project['id'], other['id'], ValueError)]:
            with self.assertRaises(error):
                self.api.generate({'request_id': 'invalid', 'name': 'bad', 'project_id': target,
                                   'assets': [{'asset_name': 'one', 'prompt': 'test', 'seconds': .5},
                                              {'asset_name': 'two', 'prompt': 'test', 'project_id': asset_target}]}, pack=True)
        with self.assertRaises(KeyError):
            self.studio.enqueue_many([{'prompt': 'ok', 'seconds': .5}, {'prompt': 'bad', 'project_id': 'missing'}])
        self.assertEqual(self.studio.rows('SELECT * FROM jobs'), [])
        self.assertEqual(self.studio.rows('SELECT * FROM project_sounds'), [])
        self.assertEqual(self.studio.rows('SELECT * FROM agent_requests'), [])

    def test_membership_shares_crop_and_favorite_without_copy_or_deletion(self):
        one = self.studio.create_project({'name': 'One'})
        two = self.studio.create_project({'name': 'Two'})
        job = self.studio.enqueue({'prompt': 'test', 'seconds': .5, 'project_id': one['id']})
        wait(self.studio, job['id'])
        sound = self.studio.project_items(one['id'])[0]
        original = Path(sound['path'])
        self.studio.set_project_sound(two['id'], sound['id'])
        self.studio.set_project_sound(two['id'], sound['id'])
        self.studio.set_trim(sound['id'], {'start': .1, 'end': .3})
        self.studio.favorite(sound['id'], True)
        self.assertEqual(self.studio.project_items(two['id'])[0]['trim']['start'], .1)
        self.assertTrue(self.studio.project_items(one['id'])[0]['favorite'])
        self.assertEqual(len(list(self.studio.audio.glob('*.wav'))), 1)
        library = self.studio.item('SFX0001')
        self.studio.set_project_sound(two['id'], library['id'])
        self.assertEqual(self.studio.project_items(two['id'])[0]['license'], library['license'])
        self.studio.set_project_sound(one['id'], sound['id'], False)
        self.assertEqual(self.studio.project_items(one['id']), [])
        self.assertTrue(original.is_file())
        self.assertEqual(len(self.studio.project_items(two['id'])), 2)
        with self.assertRaises(KeyError):
            self.studio.set_project_sound(one['id'], 'missing')
        with self.assertRaises(ValueError):
            self.studio.set_project_sound(one['id'], sound['id'], 'false')
        self.studio.close()
        self.studio = Studio(self.temp.name, command_factory=fixture)
        self.assertEqual(len(self.studio.project_items(two['id'])), 2)
        self.assertAlmostEqual(self.studio.project_items(two['id'])[1]['duration'], .2)
        original.unlink()
        self.assertTrue(self.studio.project_items(two['id'])[1]['missing'])

    def test_partial_cancel_and_failure_keep_project_usable(self):
        project = self.studio.create_project({'name': 'Cancel test'})
        def partial(settings, seed, target, reference):
            return fixture({**settings, 'prompt': 'test' if seed == 42 else 'stubborn'}, seed, target, reference)
        self.studio.command_factory = partial
        job = self.studio.enqueue({'prompt': 'test', 'seconds': .5, 'seed': 42, 'variants': 2, 'project_id': project['id']})
        deadline = time.monotonic() + 8
        while not list(self.studio.audio.glob('*.child')) and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertEqual(len(self.studio.project_items(project['id'])), 1)
        self.studio.cancel(job['id'])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'cancelled')
        self.studio.command_factory = fixture
        failed = self.studio.enqueue({'prompt': 'failure', 'seconds': .5, 'project_id': project['id']})
        self.assertEqual(wait(self.studio, failed['id'])['state'], 'failed')
        self.assertIn('process failure', self.studio.project_jobs(project['id'])[0]['error'])
        good = self.studio.enqueue({'prompt': 'test', 'seconds': .5, 'project_id': project['id']})
        self.assertEqual(wait(self.studio, good['id'])['state'], 'completed')
        self.assertEqual(self.studio.project(project['id'])['sound_count'], 2)

    def test_upgrade_existing_database_preserves_history_trim_and_favorites(self):
        job = self.studio.enqueue({'prompt': 'old history', 'seconds': .5})
        wait(self.studio, job['id'])
        item = self.studio.items()[0]
        self.studio.favorite(item['id'], True)
        self.studio.set_trim(item['id'], {'start': .1, 'end': .3})
        self.studio.close()
        with sqlite3.connect(self.studio.data / 'studio.sqlite') as db:
            db.executescript('DROP TABLE project_sounds; DROP TABLE projects;')
        self.studio = Studio(self.temp.name, command_factory=fixture)
        self.assertEqual(self.studio.projects(), [])
        retained = self.studio.item(item['id'])
        self.assertTrue(retained['favorite'])
        self.assertEqual(retained['trim']['start'], .1)
        self.assertEqual(retained['prompt'], 'old history')
        project = self.studio.create_project({'name': 'Existing work'})
        self.studio.set_project_sound(project['id'], item['id'])
        self.assertEqual(self.studio.project(project['id'])['sound_count'], 1)
