import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_core import Studio, fixture, wait
from agent_access import AgentAccess
from agent_api import AgentAPI, Conflict
from project_cleanup import deletion_plan
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_behavior_tests import fixture_library


class ProjectDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = Path(self.temp.name) / 'library'
        fixture_library(self.library)
        self.studio = Studio(self.temp.name, library_root=self.library, command_factory=fixture)
        self.api = AgentAPI(self.studio, AgentAccess(self.studio.data))
        self.project = self.studio.create_project({'name': 'Delete test'})
        self.other = self.studio.create_project({'name': 'Keep test'})

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def generate(self, request='asset'):
        data = {'request_id': request, 'settings': {'prompt': 'test', 'asset_name': request, 'seconds': .5,
                'seed': 42, 'project_id': self.project['id']}}
        job = self.api.generate(data)
        self.assertEqual(wait(self.studio, job['id'])['state'], 'completed')
        return self.studio.items(job_id=job['id'])[0], data

    def delete(self, **raw):
        plan = self.studio.project_deletion(self.project['id'])
        return self.studio.delete_project(self.project['id'], {'confirm_name': self.project['name'], 'revision': plan['revision'], **raw})

    def test_deletes_originals_revisions_crops_drag_logs_and_preserves_shared_library_exports(self):
        sound, request = self.generate()
        shared, _ = self.generate('shared')
        self.studio.set_project_sound(self.other['id'], shared['id'])
        self.studio.favorite(sound['id'], True)
        self.studio.set_trim(sound['id'], {'start': .1, 'end': .3})
        self.studio.prepare_drag(sound['id'])
        regeneration = self.studio.regenerate(sound['id'])
        self.assertEqual(wait(self.studio, regeneration['id'])['state'], 'completed')
        self.studio.prepare_drag(sound['id'])
        external = self.api.export_sound({'sound_id': sound['id'], 'name': 'editor_asset'})
        self.studio.set_project_sound(self.project['id'], 'SFX0001')
        self.studio.favorite('SFX0001', True)
        library = Path(self.studio.item('SFX0001')['path'])
        library_hash = hashlib.sha256(library.read_bytes()).digest()
        plan, ids, jobs, updates, paths = deletion_plan(self.studio, self.project['id'])
        self.assertEqual(plan['generated_sounds'], 1)
        self.assertEqual(plan['shared_sounds_kept'], 1)
        self.assertEqual(plan['library_links_removed'], 1)
        self.assertGreaterEqual(plan['files'], 7)
        result = self.delete()
        self.assertTrue(result['deleted'])
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertTrue(Path(shared['path']).exists())
        self.assertEqual(self.studio.project_items(self.other['id'])[0]['id'], shared['id'])
        self.assertEqual(self.studio.item(shared['id'])['projects'], [{'id': self.other['id'], 'name': self.other['name']}])
        self.assertNotIn('project_id', self.studio.item(shared['id'])['settings'])
        self.assertTrue(Path(external['path']).exists())
        self.assertEqual(hashlib.sha256(library.read_bytes()).digest(), library_hash)
        self.assertTrue(self.studio.item('SFX0001')['favorite'])
        self.assertEqual(self.studio.rows('SELECT * FROM sound_revisions'), [])
        self.assertEqual(self.studio.rows('SELECT * FROM sound_trims'), [])
        with self.assertRaises(KeyError):
            self.studio.item(sound['id'])
        with self.assertRaises(Conflict):
            self.api.generate(request)
        self.studio.close()
        self.studio = Studio(self.temp.name, library_root=self.library, command_factory=fixture)
        self.assertEqual(len(self.studio.projects()), 1)
        self.assertEqual(len(self.studio.items()), 1)

    def test_confirmation_and_stale_revision_never_delete(self):
        sound, _ = self.generate()
        preview = self.studio.project_deletion(self.project['id'])
        with self.assertRaisesRegex(ValueError, 'exact project name'):
            self.delete(confirm_name='wrong')
        self.studio.set_trim(sound['id'], {'start': .1, 'end': .3})
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.studio.delete_project(self.project['id'], {'confirm_name': self.project['name'], 'revision': preview['revision']})
        self.assertTrue(Path(sound['path']).exists())
        self.assertEqual(len(self.studio.project_items(self.project['id'])), 1)

    def test_active_jobs_block_deletion_until_cancelled(self):
        with self.studio.lock:
            job = self.studio.enqueue({'prompt': 'test', 'seconds': .5, 'project_id': self.project['id']})
            self.assertFalse(self.studio.project_deletion(self.project['id'])['can_delete'])
            with self.assertRaisesRegex(ValueError, 'Finish or cancel'):
                self.delete()
            self.studio.cancel(job['id'])
        self.assertEqual(wait(self.studio, job['id'])['state'], 'cancelled')
        self.assertTrue(self.delete()['deleted'])
        self.assertEqual(self.studio.rows('SELECT * FROM jobs'), [])

    def test_file_failure_rolls_back_catalogue_and_restores_staged_audio(self):
        sound, _ = self.generate()
        original = Path(sound['path']).read_bytes()
        real_replace, attempts = os.replace, []
        def fail_once(source, target):
            attempts.append(str(target))
            if len(attempts) == 2:
                raise OSError('Disk error')
            return real_replace(source, target)
        with patch('project_cleanup.os.replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'Disk error'):
                self.delete()
        self.assertEqual(Path(sound['path']).read_bytes(), original)
        self.assertEqual(self.studio.item(sound['id'])['id'], sound['id'])
        self.assertEqual(list((self.studio.data / '.project-deletions').iterdir()), [])
        self.assertTrue(self.delete()['deleted'])

    def test_startup_recovers_a_crash_before_commit_and_finishes_after_commit(self):
        sound, _ = self.generate()
        source = Path(sound['path'])
        folder = self.studio.data / '.project-deletions' / 'crash'
        folder.mkdir(parents=True)
        manifest = {'project_id': self.project['id'], 'files': [str(source.relative_to(self.studio.data))]}
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        os.replace(source, folder / '0')
        self.studio.close()
        self.studio = Studio(self.temp.name, library_root=self.library, command_factory=fixture)
        self.assertTrue(source.exists())
        self.assertFalse(folder.exists())
        folder.mkdir();(folder / 'manifest.json').write_text(json.dumps(manifest))
        os.replace(source, folder / '0')
        self.studio.execute('DELETE FROM projects WHERE id=?', (self.project['id'],))
        self.studio.close()
        self.studio = Studio(self.temp.name, library_root=self.library, command_factory=fixture)
        self.assertFalse(folder.exists())
        self.assertFalse(source.exists())

    def test_database_failure_rolls_back_sounds_jobs_and_files(self):
        sound, _ = self.generate()
        before = self.studio.rows('SELECT * FROM items')
        original = Path(sound['path']).read_bytes()
        self.studio.execute("CREATE TRIGGER fail_project_delete BEFORE DELETE ON projects BEGIN SELECT RAISE(ABORT, 'Database failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'Database failure'):
            self.delete()
        self.assertEqual(self.studio.rows('SELECT * FROM items'), before)
        self.assertTrue(self.studio.project(self.project['id']))
        self.assertTrue(self.studio.rows('SELECT * FROM jobs'))
        self.assertEqual(Path(sound['path']).read_bytes(), original)
        self.studio.execute('DROP TRIGGER fail_project_delete')
        self.assertTrue(self.delete()['deleted'])

    def test_external_and_symlink_paths_are_never_removed(self):
        sound, _ = self.generate()
        external = Path(self.temp.name) / 'external.ogg'
        external.write_bytes(Path(sound['path']).read_bytes())
        self.studio.execute('UPDATE items SET path=? WHERE id=?', (str(external), sound['id']))
        edits = self.studio.data / 'edits';edits.mkdir()
        link = edits / (sound['id'] + '-symlink.ogg');link.symlink_to(external)
        self.delete()
        self.assertTrue(external.exists())
        self.assertTrue(link.is_symlink())

    def test_mixed_pack_keeps_other_project_jobs_and_exports(self):
        pack = self.api.generate({'request_id': 'pack', 'name': 'assets', 'project_id': self.project['id'],
            'assets': [{'prompt': 'test', 'seconds': .5, 'asset_name': 'one'}, {'prompt': 'test', 'seconds': .5, 'asset_name': 'two'}]}, pack=True)
        for job in pack['jobs']:
            wait(self.studio, job['id'])
        kept = self.api.pack(pack['id'])['jobs'][1]['sounds'][0]
        self.studio.set_project_sound(self.other['id'], kept['id'])
        self.delete()
        surviving = self.api.pack(pack['id'])
        self.assertEqual(len(surviving['jobs']), 1)
        self.assertEqual(surviving['jobs'][0]['sounds'][0]['id'], kept['id'])
        self.assertEqual(surviving['state'], 'completed')
        self.assertTrue(self.api.export_pack({'pack_id': pack['id']})['sounds'])
