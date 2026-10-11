#!/usr/bin/env bash
# Native Windows x64 build under MSYS2 MINGW64. Inputs are checksum-verified
# by prepare_windows_native.py; no models or third-party binary builds.
set -euo pipefail
[[ "${MSYSTEM:-}" == MINGW64 ]] || { echo 'Use the MSYS2 MINGW64 shell.' >&2; exit 1; }
work=$(cygpath -u "$1")
prefix="$work/prefix"
jobs=${NUMBER_OF_PROCESSORS:-4}
mkdir -p "$prefix" "$work/build"
# These original releases predate GCC's C23 default. Keep their documented
# pre-C23 function declaration semantics without changing upstream sources.
export CFLAGS='-O2 -std=gnu11'
export CXXFLAGS='-O2'
export LDFLAGS='-static-libgcc'
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
export CPPFLAGS="-I$prefix/include"
export LIBRARY_PATH="$prefix/lib"
export PATH="$prefix/bin:$PATH"
cd "$work/source"

build_autoconf() {
  local folder=$1
  shift
  (cd "$folder"; ./configure --prefix="$prefix" --enable-static --disable-shared "$@"; make -j"$jobs"; make install)
}
build_autoconf libogg-1.3.5
build_autoconf libvorbis-1.3.7
build_autoconf flac-1.4.3 --disable-cpplibs --disable-programs --disable-ogg
build_autoconf opus-1.4 --disable-extra-programs --disable-doc
build_autoconf mpg123-1.32.3 --disable-modules --with-default-audio=dummy
build_autoconf lame-3.100 --disable-frontend

cmake -S libsndfile-1.2.2 -B "$work/build/sndfile" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DCMAKE_PREFIX_PATH="$prefix" -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_C_STANDARD=11 \
  -DCMAKE_SHARED_LINKER_FLAGS=-static-libgcc \
  -DBUILD_SHARED_LIBS=ON -DBUILD_PROGRAMS=OFF -DBUILD_EXAMPLES=OFF \
  -DBUILD_TESTING=OFF -DBUILD_REGTEST=OFF -DENABLE_EXTERNAL_LIBS=ON -DENABLE_MPEG=ON
cmake --build "$work/build/sndfile" --parallel "$jobs"
cmake --install "$work/build/sndfile"
# Do not silently ship a codec-disabled build when CMake misses a static library.
grep -q '^ENABLE_EXTERNAL_LIBS:BOOL=ON' "$work/build/sndfile/CMakeCache.txt"
grep -q '^ENABLE_MPEG:BOOL=ON' "$work/build/sndfile/CMakeCache.txt"

mkdir -p "$work/build/ffmpeg"
cd "$work/build/ffmpeg"
"$work/source/ffmpeg-8.0.1/configure" --target-os=mingw32 --arch=x86_64 \
  --stdc=c17 \
  --disable-autodetect --disable-gpl --disable-nonfree --disable-everything \
  --disable-doc --disable-debug --disable-network --disable-x86asm --disable-avdevice \
  --disable-ffplay --disable-ffprobe --enable-ffmpeg --enable-w32threads --enable-swresample \
  --enable-protocol=file --enable-demuxer=wav,mp3,flac,ogg \
  --enable-muxer=wav,mp3 --enable-decoder=pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le,mp3float,flac,vorbis,opus \
  --enable-parser=mpegaudio,flac,vorbis,opus \
  --enable-encoder=pcm_s16le,libmp3lame --enable-filter=aresample,anull,aformat \
  --enable-libmp3lame --pkg-config-flags=--static \
  --extra-cflags="-I$prefix/include" --extra-ldflags="-L$prefix/lib -static-libgcc"
make -j"$jobs" ffmpeg.exe
mkdir -p "$work/bin"
cp ffmpeg.exe "$work/bin/ffmpeg.exe"
# Capture the exact compiler/environment and source/build flags used.
gcc --version > "$work/compiler.txt"
pacman -Q > "$work/msys2-packages.txt"
cp config.h config_components.h ffbuild/config.mak "$work/bin/"
