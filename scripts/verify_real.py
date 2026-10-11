"""Opt-in hardware acceptance. Runs only the installed Medium model."""
import json, os, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from core import Studio
s=Studio();report={}
def state(id):return next(x for x in s.status()['jobs'] if x['id']==id)
def wait(id):
 previous=None
 while True:
  job=state(id)
  mark=(job['state'],job['stage'],job['step'])
  if mark!=previous:print(job['state'],job['message'],job['elapsed'],flush=True);previous=mark
  if job['state'] not in ('queued','running','cancelling'):return job
  time.sleep(.1)
def check(id):
 job=wait(id);assert job['state']=='completed',job
 results=s.items(job_id=id)
 for item in results:
  audio,rate=sf.read(item['path'],always_2d=True);assert rate==44100 and audio.shape[1]==2
  assert np.isfinite(audio).all() and np.max(np.abs(audio))>.001
  item['peak']=round(float(np.max(np.abs(audio))),4);item['rms']=round(float(np.sqrt(np.mean(audio**2))),4)
 return {'job':job,'items':results}
try:
 # Stop a real GPU worker after sampling has begun, then prove it no longer exists.
 cancelled=s.enqueue({'prompt':'A long gust of wind in a dark cave','seconds':30,'steps':16,'seed':42602})['id']
 queued=s.enqueue({'prompt':'An isolated metallic game impact','seconds':2,'seed':42603})['id']
 while state(cancelled)['state'] in ('queued','running'):
  if state(cancelled)['stage']==3 and s.process:
   pid=s.process.pid;start=time.monotonic();s.cancel(queued);s.cancel(cancelled);break
  time.sleep(.02)
 else:raise AssertionError('Real worker finished before cancellation checkpoint')
 stopped=wait(cancelled)
 assert stopped['state']=='cancelled' and state(queued)['state']=='cancelled'
 try:os.kill(pid,0)
 except ProcessLookupError:pass
 else:raise AssertionError('Worker is still alive')
 assert not s.items(job_id=cancelled)
 report['cancel']={'job':cancelled,'worker_pid':pid,'seconds':round(time.monotonic()-start,3),'state':stopped['state'],'queued_cancelled':True}
 # A short pair confirms recovery, real variants and seed increments.
 pair=s.enqueue({'prompt':'A futuristic laser power-up, rising electronic energy sweep, crisp game sound, no music','seconds':2,'variants':2,'seed':42604})['id']
 report['recovery_variants']=check(pair)
 atmosphere=s.enqueue({'prompt':'Deep eerie cave ambience, distant wind howling through stone tunnels, subtle low rumble, no music or voices','seconds':8,'seed':42606})['id']
 report['atmosphere']=check(atmosphere)
 item=report['recovery_variants']['items'][0];s.favorite(item['id'],True)
 export=s.data/'acceptance-exports';export.mkdir(exist_ok=True)
 import shutil
 wav=export/'Game-Boost.wav';shutil.copyfile(item['path'],wav)
 mp3=export/'Game-Boost.mp3';s.convert(item['path'],mp3,'mp3')
 info=sf.info(str(mp3));assert abs(info.duration-item['duration'])<.06 and info.frames>0
 report['exports']={'wav':str(wav),'mp3':str(mp3),'mp3_duration':info.duration,'wav_bytes':wav.stat().st_size,'mp3_bytes':mp3.stat().st_size}
 s.close();s=Studio();assert s.item(item['id'])['favorite'];assert len(s.items(job_id=pair))==2
 report['restart']={'history_preserved':True,'favorite_preserved':True}
 (s.data/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
finally:s.close()
