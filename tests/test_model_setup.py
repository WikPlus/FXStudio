import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from core import Studio, ROOT
from model_download import download_bundle, valid_file
from runtime_paths import default_data_dir, expose_cached_model
from models import weight_spec
import processes


def state(studio, model='medium'):
    return {'id':model,'ready':(studio.data/'ready').exists(),'missing':['test.npz'],
            'dependencies':[],'runtime_ready':True,'download_gib':.1}


def until(condition, timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if condition():return
        time.sleep(.02)
    raise AssertionError('Setup did not reach the expected state')


class SetupLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.patch=patch.object(Studio,'model_status',state);self.patch.start()
        self.env=patch.dict(os.environ,{'FX_AUTO_SETUP':'1'});self.env.start()
        self.studios=[]
    def tearDown(self):
        for studio in self.studios:studio.close()
        self.env.stop();self.patch.stop();self.temp.cleanup()
    def studio(self,mode='success'):
        instance=Studio(data_dir=self.folder,setup_command_factory=lambda model:
                       [sys.executable,'-u',str(ROOT/'tests/fixture_downloader.py'),mode,str(self.folder)])
        self.studios.append(instance);return instance
    def test_first_launch_starts_once_and_complete_cache_stays_offline(self):
        studio=self.studio();self.assertEqual(studio.setup_state['state'],'running')
        until(lambda:studio.setup_state.get('progress',{}).get('bytes',0)>0)
        self.assertEqual(studio.setup_state['progress']['total'],100)
        self.assertEqual(studio.setup()['state'],'running')
        until(lambda:studio.setup_state['state']=='completed')
        studio.close();second=self.studio()
        self.assertIsNone(second.setup_thread)
    def test_failure_is_visible_and_not_automatically_retried_on_restart(self):
        studio=self.studio('failure');until(lambda:studio.setup_state['state']=='failed')
        self.assertIn('Network is unavailable',studio.setup_state['message'])
        studio.close();second=self.studio('failure')
        self.assertEqual(second.setup_state['state'],'failed');self.assertIsNone(second.setup_thread)
        second.setup();until(lambda:second.setup_state['state']=='completed')
    def test_pause_stops_process_and_stays_paused_until_resume(self):
        studio=self.studio('slow');until(lambda:studio.setup_process is not None)
        process=studio.setup_process;studio.cancel_setup()
        until(lambda:studio.setup_state['state']=='paused')
        self.assertIsNotNone(process.poll());self.assertFalse((self.folder/'ready').exists())
        studio.close();second=self.studio()
        self.assertEqual(second.setup_state['state'],'paused');self.assertIsNone(second.setup_thread)
        second.setup();until(lambda:second.setup_state['state']=='completed')
    def test_normal_quit_resumes_download_on_next_launch(self):
        studio=self.studio('slow');until(lambda:studio.setup_process is not None)
        studio.close();second=self.studio()
        self.assertEqual(second.setup_state['state'],'running')
        until(lambda:second.setup_state['state']=='completed')
    def test_immediate_resume_retains_the_new_cancellable_process(self):
        closing=threading.Event();release=threading.Event();original=subprocess.Popen;calls=[]
        class DelayedClose:
            def __init__(self,stream):self.stream=stream
            def __iter__(self):return iter(self.stream)
            def close(self):closing.set();release.wait(6);self.stream.close()
        def launch(*args,**kwargs):
            process=original(*args,**kwargs)
            # Windows cancellation also launches taskkill through Popen. Only
            # count downloader processes in this download-resume regression.
            if str(ROOT/'tests/fixture_downloader.py') in args[0]:
                calls.append(process)
                if len(calls)==1:process.stdout=DelayedClose(process.stdout)
            return process
        with patch('core.subprocess.Popen',side_effect=launch):
            studio=self.studio('slow');until(lambda:studio.setup_process is not None)
            old_thread=studio.setup_thread;studio.cancel_setup();self.assertTrue(closing.wait(5))
            try:
                studio.setup();until(lambda:len(calls)==2 and studio.setup_process is calls[1])
                release.set();old_thread.join(2)
                self.assertIs(studio.setup_process,calls[1])
                studio.cancel_setup();until(lambda:studio.setup_state['state']=='paused')
                self.assertIsNotNone(calls[1].poll())
            finally:
                release.set()
                for process in calls:processes.terminate_tree(process)
    def test_missing_runtime_does_not_download(self):
        with patch.object(Studio,'model_status',lambda studio,model='medium':
                          {**state(studio,model),'runtime_ready':False}):
            studio=self.studio();self.assertEqual(studio.setup_state['state'],'failed')
            self.assertIsNone(studio.setup_thread)
            with self.assertRaisesRegex(ValueError,'runtime'):studio.setup()


class DownloadIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.cached=self.root/'cache.tflite';self.cached.write_bytes(b'\x00\x00\x00\x00TFL3test bytes')
        self.spec={'repo':'test','revision':'pinned','files':[{'name':'medium/model.tflite','remote':'tflite/medium/model.tflite','size':self.cached.stat().st_size,'sha256':hashlib.sha256(self.cached.read_bytes()).hexdigest()}]}
    def tearDown(self):self.temp.cleanup()
    def test_exact_verified_file_progress_and_cache_reuse(self):
        events=[];calls=[]
        def download(**kwargs):calls.append(kwargs);return self.cached
        folder=self.root/'models';download_bundle(self.spec,folder,download=download,progress=events.append)
        self.assertEqual((folder/'medium/model.tflite').read_bytes(),self.cached.read_bytes())
        self.assertEqual(calls[0]['revision'],'pinned');self.assertIs(calls[0]['token'],False)
        self.assertEqual(events[-1]['phase'],'ready');self.assertEqual(events[-1]['bytes'],events[-1]['total'])
        download_bundle(self.spec,folder,download=lambda **kw:self.fail('Downloaded an installed model'),progress=events.append)
    def test_corrupt_file_and_checksum_are_not_exposed(self):
        self.cached.write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'incomplete'):download_bundle(self.spec,self.root/'models',download=lambda **kw:self.cached,progress=lambda e:None)
        self.assertFalse((self.root/'models/medium/model.tflite').exists())
        self.cached.write_bytes(b'\x00\x00\x00\x00TFL3evil bytes')
        with self.assertRaisesRegex(RuntimeError,'checksum'):download_bundle(self.spec,self.root/'models',download=lambda **kw:self.cached,progress=lambda e:None)
        self.assertFalse((self.root/'models/medium/model.tflite').exists())
    def test_disk_space_failure_happens_before_network(self):
        with patch('model_download.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(RuntimeError,'disk space'):download_bundle(self.spec,self.root/'models',download=lambda **kw:self.fail('Network started'),progress=lambda e:None)
    def test_damaged_cache_is_replaced_once_before_installing(self):
        original=self.cached.read_bytes();self.cached.write_bytes(b'corrupt');calls=[]
        def download(**kwargs):
            calls.append(kwargs)
            if kwargs.get('force_download'):self.cached.write_bytes(original)
            return self.cached
        download_bundle(self.spec,self.root/'models',download=download,progress=lambda e:None)
        self.assertEqual(len(calls),2);self.assertNotIn('force_download',calls[0])
        self.assertIs(calls[1]['force_download'],True)
        self.assertEqual((self.root/'models/medium/model.tflite').read_bytes(),original)
    def test_windows_links_work_without_admin_and_copy_fallback(self):
        target=self.root/'models/fallback.tflite'
        with patch.object(Path,'symlink_to',side_effect=PermissionError('No Windows symlink permission')):
            expose_cached_model(self.cached,target);self.assertEqual(target.stat().st_ino,self.cached.stat().st_ino)
            with patch('runtime_paths.os.link',side_effect=OSError('Other volume')):
                copied=self.root/'models/copy.tflite';expose_cached_model(self.cached,copied)
                self.assertEqual(copied.read_bytes(),self.cached.read_bytes())
                self.assertNotEqual(copied.stat().st_ino,self.cached.stat().st_ino)
    def test_windows_manifest_and_data_path(self):
        spec=weight_spec(runtime='tflite');self.assertEqual(len(spec['files']),4)
        self.assertTrue(all(file['sha256'] for file in spec['files']))
        self.assertFalse(any('same-s' in file['name'] or 'sm-sfx' in file['name'] for file in spec['files']))
        with patch.dict(os.environ,{'LOCALAPPDATA':str(self.root)}):self.assertEqual(default_data_dir('win32'),self.root/'FX Studio')
    def test_windows_cancels_the_entire_process_tree(self):
        process=SimpleNamespace(pid=1234,poll=lambda:None)
        with patch.object(processes,'os',SimpleNamespace(name='nt')),patch.object(subprocess,'CREATE_NO_WINDOW',0x8000000,create=True),patch.object(subprocess,'CREATE_NEW_PROCESS_GROUP',0x200,create=True),patch('processes.subprocess.run') as run:
            self.assertEqual(processes.process_options(),{'creationflags':0x8000200})
            processes.terminate_tree(process)
            self.assertEqual(run.call_args.args[0],['taskkill','/PID','1234','/T','/F'])
