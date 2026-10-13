import http.client,json,os,secrets,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from processes import process_options,terminate_tree
class HTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.token=secrets.token_hex(20)
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
  cls.service=subprocess.Popen([sys.executable,str(ROOT/'tests/http_service_fixture.py')],env={**os.environ,'FX_PORT':str(cls.port),'FX_DATA_DIR':cls.temp.name,'FX_SESSION_TOKEN':cls.token},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**process_options())
  end=time.monotonic()+8
  while time.monotonic()<end:
   try:
    if cls.request('GET','/api/status')[0]==200:break
   except OSError:time.sleep(.05)
  else:raise AssertionError('Dienst nicht bereit')
 @classmethod
 def tearDownClass(cls):
  # Windows terminate() stops only the parent; a downloader can still write
  # into the temporary directory. Match the app's complete-tree shutdown.
  terminate_tree(cls.service);cls.service.wait(timeout=8);cls.temp.cleanup()
 @classmethod
 def request(cls,method,path,body=None,headers=None):
  conn=http.client.HTTPConnection('127.0.0.1',cls.port,timeout=5);h={'X-FX-Token':cls.token,**(headers or {})}
  if body is not None:h['Content-Type']='application/json';body=json.dumps(body)
  conn.request(method,path,body,h);r=conn.getresponse();data=r.read();result=(r.status,dict(r.getheaders()),data);conn.close();return result
 def test_ready_auth_host_origin(self):
  code,_,body=self.request('GET','/api/status');self.assertEqual(code,200);self.assertTrue(json.loads(body)['ready']);self.assertEqual(json.loads(body)['service'],'fx-studio')
  self.assertEqual([model['id'] for model in json.loads(body)['models']],['medium'])
  self.assertEqual(self.request('GET','/api/status',headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('GET','/api/status',headers={'Host':'other.test'})[0],403)
  self.assertEqual(self.request('POST','/api/generate',{},headers={'Origin':'https://other.test'})[0],403)
  self.assertEqual(self.request('POST','/api/cancel-setup',{},headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST','/api/cancel-setup',{},headers={'Origin':'https://other.test'})[0],403)
  self.assertEqual(self.request('POST','/api/cancel-setup',{})[0],200)
  self.assertEqual(self.request('GET','/api/status',headers={'X-FX-Token':'','Cookie':'fx_session='+self.token})[0],200)
 def test_validation_static_and_ranges(self):
  self.assertEqual(self.request('POST','/api/generate',[])[0],400)
  self.assertEqual(self.request('POST','/api/generate',{'prompt':'','seconds':3})[0],400)
  self.assertEqual(self.request('POST','/api/generate',{'prompt':'test','model':'dasheng'})[0],400)
  self.assertEqual(self.request('POST','/api/setup',{'model':'unknown'})[0],400)
  for model in ('sm-sfx','unite'):
   self.assertEqual(self.request('POST','/api/generate',{'prompt':'test','model':model})[0],400)
   self.assertEqual(self.request('POST','/api/setup',{'model':model})[0],400)
  self.assertEqual(self.request('POST','/api/setup',{})[0],202)
  self.assertEqual(self.request('GET','/../../etc/passwd')[0],404)
  self.assertEqual(self.request('GET','/')[0],200)
  code,headers,body=self.request('GET','/api/audio/SFX0001',headers={'Range':'bytes=0-99'});self.assertEqual(code,206);self.assertEqual(len(body),100);self.assertIn('Content-Range',headers)
  self.assertEqual(self.request('GET','/api/audio/SFX0001',headers={'Range':'bytes=999999999-'} )[0],416)
  self.assertEqual(self.request('GET','/api/audio/SFX0001',headers={'Range':'bytes=-10'})[0],206)
 def test_generation_format_preference_auth_validation_and_queue_capture(self):
  path='/api/generation-format'
  self.assertEqual(self.request('POST',path,{'format':'wav'},headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST',path,{'format':'wav'},headers={'Origin':'https://other.test'})[0],403)
  self.assertEqual(self.request('POST',path,{'format':'flac'})[0],400)
  self.assertEqual(self.request('POST',path,{'format':'wav'})[0],200)
  try:
   self.assertEqual(json.loads(self.request('GET','/api/status')[2])['generation_format'],'wav')
   code,_,body=self.request('POST','/api/generate',{'prompt':'HTTP format fixture','seconds':.5})
   self.assertEqual(code,202);job=json.loads(body)
   self.assertEqual(job['settings']['format'],'wav')
   self.assertEqual(self.request('POST','/api/generate',{'prompt':'test','format':'flac'})[0],400)
  finally:self.assertEqual(self.request('POST',path,{'format':'ogg'})[0],200)
 def test_waveform_search_and_export(self):
  code,_,body=self.request('GET','/api/waveform/SFX0001');self.assertEqual(code,200);wave=json.loads(body);self.assertEqual(len(wave['peaks']),700);self.assertGreater(max(wave['peaks']),.9)
  code,_,body=self.request('GET','/api/library?q=plop');self.assertEqual(code,200);self.assertGreater(len(json.loads(body)['items']),0)
  code,_,body=self.request('GET','/api/export/SFX0001?format=wav');self.assertEqual(code,200);self.assertEqual(body[:4],b'RIFF')
  code,_,body=self.request('GET','/api/export/SFX0001?format=mp3');self.assertEqual(code,200);self.assertGreater(len(body),10000)
  code,headers,body=self.request('GET','/api/export/SFX0001?format=ogg');self.assertEqual(code,200);self.assertEqual(body[:4],b'OggS');self.assertEqual(headers['Content-Type'],'audio/ogg')
  self.assertEqual(self.request('GET','/api/export/SFX0001?format=ogg',headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('GET','/api/export/SFX0001?format=exe')[0],400)
  self.assertEqual(self.request('POST','/api/favorite/SFX0352',{'favorite':True})[0],200)
  self.assertEqual(self.request('POST','/api/favorite/SFX0352',{'favorite':'yes'})[0],400)
 def test_creator_logo_asset(self):
  code,headers,body=self.request('GET','/assets/wik-dev.png')
  self.assertEqual(code,200);self.assertEqual(headers['Content-Type'],'image/png');self.assertEqual(body[:8],b'\x89PNG\r\n\x1a\n')
  self.assertEqual(self.request('GET','/assets/wik-dev.png',headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('GET','/assets/wik-dev.png',headers={'Host':'other.test'})[0],403)
  self.assertEqual(self.request('GET','/assets/../../backend/server.py')[0],404)
  self.assertEqual(self.request('GET','/assets/other.png')[0],404)
 def test_project_deletion_preview_auth_confirmation_and_files(self):
  code,_,body=self.request('POST','/api/projects',{'name':'HTTP disposable deletion'})
  self.assertEqual(code,200);project=json.loads(body);project_id=project['id']
  code,_,body=self.request('POST','/api/generate',{'prompt':'delete fixture','seconds':.5,'project_id':project_id})
  self.assertEqual(code,202);job_id=json.loads(body)['id'];deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   sounds=json.loads(self.request('GET','/api/history?job='+job_id)[2])['items']
   if sounds:break
   time.sleep(.03)
  self.assertTrue(sounds);source=Path(sounds[0]['path'])
  code,_,body=self.request('GET','/api/project-deletion?project_id='+project_id)
  self.assertEqual(code,200);plan=json.loads(body);self.assertEqual(plan['generated_sounds'],1)
  data={'project_id':project_id,'confirm_name':project['name'],'revision':plan['revision']}
  self.assertEqual(self.request('GET','/api/project-deletion?project_id='+project_id,headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST','/api/project-delete',data,headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST','/api/project-delete',data,headers={'Origin':'https://other.test'})[0],403)
  self.assertEqual(self.request('POST','/api/project-delete',{**data,'confirm_name':'wrong'})[0],400)
  self.assertTrue(source.exists())
  code,_,body=self.request('POST','/api/project-delete',data)
  self.assertEqual(code,200);self.assertTrue(json.loads(body)['deleted']);self.assertFalse(source.exists())
  self.assertEqual(self.request('GET','/api/projects/'+project_id)[0],404)
  self.assertEqual(self.request('GET','/api/item/'+sounds[0]['id'])[0],404)
 def test_regenerate_route_authentication_replacement_and_library_rejection(self):
  self.assertEqual(self.request('POST','/api/regenerate/SFX0001',{})[0],400)
  self.assertEqual(self.request('POST','/api/regenerate/missing',{})[0],404)
  code,_,body=self.request('POST','/api/generate',{'prompt':'HTTP replacement test','seconds':.5,'seed':42})
  self.assertEqual(code,202);job_id=json.loads(body)['id'];deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   sounds=json.loads(self.request('GET','/api/history?job='+job_id)[2])['items']
   if sounds:break
   time.sleep(.03)
  self.assertTrue(sounds);sound=sounds[0];route='/api/regenerate/'+sound['id']
  self.assertEqual(self.request('POST',route,{},headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST',route,{},headers={'Origin':'https://other.test'})[0],403)
  code,_,body=self.request('POST',route,{})
  self.assertEqual(code,202);replacement=json.loads(body)['id'];deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   state=json.loads(self.request('GET','/api/item/'+sound['id'])[2])
   if state['regeneration']['state']=='completed':break
   time.sleep(.03)
  self.assertEqual(state['regeneration']['id'],replacement)
  self.assertEqual(state['regeneration']['state'],'completed')
  self.assertNotEqual(state['path'],sound['path']);self.assertNotEqual(state['seed'],sound['seed'])
 def test_zoom_waveform_detail_and_limits(self):
  code,_,body=self.request('GET','/api/waveform/SFX0001?bins=11200')
  self.assertEqual(code,200);wave=json.loads(body);self.assertEqual(len(wave['peaks']),11200)
  self.assertEqual(wave['bins'],11200);self.assertGreater(max(wave['peaks']),.9)
  original=json.loads(self.request('GET','/api/waveform/SFX0001')[2])
  self.assertEqual(wave['duration'],original['duration']);self.assertEqual(wave['sample_rate'],original['sample_rate'])
  for value in ('-1','0','99','11201','1000000000','NaN','2.5'):
   self.assertEqual(self.request('GET','/api/waveform/SFX0001?bins='+value)[0],400)
 def test_trim_playback_export_and_access_controls(self):
  source_id='SFX0001'
  code,_,body=self.request('POST','/api/trim/'+source_id,{'start':.1,'end':.3})
  self.assertEqual(code,200);item=json.loads(body)['item'];self.assertAlmostEqual(item['duration'],.2);self.assertEqual(item['trim']['fade_ms'],5)
  import io,soundfile as sf
  for route in ('/api/audio/','/api/export/'):
   code,_,data=self.request('GET',route+source_id+('?format=wav' if route=='/api/export/' else ''))
   self.assertEqual(code,200);samples,rate=sf.read(io.BytesIO(data),always_2d=True);self.assertEqual(len(samples),round(.2*rate));self.assertTrue((samples[[0,-1]]==0).all())
  code,_,data=self.request('GET','/api/export/'+source_id+'?format=ogg')
  self.assertEqual(code,200);samples,rate=sf.read(io.BytesIO(data),always_2d=True);self.assertEqual(samples.shape,(round(.2*rate),2));self.assertEqual(sf.info(io.BytesIO(data)).subtype,'VORBIS')
  code,_,body=self.request('POST','/api/prepare-drag/'+source_id,{})
  self.assertEqual(code,200);self.assertTrue(Path(json.loads(body)['path']).is_relative_to(self.temp.name))
  self.assertEqual(self.request('POST','/api/trim/'+source_id,{'start':.1,'end':.3},headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST','/api/trim/'+source_id,{'start':.1,'end':.3},headers={'Origin':'https://other.test'})[0],403)
  self.assertEqual(self.request('POST','/api/prepare-drag/'+source_id,{},headers={'X-FX-Token':''})[0],401)
  self.assertEqual(self.request('POST','/api/trim/'+source_id,{'start':.4,'end':.2})[0],400)
  self.assertEqual(self.request('POST','/api/prepare-drag/../../etc/passwd',{})[0],404)
  self.assertEqual(self.request('POST','/api/trim/'+source_id,{'reset':True})[0],200)
