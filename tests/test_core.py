import json, os, signal, sqlite3, subprocess, sys, tempfile, time, unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from core import Studio, ROOT
from process_checks import process_running

def fixture(settings,seed,target,reference):
 return [sys.executable,'-u',str(ROOT/'tests/fixture_worker.py'),settings['prompt'],str(target),str(settings['seconds'])]
def wait(studio,id,timeout=10):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  job=next(x for x in studio.status()['jobs'] if x['id']==id)
  if job['state'] not in ('queued','running','cancelling'):return job
  time.sleep(.03)
 raise AssertionError('Testauftrag hängt')

class CoreTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
 def tearDown(self):
  self.studio.close();self.temp.cleanup()
 def enqueue(self,**kwargs):return self.studio.enqueue({'prompt':'test','seconds':.5,'seed':42,**kwargs})['id']
 def test_validation_and_no_partial_jobs(self):
  for raw in ({},{'prompt':'x','seconds':float('nan')},{'prompt':'x','variants':1.2},{'prompt':'x','seed':True},{'prompt':'x','steps':17},{'prompt':'x','mode':'unknown'},{'prompt':'x','seconds':31}):
   with self.assertRaises(ValueError):self.studio.enqueue(raw)
  self.assertEqual(self.studio.status()['jobs'],[])
 def test_serial_queue_variants_and_persistence(self):
  one=self.enqueue(variants=2);two=self.enqueue(seed=101)
  first=wait(self.studio,one);second=wait(self.studio,two)
  self.assertEqual(first['state'],'completed');self.assertGreaterEqual(second['started'],first['finished'])
  items=self.studio.items(job_id=one);self.assertEqual(sorted(x['seed'] for x in items),[42,43])
  self.studio.favorite(items[0]['id'],True);self.assertEqual(len(self.studio.items('test',True)),1)
  self.studio.close();self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
  self.assertEqual(len(self.studio.items()),3);self.assertEqual(len(self.studio.items(favorites=True)),1)
 def test_real_process_error_and_recovery(self):
  failed=wait(self.studio,self.enqueue(prompt='failure'));self.assertEqual(failed['state'],'failed');self.assertIn('process failure',failed['error'])
  incomplete=wait(self.studio,self.enqueue(prompt='incomplete'));self.assertEqual(incomplete['state'],'failed');self.assertEqual(self.studio.items(),[])
  self.assertEqual(wait(self.studio,self.enqueue())['state'],'completed')
 def test_cancel_queued_running_force_kill_and_resume(self):
  one=self.enqueue(prompt='stubborn');two=self.enqueue()
  end=time.monotonic()+5
  while not list(self.studio.audio.glob('*.child')) and time.monotonic()<end:time.sleep(.03)
  self.assertIsNotNone(self.studio.process);pid=self.studio.process.pid
  child=int(next(self.studio.audio.glob('*.child')).read_text());self.studio.cancel(two);self.assertEqual(wait(self.studio,two)['state'],'cancelled')
  self.studio.cancel(one);self.assertEqual(wait(self.studio,one)['state'],'cancelled')
  self.assertFalse(process_running(pid));self.assertFalse(process_running(child))
  self.assertEqual(self.studio.items(),[]);self.assertEqual(wait(self.studio,self.enqueue())['state'],'completed')
 def test_shutdown_stops_worker(self):
  job=self.enqueue(prompt='stubborn');end=time.monotonic()+5
  while self.studio.process is None and time.monotonic()<end:time.sleep(.01)
  pid=self.studio.process.pid;self.studio.close()
  self.assertFalse(process_running(pid))
  with self.assertRaises(sqlite3.ProgrammingError):self.studio.db.execute('SELECT 1')
  self.studio.close()
  database=Path(self.temp.name)/'studio.sqlite';moved=database.with_name('closed.sqlite')
  database.rename(moved);moved.rename(database)
  self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
  self.assertEqual(wait(self.studio,job)['state'],'cancelled')
 def test_interrupted_jobs_and_input_preserved(self):
  self.studio.execute("INSERT INTO jobs(id,settings,state,created) VALUES(?,?,?,?)",('012345678901',json.dumps({'prompt':'saved'}),'running',time.time()))
  self.studio.close();self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
  self.assertEqual(self.studio.status()['jobs'][0]['state'],'interrupted');self.assertEqual(self.studio.status()['jobs'][0]['settings']['prompt'],'saved')
 def test_library_provenance_paths_and_search(self):
  assets=self.studio.library_items();self.assertEqual(len(assets),352)
  unknown=[x for x in assets if x['license']['status']!='documented_bundle'];self.assertEqual(len(unknown),5)
  self.assertTrue(self.studio.library_items('regen'));self.assertTrue(self.studio.library_items('plop'))
  for item in assets:self.assertTrue(Path(item['path']).is_relative_to(self.studio.library_root.resolve()));self.assertTrue(Path(item['path']).is_file())
  self.studio.favorite(unknown[0]['id'],True);self.assertEqual(len(self.studio.library_items(favorites=True)),1)
  with self.assertRaises(KeyError):self.studio.item('../../etc/passwd')
 def test_missing_file_keeps_settings(self):
  id=self.enqueue();wait(self.studio,id);item=self.studio.items()[0];Path(item['path']).unlink();self.assertTrue(self.studio.item(item['id'])['missing'])
 def test_ready_setup_reuses_weights(self):
  with patch.object(self.studio,'model_status',return_value={'ready':True,'runtime_ready':True}):
   self.assertEqual(self.studio.setup()['state'],'completed');self.assertIsNone(self.studio.setup_process)
 def test_model_selection_rejects_unknown_and_missing_weights(self):
  for model in ('sm-sfx','unite','dasheng','sm-music','../medium',None,[]):
   with self.assertRaises(ValueError):self.enqueue(model=model)
  self.assertEqual(self.studio.status()['jobs'],[])
  self.studio.command_factory=self.studio.command
  with patch.object(self.studio,'model_status',return_value={'ready':False}):
   with self.assertRaisesRegex(ValueError,'Medium'):self.enqueue(model='medium')
  self.assertEqual(self.studio.rows('SELECT * FROM jobs'),[])
 def test_serial_medium_jobs_release_previous_process_and_persist_settings(self):
  previous=[];models=[]
  def command(settings,seed,target,reference):
   if previous:
    if process_running(previous[-1]):raise AssertionError('Das bisherige Modell läuft noch')
   models.append(settings['model'])
   return fixture(settings,seed,target,reference)
  self.studio.command_factory=command
  one=self.enqueue(model='medium',prompt='stubborn')
  end=time.monotonic()+5
  while not list(self.studio.audio.glob('*.child')) and time.monotonic()<end:time.sleep(.02)
  previous.append(self.studio.process.pid)
  two=self.enqueue(model='medium');three=self.enqueue(model='medium')
  self.studio.cancel(one)
  stopped=wait(self.studio,one);second=wait(self.studio,two);third=wait(self.studio,three)
  self.assertEqual(stopped['state'],'cancelled');self.assertEqual(second['state'],'completed');self.assertEqual(third['state'],'completed')
  self.assertGreaterEqual(second['started'],stopped['finished']);self.assertGreaterEqual(third['started'],second['finished'])
  self.assertEqual(models,['medium','medium','medium'])
  item=self.studio.items(job_id=two)[0];self.assertEqual(item['settings']['model'],'medium')
  self.studio.close();self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
  self.assertEqual(self.studio.item(item['id'])['settings']['model'],'medium')
 def test_medium_uses_matching_codec_sfx_prompt_and_free_models(self):
  raw={'prompt':'A metal door slamming','model':'medium','seconds':3}
  settings=self.studio.validate(raw)
  command=self.studio.command(settings,42,Path(self.temp.name)/'medium.wav',None)
  def flag(name):return command[command.index(name)+1]
  self.assertEqual(flag('--dit'),'medium');self.assertEqual(flag('--decoder'),'same-l')
  self.assertEqual(flag('--prompt'),'TrackType: SFX, '+raw['prompt']);self.assertIn('--free-models',command)
  self.assertEqual(settings['prompt'],raw['prompt'])
  old=self.studio.validate({'prompt':'request without model'});self.assertEqual(old['model'],'medium')
  command=self.studio.command(old,42,Path(self.temp.name)/'default.wav',None)
  self.assertEqual(flag('--dit'),'medium');self.assertEqual(flag('--decoder'),'same-l')
  self.assertEqual(old['steps'],8);self.assertEqual(old['cfg'],1)
 def test_removed_models_preserve_saved_audio_and_provenance(self):
  for model in ('sm-sfx','unite'):
   id=self.enqueue();wait(self.studio,id);item=self.studio.items(job_id=id)[0]
   original=Path(item['path']).read_bytes();settings={**item['settings'],'model':model}
   self.studio.execute('UPDATE items SET settings=? WHERE id=?',(json.dumps(settings),item['id']))
   self.studio.favorite(item['id'],True)
   self.studio.close();self.studio=Studio(data_dir=self.temp.name,command_factory=fixture)
   restored=self.studio.item(item['id'])
   self.assertEqual(restored['settings']['model'],model);self.assertFalse(restored['missing'])
   self.assertTrue(restored['favorite']);self.assertEqual(Path(restored['path']).read_bytes(),original)
   with self.assertRaisesRegex(ValueError,'removed'):self.studio.enqueue(settings)
   with self.assertRaisesRegex(ValueError,'removed'):self.studio.setup(model)
  self.assertEqual(wait(self.studio,self.enqueue())['state'],'completed')
 def test_editing_validation_reference_and_reuse(self):
  id=self.enqueue();wait(self.studio,id);source=self.studio.items()[0]
  settings=self.studio.validate({'prompt':'variation','mode':'variation','seconds':.5,'reference_id':source['id'],'strength':.65})
  self.assertEqual(settings['reference_id'],source['id'])
  for raw in ({'seconds':1},{'strength':1.1},{'mode':'inpaint','start':.4,'end':.2},{'mode':'inpaint','start':-.1,'end':.2}):
   with self.assertRaises(ValueError):self.studio.validate({'prompt':'edit','mode':'variation','seconds':.5,'reference_id':source['id'],**raw})
  edit=self.enqueue(mode='inpaint',reference_id=source['id'],start=.1,end=.3)
  self.assertEqual(wait(self.studio,edit)['state'],'completed');item=self.studio.items(job_id=edit)[0]
  self.assertEqual(item['settings']['start'],.1);self.assertEqual(item['reference']['title'],source['title'])
