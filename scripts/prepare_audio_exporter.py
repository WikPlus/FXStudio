"""Build the macOS WAV/MP3 exporter from verified LGPL sources.

Uses the already-installed shared LAME 3.100 library. Never changes Homebrew.
Only this project's .runtime directory is written. Source archives and the
exact build recipe are retained for redistribution with the application.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.runtime/legal-cache'
TARGET = ROOT / '.runtime/audio-exporter'
SOURCES = {
    'ffmpeg-8.0.1.tar.xz': ('https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz', '05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41'),
    'lame-3.100.tar.gz': ('https://downloads.sourceforge.net/project/lame/lame/3.100/lame-3.100.tar.gz', 'ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e'),
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(name, url, expected):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / name
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.part')
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
            while chunk := response.read(1024**2):
                out.write(chunk)
                if out.tell() > 100 * 1024**2:
                    raise ValueError('Source archive is unexpectedly large: ' + name)
        temporary.replace(target)
    if digest(target) != expected:
        raise ValueError('Source archive checksum mismatch: ' + name)
    return target


def main():
    if sys.platform != 'darwin' or os.uname().machine != 'arm64':
        raise SystemExit('This exporter build requires Apple Silicon macOS.')
    lame = Path('/opt/homebrew/opt/lame').resolve()
    if lame.name != '3.100' or not (lame / 'lib/libmp3lame.dylib').is_file():
        raise SystemExit('Install LAME 3.100 before building: brew install lame')
    sources = {name: fetch(name, *record) for name, record in SOURCES.items()}
    build = TARGET / 'source'
    build.mkdir(parents=True, exist_ok=True)
    with tarfile.open(sources['ffmpeg-8.0.1.tar.xz']) as archive:
        archive.extractall(build, filter='data')
    configure = [
        './configure', '--prefix=' + str(TARGET), '--cc=clang',
        '--disable-autodetect', '--disable-gpl', '--disable-nonfree',
        '--disable-doc', '--disable-debug', '--disable-ffplay', '--disable-ffprobe',
        '--disable-avdevice', '--disable-network', '--disable-everything',
        '--enable-ffmpeg', '--enable-pthreads', '--enable-swresample',
        '--enable-protocol=file', '--enable-demuxer=wav,mp3,flac,ogg',
        '--enable-muxer=wav,mp3',
        '--enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,mp3float,flac,vorbis,opus',
        '--enable-encoder=pcm_s16le,libmp3lame', '--enable-parser=mpegaudio,flac,vorbis,opus',
        '--enable-filter=aresample,anull,aformat', '--enable-libmp3lame',
        '--extra-cflags=-I' + str(lame / 'include'),
        '--extra-ldflags=-L' + str(lame / 'lib'),
    ]
    cwd = build / 'ffmpeg-8.0.1'
    subprocess.run(configure, cwd=cwd, check=True)
    subprocess.run(['make', '-j', str(min(os.cpu_count() or 2, 6)), 'ffmpeg'], cwd=cwd, check=True)
    (TARGET / 'bin').mkdir(exist_ok=True)
    shutil.copy2(cwd / 'ffmpeg', TARGET / 'bin/ffmpeg')
    license_output = subprocess.run([str(TARGET / 'bin/ffmpeg'), '-L'], check=True, capture_output=True, text=True)
    if 'GNU Lesser General Public License' not in ' '.join((license_output.stdout + license_output.stderr).split()):
        raise RuntimeError('Expected an LGPL exporter; refusing another build.')
    (TARGET / 'build.json').write_text(json.dumps({
        'ffmpeg_version': '8.0.1', 'license': 'LGPL-2.1-or-later',
        'ffmpeg_sha256': digest(TARGET / 'bin/ffmpeg'),
        'configure': configure, 'sources': {name: {'url': record[0], 'sha256': record[1]} for name, record in SOURCES.items()},
        'lame_library': str((lame / 'lib/libmp3lame.dylib').resolve()),
        'lame_sha256': digest(lame / 'lib/libmp3lame.dylib'),
        'lame_build_recipe': str(lame / '.brew/lame.rb'),
        'ffmpeg_source_changes': 'None. Built from the unmodified FFmpeg 8.0.1 release archive.',
        'lame_source_changes': 'Homebrew removes lame_init_old from include/libmp3lame.sym; see the included lame.rb recipe.',
    }, indent=2) + '\n')
    print('Built verified LGPL WAV/MP3 exporter:', TARGET / 'bin/ffmpeg', flush=True)


if __name__ == '__main__':
    main()
