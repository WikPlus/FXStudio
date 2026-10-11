"""Build a relocatable Apple Silicon app from the installed, pinned runtimes.

No downloads, model weights, user data, source-checkout pointers or venv links
are included. Models are linked from the user's verified cache on first launch.
"""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from collect_licenses import collect
from macos_runtime import MACH_HEADERS, minimum_macos

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'dist/FX Studio.app'
APP = TARGET / 'Contents/Resources/app'


def run(*args, capture=False):
    return subprocess.run([str(arg) for arg in args], check=True,
                          capture_output=capture, text=True)


def copy_tree(source, target, extra=()):
    shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.git', *extra))


def dependencies(binary):
    lines = run('/usr/bin/otool', '-L', binary, capture=True).stdout.splitlines()[1:]
    return [line.strip().split(' (compatibility')[0] for line in lines if line.strip()]


def system_library(path):
    return path.startswith(('/usr/lib/', '/System/Library/'))


def bundle_ffmpeg(source):
    tools = APP / 'tools'
    libs = tools / 'lib'
    libs.mkdir(parents=True)
    shutil.copy2(source.resolve(), tools / 'ffmpeg')
    pending = [(source.resolve(), tools / 'ffmpeg')]
    copied = {}
    while pending:
        original, bundled = pending.pop()
        for dependency in dependencies(original):
            if system_library(dependency):
                continue
            if dependency.startswith('@loader_path/'):
                resolved = (original.parent / dependency[len('@loader_path/'):]).resolve()
            elif dependency.startswith('/'):
                resolved = Path(dependency).resolve()
            else:
                raise RuntimeError(f'Unresolved library dependency: {dependency} in {original.name}')
            # otool also prints a dylib's own install ID.
            if resolved == original:
                continue
            if not resolved.is_file():
                raise RuntimeError(f'Missing library: {resolved}')
            name = resolved.name
            if name in copied and copied[name] != resolved:
                raise RuntimeError(f'Duplicate library name: {name}')
            if name not in copied:
                copied[name] = resolved
                shutil.copy2(resolved, libs / name)
                (libs / name).chmod(0o755)
                pending.append((resolved, libs / name))
            replacement = '@loader_path/' + ('lib/' if bundled.parent == tools else '') + name
            run('/usr/bin/install_name_tool', '-change', dependency, replacement, bundled, capture=True)
        if bundled.parent == libs:
            run('/usr/bin/install_name_tool', '-id', '@rpath/' + bundled.name, bundled, capture=True)
    for binary in [tools / 'ffmpeg', *libs.iterdir()]:
        # Reject accidental dependencies on Homebrew or another checkout.
        for dependency in dependencies(binary):
            if not system_library(dependency) and not dependency.startswith(('@loader_path/', '@rpath/')):
                raise RuntimeError(f'External dependency remains in {binary.name}: {dependency}')
    return copied


def sign_embedded_runtime():
    for folder in (APP / 'python', APP / 'tools'):
        for path in folder.rglob('*'):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as stream:
                is_mach = stream.read(4) in MACH_HEADERS
            if is_mach:
                run('/usr/bin/codesign', '--force', '--sign', '-', path, capture=True)


