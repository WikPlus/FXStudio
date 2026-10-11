"""Native isolated Windows acceptance. Model inference requires --generate.

Smoke checks use clearly identified synthetic test audio. The real generation
check downloads only the pinned Medium files and runs the actual LiteRT worker.
No test writes to the user's normal FX Studio data or uploads audio.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CHECK=r'''
import json,os,sys,time,math,urllib.request,secrets,socket,subprocess
from pathlib import Path
app=Path(sys.argv[1]);folder=Path(sys.argv[2]);generate=sys.argv[3]=='1'
sys.path.insert(0,str(app/'backend'))
import numpy as np, soundfile as sf, ai_edge_litert, sentencepiece, huggingface_hub,mcp
for module in (np,sf,ai_edge_litert,sentencepiece,huggingface_hub,mcp):
    assert Path(module.__file__).resolve().is_relative_to(app), module.__file__
assert Path(sys.prefix).resolve().is_relative_to(app)
from core import Studio
from runtime_paths import runtime_kind
assert runtime_kind()=='tflite'
library=folder/'library';library.mkdir()
samples=np.sin(np.arange(44100)*.04)*.7
sf.write(library/'synthetic.wav',np.stack((samples,samples),axis=1),44100)
(library/'katalog.json').write_text(json.dumps({'assets':[{'id':'SFX0001','path':'synthetic.wav','duration_seconds':1,'source':{'original_filename':'synthetic.wav'},'license':{'name':'Synthetic temporary test audio','status':'documented_bundle'}}]}))
studio=Studio(data_dir=folder/'data',library_root=library)
try:
    status=studio.status();assert status['packaged'] and status['model']['runtime']=='CPU'
    assert status['model']['runtime_ready'] and not status['model']['dependencies'],status['model']
    project=studio.create_project({'name':'Windows acceptance'})
    studio.set_project_sound(project['id'],'SFX0001')
    studio.set_trim('SFX0001',{'start':.1,'end':.3})
    dragged=studio.prepare_drag('SFX0001');assert Path(dragged['path']).is_file()
    audio,rate=sf.read(dragged['path'],always_2d=True)
    assert rate==44100 and len(audio)==8820 and audio.shape[1]==2
    assert np.isfinite(audio).all() and (audio[[0,-1]]==0).all()
    mp3=folder/'crop.mp3';studio.convert(Path(dragged['path']),mp3,'mp3')
    decoded=folder/'decoded.wav';studio.convert(mp3,decoded,'wav')
    check,rate=sf.read(decoded,always_2d=True)
    assert mp3.stat().st_size>1000 and rate==44100 and check.shape[1]==2 and np.isfinite(check).all()
    report={'platform':'win32','standalone':True,'runtime':'Official LiteRT CPU','trim_export_drag_path':True,'mp3_roundtrip':True,'model_generation':'not_run','synthetic_audio_used_only_for_smoke':True}
    if generate:
        from models import weight_spec
        from model_download import download_bundle
        from runtime_paths import model_folder
        download_bundle(weight_spec(runtime='tflite'),model_folder())
        assert studio.model_status()['ready']
        started=time.monotonic()
        job_id=studio.enqueue({'model':'medium','prompt':'A DSLR camera shutter firing once. A crisp mechanical snap followed by a tiny spring click, with a compact midrange body and a very fast decay. Recorded close in an acoustically dead room.','seconds':1,'steps':8,'cfg':1,'seed':52611})['id']
        while True:
            job=next(j for j in studio.status()['jobs'] if j['id']==job_id)
            if job['state'] not in ('queued','running','cancelling'):break
            time.sleep(.2)
        assert job['state']=='completed',job
        item=studio.items(job_id=job_id)[0]
        audio,rate=sf.read(item['path'],always_2d=True)
        assert rate==44100 and audio.shape==(44100,2) and np.isfinite(audio).all()
        assert np.max(np.abs(audio))>.001
        studio.convert(Path(item['path']),folder/'real-medium.mp3','mp3')
        report.update(model_generation='passed',generation_seconds=round(time.monotonic()-started,2),sample_rate=rate,peak=float(np.max(np.abs(audio))))
    studio.close();studio=Studio(data_dir=folder/'data',library_root=library)
    assert len(studio.project_items(project['id']))==1 and studio.item('SFX0001')['trim']
    report['restart_persistence']=True
finally:studio.close()
# Start the actual bundled service, from a different directory and minimal PATH.
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
token=secrets.token_hex(24)
env={**os.environ,'FX_PORT':str(port),'FX_DATA_DIR':str(folder/'service'),'FX_LIBRARY_ROOT':str(library),'FX_SESSION_TOKEN':token,'FX_AUTO_SETUP':'0'}
with (folder/'service-output.txt').open('w') as log:
    service=subprocess.Popen([sys.executable,'-s','-B',str(app/'backend/server.py')],cwd=folder,env=env,stdout=log,stderr=log)
    try:
        end=time.monotonic()+30
        while time.monotonic()<end:
            try:
                req=urllib.request.Request(f'http://127.0.0.1:{port}/api/status',headers={'X-FX-Token':token})
                with urllib.request.urlopen(req,timeout=1) as response:state=json.load(response)
                assert state['ready'] and state['service']=='fx-studio';break
            except OSError:
                if service.poll() is not None:raise AssertionError((folder/'service-output.txt').read_text())
                time.sleep(.1)
        else:raise AssertionError('Bundled service did not start')
        report['bundled_service_start']=True
        # Exercise the actual packaged stdio adapter and CLI against this
        # isolated service, including its real opt-in credential handling.
        req=urllib.request.Request(f'http://127.0.0.1:{port}/api/agents',
            data=json.dumps({'enabled':True}).encode(),
            headers={'X-FX-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response:json.load(response)
        import asyncio
        async def check_mcp():
            from mcp import Client,StdioServerParameters
            params=StdioServerParameters(command=sys.executable,
                args=['-s','-B',str(app/'backend/mcp_server.py')],
                env={**env,'FX_AGENT_NO_LAUNCH':'1'},cwd=str(folder))
            async with Client(params) as client:
                tools=await client.list_tools();assert len(tools.tools)==20
                state=await client.call_tool('get_status')
                assert not state.is_error and state.structured_content['ready']
                guide=await client.call_tool('get_prompt_guide')
                assert not guide.is_error and 'Camera shutter' in str(guide.structured_content)
                created=await client.call_tool('create_project',{'name':'Packaged MCP project'})
                assert not created.is_error and created.structured_content['id']
                project=await client.call_tool('get_project',{'project_id':created.structured_content['id']})
                assert not project.is_error
                return guide.structured_content['guide']
        guide_text=asyncio.run(check_mcp())
        cli=subprocess.run([sys.executable,'-s','-B',str(app/'backend/agent_cli.py'),'status'],
            cwd=folder,env={**env,'FX_AGENT_NO_LAUNCH':'1'},check=True,capture_output=True,text=True,encoding='utf-8')
        assert json.loads(cli.stdout)['ready']
        cli_guide=subprocess.run([sys.executable,'-s','-B',str(app/'backend/agent_cli.py'),'guide'],
            cwd=folder,env={**env,'FX_AGENT_NO_LAUNCH':'1'},check=True,capture_output=True,text=True,encoding='utf-8')
        assert json.loads(cli_guide.stdout)['guide']==guide_text
        report.update(bundled_mcp_20_tools=True,bundled_mcp_project_workflow=True,bundled_agent_cli=True)
    finally:service.terminate();service.wait(timeout=15)
print(json.dumps(report))
'''


def verify(bundle,generate=False):
    app=Path(bundle).resolve()/'resources/app'
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','FX_'))}
    env.update(PATH=os.environ.get('SystemRoot','C:/Windows')+'/System32',
               PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
               FX_AUTO_SETUP='0',FX_PACKAGED_RUNTIME='1',FX_FFMPEG_PATH=str(app/'tools/ffmpeg.exe'),
               HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1')
    if not generate:env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    with tempfile.TemporaryDirectory(prefix='fx-windows-check-') as temp:
        env['FX_MODEL_DIR']=str(Path(temp)/'models')
        env['HF_HOME']=str(Path(temp)/'hf-cache')
        result=subprocess.run([str(app/'python/python.exe'),'-I','-B','-c',CHECK,str(app),temp,'1' if generate else '0'],
                              cwd=temp,env=env,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
        return json.loads(result.stdout.splitlines()[-1])


def main():
    if sys.platform!='win32':raise SystemExit('This acceptance must execute natively on Windows.')
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',default=str(ROOT/'dist/FX Studio Windows'))
    parser.add_argument('--installer');parser.add_argument('--generate',action='store_true');args=parser.parse_args()
    if args.installer:
        with tempfile.TemporaryDirectory(prefix='fx-installer-') as temp:
            target=Path(temp)/'FX Studio'
            subprocess.run([str(Path(args.installer).resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-', '/DIR='+str(target)],check=True)
            try:
                assert (target/'FX Studio.exe').is_file()
                report=verify(target)
                report['silent_installer']='passed'
            finally:
                uninstaller=target/'unins000.exe'
                if uninstaller.is_file():subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True)
        name='windows-installer-acceptance.json'
    else:
        report=verify(args.bundle,args.generate)
        name='windows-model-acceptance.json' if args.generate else 'windows-bundle-acceptance.json'
    path=ROOT/'.runtime'/name;path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
