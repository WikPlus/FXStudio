import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from test_core import Studio, fixture, wait


class RegenerateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.studio = Studio(data_dir=self.temp.name, command_factory=fixture)
        self.project = self.studio.create_project({'name': 'Game'})
        self.original_job = self.studio.enqueue({'prompt': 'A camera clicking once.', 'seconds': .5,
                                               'seed': 42, 'project_id': self.project['id']})['id']
        wait(self.studio, self.original_job)
        self.sound = self.studio.items()[0]

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def snapshot(self):
        return self.studio.rows('SELECT * FROM items'), self.studio.rows('SELECT * FROM sound_trims')

    def test_replace_keeps_identity_order_projects_favorite_crop_and_job_filter(self):
        other = self.studio.create_project({'name': 'Edit'})
        self.studio.set_project_sound(other['id'], self.sound['id'])
        self.studio.favorite(self.sound['id'], True)
        self.studio.set_trim(self.sound['id'], {'start': .1, 'end': .3})
        before = self.studio.item(self.sound['id'])
        drag = self.studio.prepare_drag(before['id'])['path']
        membership = self.studio.rows('SELECT * FROM project_sounds')
        job = self.studio.regenerate(before['id'])
        self.assertNotEqual(job['settings']['seed'], before['seed'])
        self.assertEqual(job['settings']['variants'], 1)
        for key in ('prompt', 'model', 'seconds', 'steps', 'cfg', 'mode', 'format'):
            self.assertEqual(job['settings'][key], before['settings'][key])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        after = self.studio.item(before['id'])
        for key in ('id', 'created', 'title', 'favorite', 'job_id', 'projects'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(self.studio.rows('SELECT * FROM project_sounds'), membership)
        self.assertEqual(len(self.studio.items()), 1)
        self.assertEqual(self.studio.items(job_id=self.original_job)[0]['id'], before['id'])
        self.assertEqual(after['trim']['start'], .1)
        self.assertEqual(after['trim']['end'], .3)
        self.assertEqual(after['regeneration']['state'], 'completed')
        self.assertNotEqual(after['path'], before['path'])
        self.assertNotEqual(self.studio.prepare_drag(after['id'])['path'], drag)
        self.assertTrue(Path(before['path']).is_file())
        self.assertEqual(json.loads(self.studio.rows('SELECT item FROM sound_revisions')[0]['item'])['path'], before['path'])
        self.studio.close()
        self.studio = Studio(data_dir=self.temp.name, command_factory=fixture)
        self.assertEqual(self.studio.item(after['id'])['path'], after['path'])

    def test_untrimmed_drag_gets_new_file_and_duplicate_click_uses_same_job(self):
        old_drag = self.studio.prepare_drag(self.sound['id'])['path']
        job = self.studio.regenerate(self.sound['id'])
        duplicate = self.studio.regenerate(self.sound['id'])
        self.assertEqual(duplicate['id'], job['id'])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        self.assertNotEqual(self.studio.prepare_drag(self.sound['id'])['path'], old_drag)
        self.assertEqual(len(self.studio.rows('SELECT * FROM sound_revisions')), 1)

    def test_seed_never_reuses_original_or_prior_attempts_even_on_random_collision(self):
        seeds = {42}
        for _ in range(3):
            with patch('core.secrets.randbelow', return_value=42):
                job = self.studio.regenerate(self.sound['id'])
            self.assertNotIn(job['settings']['seed'], seeds)
            seeds.add(job['settings']['seed'])
            self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')

    def test_process_failure_and_crop_failure_preserve_old_sound_and_retry(self):
        self.studio.set_trim(self.sound['id'], {'start': .1, 'end': .3})
        before = self.snapshot()
        self.studio.command_factory = lambda settings, seed, target, reference: fixture({**settings, 'prompt': 'failure'}, seed, target, reference)
        failed = wait(self.studio, self.studio.regenerate(self.sound['id'])['id'])
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(self.snapshot(), before)
        self.studio.command_factory = fixture
        with patch('core.render_trim', side_effect=ValueError('Crop failed')):
            failed = wait(self.studio, self.studio.regenerate(self.sound['id'])['id'])
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.studio.rows('SELECT * FROM sound_revisions'), [])
        self.assertEqual(wait(self.studio, self.studio.regenerate(self.sound['id'])['id'])['state'], 'completed')

    def test_cancel_running_preserves_take_and_regeneration_can_resume(self):
        before = self.snapshot()
        self.studio.command_factory = lambda settings, seed, target, reference: fixture({**settings, 'prompt': 'stubborn'}, seed, target, reference)
        job = self.studio.regenerate(self.sound['id'])
        deadline = time.monotonic() + 5
        while not list(self.studio.audio.glob('*.child')) and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(list(self.studio.audio.glob('*.child')))
        self.studio.cancel(job['id'])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'cancelled')
        self.assertEqual(self.snapshot(), before)
        self.studio.command_factory = fixture
        self.assertEqual(wait(self.studio, self.studio.regenerate(self.sound['id'])['id'])['state'], 'completed')

    def test_removed_model_uses_medium_and_does_not_restore_removed_project_membership(self):
        self.studio.set_project_sound(self.project['id'], self.sound['id'], False)
        saved = {**self.sound['settings'], 'model': 'sm-sfx', 'steps': 16, 'cfg': 6}
        self.studio.execute('UPDATE items SET settings=? WHERE id=?', (json.dumps(saved), self.sound['id']))
        job = self.studio.regenerate(self.sound['id'])
        self.assertEqual(job['settings']['model'], 'medium')
        self.assertEqual(job['settings']['steps'], 8)
        self.assertEqual(job['settings']['cfg'], 1)
        self.assertNotIn('project_id', job['settings'])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        self.assertEqual(self.studio.item(self.sound['id'])['projects'], [])
        with self.assertRaises(KeyError):
            self.studio.regenerate('missing')
