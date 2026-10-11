"""Build native audio tools and matching license/source evidence on Windows.

--prepare-only also works on macOS: it downloads/verifies inputs and extracts
notices, but never executes Windows binaries or downloads sound model weights.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.runtime/windows-native'
MATERIALS = ROOT / '.runtime/windows-native-materials'
MANIFEST = ROOT / 'packaging/windows-sources.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(record, target):
    target = Path(target)
    if target.is_file() and digest(target) == record['sha256']:
        return target
    cache = ROOT / '.runtime/legal-cache' / record['file']
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.part')
    if cache.is_file() and digest(cache) == record['sha256']:
        shutil.copyfile(cache, temporary)
    else:
        request = urllib.request.Request(record['url'], headers={'User-Agent': 'FX-Studio-Windows-build'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open('wb') as output:
                    while chunk := response.read(1024**2):
                        output.write(chunk)
                        if output.tell() > record['bytes']:
                            raise ValueError('Unexpected input size: ' + record['file'])
                break
            except (OSError, urllib.error.URLError):
                if attempt == 2:
                    raise
                print('Retrying Windows input:', record['file'], flush=True)
                time.sleep(2)
    if temporary.stat().st_size != record['bytes'] or digest(temporary) != record['sha256']:
        raise ValueError('Input checksum/size mismatch: ' + record['file'])
    temporary.replace(target)
    return target


def notice(name):
    path=Path(name)
    return path.suffix.lower() not in {'.py','.pyc','.obj','.o','.a','.dll','.so','.pyd','.c','.h','.cpp','.exe','.pdb'} and any(word in path.name.lower() for word in ('license', 'licence', 'copying', 'copyright', 'notice', 'authors'))


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive member: ' + name)
    return path


def prepare():
    import zstandard
    manifest = json.loads(MANIFEST.read_text())
    (MATERIALS/'inventory.json').unlink(missing_ok=True)
    for name in ('audio','cpython'):
        shutil.rmtree(MATERIALS/'software'/name,ignore_errors=True)
    for record in manifest['archives']:
        is_python = record['file'].startswith('cpython-')
        archive = fetch(record, (WORK / 'inputs' if is_python else MATERIALS / 'sources') / record['file'])
        print('Verified Windows input:', record['file'], flush=True)
        if is_python:
            continue
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                safe_relative(member.name)
                if member.isfile() and notice(member.name):
                    target = MATERIALS / 'software/audio' / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(tar.extractfile(member).read())
            tar.extractall(WORK / 'source', filter='data')
    # Use the pinned official standalone Python itself, not whatever Python a
    # runner happened to have installed. Its matching full archive has notices
    # for the embedded native libraries omitted from install-only archives.
    with tarfile.open(WORK / 'inputs/cpython-3.11.11-windows-install.tar.gz') as tar:
        for member in tar.getmembers():
            safe_relative(member.name)
            # A later preparation step may itself be running on this pinned
            # Python. Windows locks loaded PYD/DLL files. Reuse a file only
            # after comparing its bytes with the checksum-pinned archive.
            target = WORK / 'runtime' / member.name
            if member.isfile() and target.is_file() and not target.is_symlink():
                expected = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                if digest(target) == expected:
                    continue
            tar.extract(member, WORK / 'runtime', filter='data')
    full = WORK / 'inputs/cpython-3.11.11-windows-full.tar.zst'
    matched_python=False
    with full.open('rb') as compressed, zstandard.ZstdDecompressor().stream_reader(compressed) as decoded:
        with tarfile.open(fileobj=decoded, mode='r|') as tar:
            for member in tar:
                safe_relative(member.name)
                if member.name=='python/install/python.exe':
                    full_sha=hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                    if full_sha!=digest(WORK/'runtime/python/python.exe'):
                        raise ValueError('Install-only Python differs from its matching full-release binary.')
                    matched_python=True
                if member.isfile() and (notice(member.name) or member.name.endswith('/PYTHON.json')):
                    target = MATERIALS / 'software/cpython' / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(tar.extractfile(member).read())
    python_license = WORK / 'runtime/python/LICENSE.txt'
    if not python_license.is_file():
        raise ValueError('Pinned Windows Python has no LICENSE.txt')
    shutil.copy2(python_license, MATERIALS / 'software/cpython/LICENSE.txt')
    if not matched_python:
        raise ValueError('Full Windows Python archive has no matching install/python.exe.')
    (MATERIALS/'software/cpython/PROVENANCE.json').write_text(json.dumps({
        'version':manifest['python_version'],'release':manifest['python_release'],
        'python_exe_sha256':digest(WORK/'runtime/python/python.exe'),
        'full_release_binary_match':True,
        'archives':[r for r in manifest['archives'] if r['file'].startswith('cpython-')]},indent=2)+'\n')
    for record in manifest['sentencepiece_texts'] + manifest.get('additional_texts', []):
        fetch(record, MATERIALS / 'software' / record['file'])
    shutil.copy2(MANIFEST, MATERIALS / 'sources/source-manifest.json')
    for name in ('prepare_windows_native.py',):
        shutil.copy2(ROOT / 'scripts' / name, MATERIALS / 'sources' / name)
    shutil.copy2(ROOT / 'packaging/build-windows-audio.sh', MATERIALS / 'sources/build-windows-audio.sh')
    (MATERIALS / 'README.md').write_text(
        '# Windows native software\n\n'
        'CPython 3.11.11, official 20250317 Windows x64 release, with its matching embedded-library notices.\n'
        'Audio tools are compiled from the checksum-pinned, unmodified source archives here.\n'
        'FFmpeg is LGPL 2.1 or later; its statically linked LAME is LGPL 2.0 or later.\n'
        'libsndfile is shared, with statically linked LGPL/BSD codecs.\n'
        'Rebuild in MSYS2 MINGW64 with sources/build-windows-audio.sh; build.json records the actual compiler and binary hashes.\n'
        'You may modify/replace these LGPL tools and debug those changes. No FX Studio restriction prohibits that.\n'
        'Windows native build and model generation are different checks; see acceptance reports.\n')
    return manifest


def build(msys_root):
    if sys.platform != 'win32':
        raise ValueError('Native compilation needs Windows x64; --prepare-only is available on macOS.')
    msys_root = Path(msys_root).resolve()
    for name in ('build','prefix','bin'):
        shutil.rmtree(WORK/name,ignore_errors=True)
    bash = msys_root / 'usr/bin/bash.exe'
    environment = {**os.environ, 'MSYSTEM': 'MINGW64', 'CHERE_INVOKING': '1', 'MSYS2_PATH_TYPE': 'minimal'}
    # bash accepts its POSIX /c/... path. Do not construct shell commands from
    # external input; the recipe and build directory are separate arguments.
    recipe = str((ROOT / 'packaging/build-windows-audio.sh').resolve()).replace('\\', '/')
    recipe = '/' + recipe[0].lower() + recipe[2:] if len(recipe) > 1 and recipe[1] == ':' else recipe
    subprocess.run([str(bash), '-l', recipe, str(WORK)], check=True, env=environment)
    python = ROOT / '.venv/Scripts/python.exe'
    if not python.is_file():
        raise ValueError('Prepare the pinned Windows .venv before finalizing native materials.')
    ffmpeg = WORK / 'bin/ffmpeg.exe'
    output = subprocess.run([str(ffmpeg), '-L'], check=True, capture_output=True, text=True).stdout
    if 'GNU Lesser General Public License' not in ' '.join(output.split()):
        raise ValueError('Windows FFmpeg is not the requested LGPL build.')
    dlls = list((WORK / 'prefix/bin').glob('*sndfile*.dll'))
    if len(dlls) != 1:
        raise ValueError('Expected one locally compiled libsndfile DLL.')
    site = ROOT / '.venv/Lib/site-packages'
    target = site / '_soundfile_data/libsndfile_x64.dll'
    if not target.is_file():
        raise ValueError('SoundFile wheel layout changed; resolve its actual DLL before building.')
    shutil.copy2(dlls[0], target)
    # Fail for MinGW runtime DLL dependencies rather than accidentally relying
    # on a compiler installed on the end user's machine.
    objdump = msys_root / 'mingw64/bin/objdump.exe'
    dependencies = {}
    for binary in (ffmpeg, target):
        pe = subprocess.run([str(objdump), '-p', str(binary)], check=True, capture_output=True, text=True).stdout
        imports = [line.split('DLL Name:', 1)[1].strip() for line in pe.splitlines() if 'DLL Name:' in line]
        allowed = {'kernel32.dll', 'msvcrt.dll', 'ucrtbase.dll', 'user32.dll', 'advapi32.dll', 'shell32.dll', 'shlwapi.dll', 'ole32.dll', 'ws2_32.dll', 'bcrypt.dll', 'secur32.dll'}
        if any(name.lower() not in allowed and not name.lower().startswith('api-ms-win-') for name in imports):
            raise ValueError('Unexpected non-system DLL dependencies: ' + str(imports))
        dependencies[binary.name] = imports
    subprocess.run([str(python), '-I', '-c',
        'import soundfile as s; assert s.__libsndfile_version__ == "1.2.2"; '
        'assert all(f in s.available_formats() for f in ("WAV", "FLAC", "OGG", "MP3")); print(s.available_formats())'], check=True)
    crypto_openssl = subprocess.run([str(python), '-I', '-c',
        'from cryptography.hazmat.bindings.openssl.binding import Binding; '
        'b=Binding(); print(b.ffi.string(b.lib.OpenSSL_version(0)).decode())'],
        check=True, capture_output=True, text=True).stdout.strip()
    if not crypto_openssl.startswith('OpenSSL 4.0.3 '):
        raise ValueError('Resolve matching cryptography OpenSSL notices: ' + crypto_openssl)
    toolchain = MATERIALS / 'software/toolchain'
    for folder in (msys_root / 'mingw64/share/licenses', msys_root / 'usr/share/licenses'):
        if folder.is_dir():
            shutil.copytree(folder, toolchain / folder.parent.parent.name, dirs_exist_ok=True)
    if not any(p.is_file() and notice(p.name) for p in toolchain.rglob('*')):
        raise ValueError('Missing MinGW/runtime license texts.')
    for name in ('compiler.txt', 'msys2-packages.txt'):
        shutil.copy2(WORK / name, MATERIALS / 'sources' / name)
    for name in ('config.h', 'config_components.h', 'config.mak'):
        shutil.copy2(WORK / 'bin' / name, MATERIALS / 'sources' / name)
    records = [{'path': 'tools/ffmpeg.exe', 'sha256': digest(ffmpeg)},
               {'path': 'python/Lib/site-packages/_soundfile_data/libsndfile_x64.dll', 'sha256': digest(target)}]
    python_root=WORK/'runtime/python'
    core_binaries=[python_root/'python.exe',*python_root.glob('*.dll'),*(python_root/'DLLs').glob('*.pyd'),*(python_root/'DLLs').glob('*.dll')]
    records.extend({'path':'python/'+p.relative_to(python_root).as_posix(),'sha256':digest(p)} for p in core_binaries)
    build_info = {'platform': 'win32', 'source_changes': 'None; configure/CMake options in the supplied recipe.',
                  'binaries': records, 'system_dependencies': dependencies,
                  'compiler': (WORK / 'compiler.txt').read_text(), 'python_source_release': '20250317'}
    build_info['cryptography_openssl'] = crypto_openssl
    (MATERIALS / 'sources/build.json').write_text(json.dumps(build_info, indent=2) + '\n')
    components = []
    for name, version, license, prefix in [
        ('CPython and embedded native libraries', '3.11.11', 'PSF and upstream terms', 'software/cpython'),
        ('SentencePiece', '0.2.1', 'Apache-2.0 and supplied notices', 'software/sentencepiece-0.2.1'),
        ('OpenSSL in cryptography', '4.0.3', 'Apache-2.0', 'software/openssl-4.0.3'),
        ('FFmpeg / LAME / libsndfile and linked audio codecs', '8.0.1 / 3.100 / 1.2.2', 'LGPL and supplied BSD terms', 'software/audio'),
        ('MinGW runtime and build tool notices', 'recorded in msys2-packages.txt', 'Upstream terms and GCC Runtime Library Exception', 'software/toolchain')]:
        texts = [p.relative_to(MATERIALS).as_posix() for p in sorted((MATERIALS / prefix).rglob('*')) if p.is_file() and notice(p.name)]
        if not texts:
            raise ValueError('No license texts for ' + name)
        components.append({'name': name, 'version': version, 'license': license, 'license_files': texts,
                           'source': 'Original URLs and SHA-256 in sources/source-manifest.json; complete audio sources and native build recipe supplied.'})
    inventory = {'schema': 1, 'platform': 'win32', 'components': components, 'binaries': records,
                 'files': [{'path': p.relative_to(MATERIALS).as_posix(), 'sha256': digest(p)} for p in sorted(MATERIALS.rglob('*')) if p.is_file() and p.name != 'inventory.json']}
    (MATERIALS / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    from collect_licenses import validate_license_bundle
    validate_license_bundle(MATERIALS)
    print('Windows audio binaries and matching native license/source inventory verified.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--msys-root', default='C:/msys64')
    args = parser.parse_args()
    prepare()
    if not args.prepare_only:
        build(args.msys_root)


if __name__ == '__main__':
    main()
