"""Tiny subprocess fixture. Only test temporary directories receive its output."""
import json, math, os, signal, struct, subprocess, sys, time, wave
from pathlib import Path
prompt,target,seconds=sys.argv[1:]
seconds=float(seconds)
print('FX_EVENT '+json.dumps({'stage':3,'step':1,'total':8}),flush=True)
if prompt=='failure':
 print('deliberate process failure',flush=True);sys.exit(9)
if prompt=='stubborn':
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(90)'])
 Path(target+'.child').write_text(str(child.pid))
 time.sleep(90)
else:
 time.sleep(.25)
 with wave.open(target,'wb') as out:
  out.setparams((2,2,44100,0,'NONE','not compressed'))
  frames=int(seconds*44100) if prompt!='incomplete' else 10
  out.writeframes(b''.join(struct.pack('<hh',int(2000*math.sin(i*.04)),int(2000*math.sin(i*.04))) for i in range(frames)))
