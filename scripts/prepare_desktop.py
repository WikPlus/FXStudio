"""Create a local macOS app with a distinct identity; keep models outside it."""
import json, plistlib, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'node_modules/electron/dist/Electron.app'
target=ROOT/'.runtime/FX Studio.app'
version=(ROOT/'node_modules/electron/dist/version').read_text().strip()
marker=target/'Contents/Resources/fx-runtime-version'
if not source.is_dir():raise SystemExit('Electron is missing. Run Einrichten.command.')
if marker.is_file() and marker.read_text().strip()==version:
 plist=target/'Contents/Info.plist'
 with plist.open('rb') as stream:info=plistlib.load(stream)
 if info.get('CFBundleDevelopmentRegion')!='en' or info.get('CFBundleLocalizations')!=['en']:
  info.update(CFBundleDevelopmentRegion='en',CFBundleLocalizations=['en'])
  with plist.open('wb') as stream:plistlib.dump(info,stream)
  subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(target)],check=True)
 print('FX Studio.app is already set up.');raise SystemExit(0)
if target.exists():
 import shutil
 shutil.rmtree(target)
target.parent.mkdir(exist_ok=True)
# APFS clone: the original runtime remains available without a second full allocation.
subprocess.run(['/bin/cp','-cR',str(source),str(target)],check=True)
plist=target/'Contents/Info.plist'
with plist.open('rb') as stream:info=plistlib.load(stream)
info.update(CFBundleName='FX Studio',CFBundleDisplayName='FX Studio',CFBundleIdentifier='com.fxstudio.desktop',CFBundleShortVersionString='0.1.0',CFBundleDevelopmentRegion='en',CFBundleLocalizations=['en'])
with plist.open('wb') as stream:plistlib.dump(info,stream)
resources=target/'Contents/Resources'
packaged=resources/'app';packaged.mkdir(exist_ok=True)
(packaged/'package.json').write_text(json.dumps({'name':'fx-studio','version':'0.1.0','main':'main.cjs'}))
# The launcher resolves its sibling repository when the whole folder is moved.
(packaged/'main.cjs').write_text("const {join}=require('path'); require(join(process.resourcesPath,'..','..','..','..','desktop','main.cjs'));\n")
marker.write_text(version)
subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-',str(target)],check=True)
print('Local FX Studio.app prepared (Electron '+version+').')
