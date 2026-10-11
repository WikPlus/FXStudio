"""Audit a Windows ZIP and its included license hashes before handoff."""
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def audit_zip(path):
    root = 'FX Studio Windows/resources/app/'
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('ZIP CRC failure: ' + bad)
        for name in archive.namelist():
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in name:
                raise ValueError('Unsafe ZIP path: ' + name)
            if relative.suffix.lower() in {'.wav','.mp3','.safetensors','.tflite','.sqlite','.pyc'} or relative.name in {'agent-access.json','.env'} or relative.name.startswith('studio.sqlite'):
                raise ValueError('Private data/model weights/bytecode in release: ' + name)
            # NumPy ships tiny NPZ test fixtures. Apply the same model-weight
            # guard as the Mac packager rather than rejecting its dependencies.
            if relative.suffix.lower()=='.npz' and (archive.getinfo(name).file_size>1024**2 or '.runtime' in relative.parts):
                raise ValueError('Model weights in release: ' + name)
        for name in ('FX Studio Windows/FX Studio.exe',root+'python/python.exe',root+'tools/ffmpeg.exe'):
            if archive.read(name)[:2] != b'MZ':
                raise ValueError('Missing Windows executable: ' + name)
        inventory = json.loads(archive.read(root+'ui/licenses/inventory.json'))
        if inventory['platform'] != 'win32':
            raise ValueError('Wrong platform license inventory')
        for record in inventory['files']:
            material = PurePosixPath(record['path'])
            if material.is_absolute() or '..' in material.parts or '\\' in record['path']:
                raise ValueError('Unsafe material path')
            if hashlib.sha256(archive.read(root+'ui/licenses/'+record['path'])).hexdigest()!=record['sha256']:
                raise ValueError('Changed license/source file: '+record['path'])
        return {'license_components':len(inventory['components']),'verified_material_files':len(inventory['files'])}


def write_checksum(path):
    path=Path(path)
    with path.open('rb') as stream:
        value=hashlib.file_digest(stream,'sha256').hexdigest()
    path.with_name(path.name+'.sha256').write_text(value+'  '+path.name+'\n')
    return value
