"""Package an already-built Mac app for GitHub Releases, without publishing it."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from collect_licenses import validate_license_bundle

ROOT = Path(__file__).resolve().parents[1]


def audit(bundle):
    bundle = bundle.resolve()
    app = bundle / 'Contents/Resources/app'
    manifest = json.loads((bundle / 'Contents/Resources/build.json').read_text())
    if manifest.get('architecture') != 'arm64' or manifest.get('weights_bundled') is not False:
        raise ValueError('Expected a standalone Apple Silicon bundle without weights.')
    if manifest.get('standalone') is not True:
        raise ValueError('Expected the standalone app, not a development launcher.')
    if manifest.get('ffmpeg_license') != 'LGPL-2.1-or-later' or not manifest.get('license_inventory'):
        raise ValueError('Rebuild with the license/source collection and LGPL exporter before packaging.')
    validate_license_bundle(app / 'ui/licenses')
    spec = importlib.util.spec_from_file_location('fx_release_models', app / 'backend/models.py')
    models = importlib.util.module_from_spec(spec)
    # Inspect without adding a bytecode cache to the already-signed bundle.
    prior = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(models)
    finally:
        sys.dont_write_bytecode = prior
    if models.DEFAULT_MODEL != 'medium' or set(models.MODELS) != {'medium'}:
        raise ValueError('The release must offer only Stable Audio 3 Medium.')
    for path in bundle.rglob('*'):
        if path.is_symlink() and (os.path.isabs(os.readlink(path)) or not path.resolve().is_relative_to(bundle)):
            raise ValueError('External symlink in release: ' + str(path.relative_to(bundle)))
        if not path.is_file():
            continue
        relative = path.relative_to(app) if path.is_relative_to(app) else path.relative_to(bundle)
        if path.name == 'agent-access.json' or path.name.startswith('studio.sqlite') or path.name == '.env':
            raise ValueError('Local credentials or history in release: ' + str(relative))
        if path.suffix.lower() in {'.safetensors', '.tflite', '.wav', '.mp3', '.sqlite', '.p12', '.key'}:
            raise ValueError('Weights, user media or private data in release: ' + str(relative))
        # NumPy includes tiny NPZ test fixtures; they are not sound-model weights.
        if path.suffix == '.npz' and (path.stat().st_size > 1024**2 or '.runtime' in path.parts):
            raise ValueError('Model weights in release: ' + str(relative))
        if path.suffix == '.pem' and b'PRIVATE KEY' in path.read_bytes():
            raise ValueError('Private key in release: ' + str(relative))
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    return manifest


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Package the macOS app on a Mac.')
    bundle = ROOT / 'dist/FX Studio.app'
    manifest = audit(bundle)
    archive = ROOT / 'dist/FXStudio-macOS-arm64.zip'
    if archive.exists():
        archive.unlink()
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(bundle), str(archive)], check=True)
    if archive.stat().st_size >= 2 * 1024**3:
        raise ValueError('Archive exceeds the GitHub Releases per-file limit.')
    with zipfile.ZipFile(archive) as zipped:
        bad = zipped.testzip()
        if bad:
            raise ValueError('ZIP integrity failure: ' + bad)
        launcher = zipped.getinfo('FX Studio.app/Contents/MacOS/FXStudio')
        if not (launcher.external_attr >> 16) & 0o111:
            raise ValueError('ZIP lost the executable permission on the launcher.')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksum = archive.with_suffix('.zip.sha256')
    checksum.write_text(digest + '  ' + archive.name + '\n')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': digest, 'version': manifest['version'], 'model': 'medium',
                      'weights_bundled': False, 'signature': 'ad hoc',
                      'notarized': False, 'published': False}, indent=2))


if __name__ == '__main__':
    main()
