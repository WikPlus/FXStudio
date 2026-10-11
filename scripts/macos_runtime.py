"""Read the minimum OS from the native software actually being distributed."""
import re
import subprocess
import tempfile
from pathlib import Path

MACH_HEADERS = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def minimum_macos(bundle):
    versions = []
    with tempfile.TemporaryDirectory(prefix='fx-native-metadata-') as temp:
        alias = Path(temp) / 'native'
        for path in Path(bundle).resolve().rglob('*'):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as stream:
                if stream.read(4) not in MACH_HEADERS:
                    continue
            # otool interprets parenthesized Electron helper filenames as
            # archive(member) syntax. A temporary alias avoids that ambiguity.
            alias.unlink(missing_ok=True)
            alias.symlink_to(path)
            result = subprocess.run(['/usr/bin/otool', '-l', str(alias)],
                                    capture_output=True, text=True, check=True)
            found = re.findall(r'\bminos ([\d.]+)', result.stdout)
            found += re.findall(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([\d.]+)', result.stdout)
            versions.extend(tuple(map(int, value.split('.'))) for value in found)
    if not versions:
        raise ValueError('No native macOS deployment targets found in the bundle.')
    return '.'.join(map(str, max(versions)))
