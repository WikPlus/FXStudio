"""Build a self-contained Windows x64 app on Windows; never download models."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from collect_licenses import collect
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'dist/FX Studio Windows'
APP=TARGET/'resources/app'


def copy_tree(source,target,extra=()):
    shutil.copytree(source,target,symlinks=False,dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store','.git',*extra))


def main():
    if sys.platform!='win32' or platform.machine().lower() not in ('amd64','x86_64'):
        raise SystemExit('Build this package on Windows x64. The macOS build remains separate.')
    parser=argparse.ArgumentParser();parser.add_argument('--ffmpeg');parser.add_argument('--native-license-dir');args=parser.parse_args()
    if sys.prefix==sys.base_prefix:raise SystemExit('Build with the managed .venv Python, via Build-Windows.ps1.')
    electron=ROOT/'node_modules/electron/dist'
    runtime=ROOT/'.runtime/stable-audio-3-windows/optimized/tflite'
    ffmpeg=Path(args.ffmpeg or shutil.which('ffmpeg') or '')
    if not (electron/'electron.exe').is_file():
        raise SystemExit('The Electron executable is missing. Run node node_modules/electron/install.js before packaging.')
    if not (runtime/'scripts/sa3_tflite.py').is_file():
        raise SystemExit('The pinned CPU source is missing. Run scripts/prepare_windows.py before packaging.')
    if not ffmpeg.is_file():raise SystemExit('Provide a Windows FFmpeg executable: Build-Windows.ps1 -FFmpegPath C:\\path\\ffmpeg.exe')
    if not args.native_license_dir:
        raise SystemExit('Supply -NativeLicenseDir with the selected Windows binaries\' matching license texts, sources and inventory. See packaging/GITHUB-RELEASE.md. No incomplete release ZIP is produced.')
    if TARGET.exists():shutil.rmtree(TARGET)
    copy_tree(electron,TARGET)
    (TARGET/'electron.exe').rename(TARGET/'FX Studio.exe')
    default=TARGET/'resources/default_app.asar'
    if default.exists():default.unlink()
    APP.mkdir(parents=True)
    for folder in ('backend','ui','desktop'):copy_tree(ROOT/folder,APP/folder,('launcher.c',))
    # These are Mac-specific seeds; the Windows collector adds the actual
    # Windows package/native notices rather than implying Mac binary evidence.
    shutil.rmtree(APP/'ui/licenses/software',ignore_errors=True)
    (APP/'scripts').mkdir();shutil.copy2(ROOT/'scripts/download_models.py',APP/'scripts/download_models.py')
    package=json.loads((ROOT/'package.json').read_text())
    (APP/'package.json').write_text(json.dumps({key:package[key] for key in ('name','version','main','description','license')},indent=2)+'\n')
    copy_tree(Path(sys.base_prefix),APP/'python',('include','Scripts'))
    if (APP/'python/Lib/site-packages').exists():shutil.rmtree(APP/'python/Lib/site-packages')
    copy_tree(Path(sysconfig.get_paths()['purelib']),APP/'python/Lib/site-packages',('_virtualenv.py','_virtualenv.pth'))
    copy_tree(runtime,APP/'.runtime/stable-audio-3-windows/optimized/tflite',('*.tflite','output','build','docs'))
    shutil.copy2(runtime.parents[1]/'LICENSE',APP/'.runtime/stable-audio-3-windows/LICENSE')
    tools=APP/'tools';tools.mkdir();shutil.copy2(ffmpeg,tools/'ffmpeg.exe')
    for dll in ffmpeg.parent.glob('*.dll'):shutil.copy2(dll,tools/dll.name)
    license_inventory=collect(APP,TARGET/'resources',electron,APP/'python/Lib/site-packages',
                              'win32',native_materials=Path(args.native_license_dir))
    (TARGET/'resources/build.json').write_text(json.dumps({'platform':'win32','architecture':'x64','runtime':'Official LiteRT CPU','python':sys.version.split()[0],'weights_bundled':False,'standalone':True,'license_inventory':license_inventory,'windows_acceptance':'native_smoke_pending','model_generation':'not_run'},indent=2)+'\n')
    python=APP/'python/python.exe'
    with tempfile.TemporaryDirectory() as temp:
        environment={**os.environ,'PYTHONNOUSERSITE':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        for key in ('PYTHONHOME','PYTHONPATH'):environment.pop(key,None)
        subprocess.run([str(python),'-s','-B','-c','import ai_edge_litert,numpy,soundfile,sentencepiece,huggingface_hub,mcp; print("Bundled Windows CPU dependencies import successfully")'],check=True,cwd=temp,env=environment)
    subprocess.run([sys.executable,str(ROOT/'scripts/verify_windows.py'),'--bundle',str(TARGET)],check=True)
    metadata=json.loads((TARGET/'resources/build.json').read_text());metadata['windows_acceptance']='native_runtime_and_export_passed'
    (TARGET/'resources/build.json').write_text(json.dumps(metadata,indent=2)+'\n')
    archive=shutil.make_archive(str(ROOT/'dist/FXStudio-Windows-x64'),'zip',TARGET.parent,TARGET.name)
    from package_windows import audit_zip, write_checksum
    audit_zip(archive);write_checksum(archive)
    print('Built and audited portable package:',archive)
    compiler=shutil.which('ISCC')
    if not compiler:
        candidate=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Inno Setup 6/ISCC.exe'
        if candidate.is_file():compiler=str(candidate)
    if compiler:
        subprocess.run([compiler,str(ROOT/'packaging/windows.iss')],check=True)
        installer=ROOT/'dist/FXStudio-Windows-x64-Setup.exe'
        subprocess.run([sys.executable,str(ROOT/'scripts/verify_windows.py'),'--installer',str(installer)],check=True)
        write_checksum(installer)
    else:print('For a Setup.exe installer, install official Inno Setup and compile packaging/windows.iss. The ZIP is already self-contained.')


if __name__=='__main__':main()
