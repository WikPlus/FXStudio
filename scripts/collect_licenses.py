"""Collect and verify the licenses of the software actually put in a bundle.

Runs offline during builds. Missing license texts or corresponding source
archives fail the build instead of producing an incomplete release package.
"""
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def license_file(path):
    name = Path(path).name.lower()
    return any(token in name for token in ('license', 'licence', 'copying', 'copyright', 'notice', 'authors')) and Path(path).suffix not in {'.py', '.pyc'}


def validate_license_bundle(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'inventory.json').read_text())
    if manifest.get('schema') != 1 or not manifest.get('components'):
        raise ValueError('Missing software license inventory.')
    for component in manifest['components']:
        if not component.get('license_files'):
            raise ValueError('No license texts for ' + component['name'])
    for record in manifest['files']:
        path = (folder / record['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or sha256(path) != record['sha256']:
            raise ValueError('Missing or changed license/source material: ' + record['path'])
    for component in manifest['components']:
        for name in component['license_files']:
            if name not in {record['path'] for record in manifest['files']}:
                raise ValueError('Untracked license text: ' + name)
    return manifest


def collect(app, resources, electron, python_site, platform, exporter=None, native_materials=None):
    app, resources, electron, python_site = map(Path, (app, resources, electron, python_site))
    folder = app / 'ui/licenses'
    components = []

    def copy(source, relative):
        source = Path(source)
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError('Missing license/source material: ' + str(source))
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return str(Path(relative).as_posix())

    def component(name, version, license, files, source):
        components.append({'name': name, 'version': version, 'license': license,
                           'license_files': files, 'source': source})

    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, app / name)
    component('FX Studio', json.loads((ROOT / 'package.json').read_text())['version'], 'MIT',
              [copy(ROOT / 'LICENSE', 'software/FX-Studio-LICENSE.txt'), copy(ROOT / 'NOTICE', 'software/FX-Studio-NOTICE.txt')],
              'The public FX Studio repository; this app includes the backend, UI, desktop and agent skill source.')
    version = (electron / 'version').read_text().strip()
    component('Electron / Chromium / Node.js', version, 'MIT and upstream component licenses',
              [copy(electron / 'LICENSE', 'software/electron/LICENSE'),
               copy(electron / 'LICENSES.chromium.html', 'software/electron/LICENSES.chromium.html')],
              'https://github.com/electron/electron/tree/v' + version)
    # Electron puts these files beside Electron.app on macOS. Copy them
    # explicitly; cloning Electron.app alone silently omits both files.
    for name in ('LICENSE', 'LICENSES.chromium.html'):
        shutil.copy2(electron / name, resources / name)

    if platform == 'darwin':
        python_texts = list((folder / 'software/python-3.11.11').glob('LICENSE.*.txt'))
        if len(python_texts) < 15:
            raise ValueError('Missing CPython and embedded native-library license texts.')
        component('CPython and embedded native libraries', '3.11.11', 'PSF and upstream library licenses',
                  [p.relative_to(folder).as_posix() for p in sorted(python_texts)],
                  'https://github.com/astral-sh/python-build-standalone ; original release metadata in software/python-3.11.11/PROVENANCE.json')
        component('OpenSSL in cryptography', '4.0.3', 'Apache-2.0', ['software/native/openssl-4.0.3/LICENSE.txt'],
                  'https://github.com/openssl/openssl/tree/openssl-4.0.3')
        component('Homebrew build recipes', 'LAME 3.100 recipe', 'BSD-2-Clause', ['software/native/homebrew/LICENSE.txt'],
                  'https://github.com/Homebrew/brew')
    else:
        if not native_materials:
            raise ValueError('Windows packaging requires version-matched native license/source materials.')
        native = validate_license_bundle(native_materials)
        if native.get('platform') != 'win32' or not any('cpython' in c['name'].lower() for c in native['components']):
            raise ValueError('Windows native materials must include CPython and its embedded library licenses.')
        binary_records = {r['path']: r for r in native.get('binaries', [])}
        required = [p for p in (app / 'tools').iterdir() if p.suffix.lower() in {'.exe', '.dll'}]
        required += list((python_site / '_soundfile_data').glob('*.dll'))
        required += [app/'python/python.exe',*(app/'python').glob('*.dll'),
                     *(app/'python/DLLs').glob('*.pyd'),*(app/'python/DLLs').glob('*.dll')]
        for binary in required:
            relative = str(binary.relative_to(app)).replace('\\', '/')
            if relative not in binary_records or binary_records[relative]['sha256'] != sha256(binary):
                raise ValueError('Windows native binary lacks matching source evidence: ' + relative)

    for distribution in sorted(importlib.metadata.distributions(path=[str(python_site)]), key=lambda d: d.metadata['Name'].lower()):
        name, version = distribution.metadata['Name'], distribution.version
        stem = re.sub(r'[^a-zA-Z0-9._-]', '-', name) + '-' + version
        files = []
        for entry in distribution.files or []:
            if license_file(entry) or any(part.endswith('.dist-info') for part in Path(entry).parts) and 'licenses' in Path(entry).parts:
                relative = Path(entry)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid package license path: ' + str(entry))
                files.append(copy(distribution.locate_file(entry), Path('software/python-packages') / stem / relative))
        if not files and name.lower() == 'sentencepiece':
            seed = folder / ('software/sentencepiece-' + version)
            files = [p.relative_to(folder).as_posix() for p in sorted(seed.rglob('*')) if p.is_file() and license_file(p)]
        if not files and platform == 'win32':
            match = next((c for c in native['components'] if c['name'].lower() == name.lower() and c['version'] == version), None)
            if match:
                files = [copy(Path(native_materials) / p, 'windows-native/' + p) for p in match['license_files']]
        if not files:
            raise ValueError('Package omits license texts: ' + name + ' ' + version + '. Add its version-matched upstream texts before releasing.')
        component(name, version, distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See supplied license texts',
                  files, 'https://pypi.org/project/' + name + '/' + version + '/')

    component('Feather icons', 'bundled SVG paths', 'MIT', ['feather.txt'], 'https://github.com/feathericons/feather')
    runtime = app / ('.runtime/stable-audio-3-windows' if platform == 'win32' else '.runtime/stable-audio-3')
    component('Stable Audio 3 inference runtime', 'pinned in FX Studio documentation', 'MIT',
              [copy(runtime / 'LICENSE', 'software/stable-audio-runtime/LICENSE')], 'https://github.com/Stability-AI/stable-audio-3')
    component('Stable Audio 3 Medium / T5Gemma model materials', 'downloaded separately; weights are not bundled',
              'Stability AI Community License and Gemma Terms',
              ['models/LICENSE.md', 'models/LICENSE_GEMMA.md', 'models/NOTICE'], 'https://huggingface.co/stabilityai/stable-audio-3-optimized')

    if platform == 'darwin':
        native = json.loads((ROOT / 'packaging/macos-sources.json').read_text())
        materials = ROOT / '.runtime/legal-cache'
        exporter_info = json.loads((Path(exporter) / 'build.json').read_text())
        if sha256(Path(exporter) / 'bin/ffmpeg') != exporter_info['ffmpeg_sha256']:
            raise ValueError('FFmpeg does not match its source/build manifest.')
        if sha256(exporter_info['lame_library']) != exporter_info['lame_sha256']:
            raise ValueError('LAME does not match its source/build manifest.')
        copy(ROOT / 'scripts/prepare_audio_exporter.py', 'sources/prepare_audio_exporter.py')
        copy(exporter_info['lame_build_recipe'], 'sources/lame.rb')
        copy(Path(exporter) / 'build.json', 'sources/exporter-build.json')
        copy(materials / 'sndfile-matching-build.sh', 'sources/libsndfile-mac-build.sh')
        for record in native['archives']:
            path = materials / record['file']
            if not path.is_file() or sha256(path) != record['sha256']:
                raise ValueError('Missing/corrupt corresponding source: ' + record['file'] + '. Run scripts/prepare_release_sources.py.')
            copy(path, Path('sources') / record['file'])
        sndfile = python_site / '_soundfile_data/libsndfile_arm64.dylib'
        # Signing the bundled dylib changes its bytes, so check before signing.
        if sha256(sndfile) != native['libsndfile_binary_sha256']:
            raise ValueError('Changed libsndfile binary: resolve matching sources before building.')
        for name, version, license in [('FFmpeg', '8.0.1', 'LGPL-2.1-or-later'), ('LAME', '3.100', 'LGPL-2.0-or-later'),
                                      ('libsndfile and linked audio codecs', '1.2.2', 'LGPL and supplied codec licenses')]:
            prefix = 'software/native/' + name.split()[0].lower()
            files = [p.relative_to(folder).as_posix() for p in sorted((folder / prefix).rglob('*')) if p.is_file() and license_file(p)]
            component(name, version, license, files, 'Corresponding source archives and build instructions are included in sources/.')
        shutil.copy2(ROOT / 'packaging/macos-sources.json', folder / 'sources/source-manifest.json')
    else:
        # A Windows FFmpeg DLL/EXE selected by the builder has its own build,
        # libraries and source requirements; never reuse macOS source evidence.
        if not native_materials:
            raise ValueError('Windows packaging requires --native-license-dir with version-matched FFmpeg/libsndfile sources and inventory.json. See packaging/GITHUB-RELEASE.md.')
        native = validate_license_bundle(native_materials)
        shutil.copytree(native_materials, folder / 'windows-native', dirs_exist_ok=True)
        for item in native['components']:
            components.append({**item, 'license_files': ['windows-native/' + p for p in item['license_files']]})

    rows = ['# FX Studio — bundled licenses', '', 'Powered by Stability AI', '',
            'The original application code and agent skill use MIT. Each component below retains its own terms.', '',
            '| Component | Version | License |', '| --- | --- | --- |']
    rows.extend('| ' + ' | '.join(str(item[k]).replace('|', '/') for k in ('name', 'version', 'license')) + ' |' for item in components)
    source_folder = 'windows-native/sources/' if platform == 'win32' else 'sources/'
    rows += ['', 'See THIRD_PARTY_NOTICES.md for source availability and replacing/rebuilding LGPL components.',
             'Sources and their SHA-256 hashes are in ' + source_folder + '. No model agreement is accepted by the app.', '']
    (folder / 'README.md').write_text('\n'.join(rows))
    copy(ROOT / 'THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md')
    manifest = {'schema': 1, 'platform': platform, 'components': components,
                'files': [{'path': p.relative_to(folder).as_posix(), 'sha256': sha256(p)} for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'inventory.json']}
    (folder / 'inventory.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_license_bundle(folder)
    # Keep the usual Resources entry easy to find without another duplicate.
    (resources / 'Third-party notices').mkdir(exist_ok=True)
    (resources / 'Third-party notices/README.txt').write_text('Full license texts, copyright notices, source archives and inventory:\n../app/ui/licenses/\n\nFX Studio original code: ../app/LICENSE (MIT)\n')
    return {'components': len(components), 'files': len(manifest['files']), 'inventory': 'app/ui/licenses/inventory.json'}