def main():
    if sys.platform != 'darwin' or os.uname().machine != 'arm64':
        raise SystemExit('This build requires an Apple Silicon Mac.')
    electron = ROOT / 'node_modules/electron/dist/Electron.app'
    base_python = Path(sys.base_prefix)
    site_packages = Path(sysconfig.get_paths()['purelib'])
    runtime = ROOT / '.runtime/stable-audio-3/optimized/mlx'
    exporter = ROOT / '.runtime/audio-exporter'
    ffmpeg = exporter / 'bin/ffmpeg'
    for source in (electron, base_python / 'bin/python3', site_packages / 'mlx',
                   runtime / 'scripts/sa3_mlx.py', ffmpeg):
        if not source.exists():
            raise SystemExit(f'Missing build dependency: {source}. Run Einrichten.command; for the release exporter run .venv/bin/python scripts/prepare_audio_exporter.py.')
    if base_python == Path(sys.prefix):
        raise SystemExit('Build using the project .venv Python, backed by uv standalone Python.')
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    print('Packaging Electron, Python and MLX …', flush=True)
    run('/bin/cp', '-cR', electron, TARGET)
    resources = TARGET / 'Contents/Resources'
    for old in ('default_app.asar', 'app'):
        path = resources / old
        if path.is_dir(): shutil.rmtree(path)
        elif path.exists(): path.unlink()
    APP.mkdir()
    for folder in ('backend', 'ui', 'desktop'):
        copy_tree(ROOT / folder, APP / folder, extra=('launcher.c',))
    (APP / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/download_models.py', APP / 'scripts/download_models.py')
    package = json.loads((ROOT / 'package.json').read_text())
    (APP / 'package.json').write_text(json.dumps({key: package[key] for key in ('name', 'version', 'main', 'description', 'license')}, indent=2) + '\n')
    copy_tree(base_python, APP / 'python', extra=('include',))
    python_site = APP / 'python/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    # Build-only pip/setuptools are not needed by the desktop runtime.
    if python_site.exists():
        shutil.rmtree(python_site)
    copy_tree(site_packages, python_site, extra=('_virtualenv.py', '_virtualenv.pth'))
    copy_tree(runtime, APP / '.runtime/stable-audio-3/optimized/mlx', extra=('mlx', '*.npz', '*.safetensors'))
    source_repo = ROOT / '.runtime/stable-audio-3'
    for name in ('LICENSE', 'README.md'):
        if (source_repo / name).is_file():
            shutil.copy2(source_repo / name, APP / '.runtime/stable-audio-3' / name)
    print('Bundling FFmpeg and its library dependencies …', flush=True)
    ffmpeg_libraries = bundle_ffmpeg(ffmpeg)
    print('Collecting license texts and corresponding source archives …', flush=True)
    license_inventory = collect(APP, resources, ROOT / 'node_modules/electron/dist', python_site,
                                'darwin', exporter=exporter)
    print('Compiling the native launcher and signing the app …', flush=True)
    run('/usr/bin/xcrun', 'clang', '-arch', 'arm64', '-O2', '-Wall', '-Wextra',
        ROOT / 'desktop/launcher.c', '-o', TARGET / 'Contents/MacOS/FXStudio')
    minimum_os = minimum_macos(TARGET)
    plist = TARGET / 'Contents/Info.plist'
    with plist.open('rb') as stream: info = plistlib.load(stream)
    info.update(CFBundleExecutable='FXStudio', CFBundleName='FX Studio',
                CFBundleDisplayName='FX Studio', CFBundleIdentifier='com.fxstudio.desktop',
                CFBundleShortVersionString=package['version'], CFBundleVersion=package['version'],
                CFBundleDevelopmentRegion='en', CFBundleLocalizations=['en'],
                CFBundleIconFile='fxstudio.icns', LSMinimumSystemVersion=minimum_os)
    from app_icon import write_icon
    write_icon(resources / 'fxstudio.icns')
    with plist.open('wb') as stream: plistlib.dump(info, stream)
    # Every symlink must stay within the bundle; models belong in Application Support.
    for path in TARGET.rglob('*'):
        if path.is_symlink() and (Path(os.readlink(path)).is_absolute() or not path.resolve().is_relative_to(TARGET)):
            raise RuntimeError(f'External symlink in app: {path.relative_to(TARGET)}')
    manifest = {'version': package['version'], 'architecture': 'arm64', 'minimum_macos': minimum_os,
                'electron': (ROOT / 'node_modules/electron/dist/version').read_text().strip(),
                'python': sys.version.split()[0], 'bundled_ffmpeg_libraries': sorted(ffmpeg_libraries),
                'ffmpeg_license': 'LGPL-2.1-or-later', 'license_inventory': license_inventory,
                'weights_bundled': False, 'standalone': True}
    (resources / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    sign_embedded_runtime()
    run('/usr/bin/codesign', '--force', '--deep', '--sign', '-', TARGET, capture=True)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', TARGET, capture=True)
    print(f'Built and verified: {TARGET}', flush=True)


if __name__ == '__main__':
    main()
