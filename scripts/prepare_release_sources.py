"""Fetch pinned corresponding-source archives, without model downloads."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    cache = ROOT / '.runtime/legal-cache'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'packaging/macos-sources.json').read_text())
    for record in manifest['archives']:
        path = cache / record['file']
        if not path.exists():
            temporary = path.with_suffix(path.suffix + '.part')
            with urllib.request.urlopen(record['url'], timeout=60) as response, temporary.open('wb') as out:
                while chunk := response.read(1024**2):
                    out.write(chunk)
                    if out.tell() > 100 * 1024**2:
                        raise ValueError('Unexpectedly large source archive: ' + path.name)
            temporary.replace(path)
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != record['sha256']:
            raise ValueError('Corresponding source checksum mismatch: ' + path.name)
        print('Verified corresponding source:', path.name, flush=True)
    recipe = cache / 'sndfile-matching-build.sh'
    recipe.write_text((ROOT / 'packaging/libsndfile-mac-build.sh').read_text())


if __name__ == '__main__':
    main()
