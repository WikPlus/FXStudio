"""Fetch the pinned official CPU runtime, never download sound model weights."""
import hashlib
import json
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    manifest=json.loads((ROOT/'scripts/windows_runtime.json').read_text())
    folder=ROOT/'.runtime/stable-audio-3-windows'
    for file in manifest['files']:
        relative=Path(file['path'])
        if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Invalid runtime path')
        target=folder/relative
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==file['sha256']:continue
        url='https://raw.githubusercontent.com/Stability-AI/stable-audio-3/'+manifest['revision']+'/'+file['path']
        request=urllib.request.Request(url,headers={'User-Agent':'FX-Studio-runtime-setup'})
        with urllib.request.urlopen(request,timeout=45) as response:data=response.read(8*1024**2+1)
        if len(data)>8*1024**2 or hashlib.sha256(data).hexdigest()!=file['sha256']:raise RuntimeError('Runtime integrity check failed: '+file['path'])
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (folder/'revision.txt').write_text(manifest['revision']+'\n')
    print('Pinned official CPU runtime verified. No sound models downloaded.')


if __name__=='__main__':main()
