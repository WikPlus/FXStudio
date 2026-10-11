"""Opt-in real editing acceptance. Run while the desktop app is closed."""
import json,sys,time
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from core import Studio
s=Studio();source=s.item('44c4c47e164a');report={}
try:
 for mode,seed in [('variation',42607),('inpaint',42608)]:
  raw={'prompt':'Deep eerie cave ambience with wind and distant water drops, no music or voices','seconds':source['duration'],'mode':mode,'reference_id':source['id'],'strength':.65,'seed':seed,'start':2,'end':4}
  id=s.enqueue(raw)['id'];prior=None
  while True:
   job=next(x for x in s.status()['jobs'] if x['id']==id)
   if job['message']!=prior:print(mode,job['state'],job['message'],flush=True);prior=job['message']
   if job['state'] not in ('queued','running','cancelling'):break
   time.sleep(.05)
  assert job['state']=='completed',job
  item=s.items(job_id=id)[0];audio,rate=sf.read(item['path'],always_2d=True);original,_=sf.read(source['path'],always_2d=True)
  assert np.isfinite(audio).all() and np.max(np.abs(audio))>.001 and len(audio)==len(original)
  report[mode]={'job':job,'item':item,'peak':float(np.max(np.abs(audio)))}
  if mode=='inpaint':
   outside=np.r_[0:rate,int(5*rate):int(7*rate)]
   report[mode]['outside_correlation']=float(np.corrcoef(original[outside].ravel(),audio[outside].ravel())[0,1])
   report[mode]['outside_rms_difference']=float(np.sqrt(np.mean((original[outside]-audio[outside])**2)))
   report[mode]['inside_rms_difference']=float(np.sqrt(np.mean((original[2*rate:4*rate]-audio[2*rate:4*rate])**2)))
 (s.data/'editing-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
finally:s.close()
