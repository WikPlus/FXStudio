# FX Studio — third-party licenses and source availability

FX Studio's original source code, documentation and local agent skill are MIT
licensed; see [LICENSE](LICENSE). Third-party materials retain their original
licenses. The app license does not grant rights to model weights, user audio,
external library audio or another party's trademarks.

## Bundled software

The release build creates `ui/licenses/inventory.json` and `ui/licenses/README.md`
from the packages actually bundled. Each entry identifies its version, license
texts and source location. **Setup → Models & licenses → Open bundled licenses**
opens the local files. The build and release packager reject missing or changed
license/source files.

- **Electron, Chromium and Node.js:** the official Electron `LICENSE` and full
  `LICENSES.chromium.html` accompany the app, including embedded component
  notices. Source: https://github.com/electron/electron. The bundled version is
  recorded in the inventory and build manifest; use its matching release tag.
  Electron's matching Chromium and Node.js revisions are in that release's
  `DEPS` file. Chromium source, including its FFmpeg component:
  https://chromium.googlesource.com/chromium/src/ and
  https://chromium.googlesource.com/chromium/third_party/ffmpeg/.
- **CPython 3.11.11:** PSF/Python license and the upstream standalone runtime's
  embedded library notices are in `ui/licenses/software/python-3.11.11/`.
  Sources and build metadata: https://github.com/astral-sh/python-build-standalone
  and https://github.com/python/cpython/tree/v3.11.11.
- **Python packages:** full supplied LICENSE/COPYING/NOTICE/copyright texts are
  copied from installed package metadata; versions and exact PyPI source pages
  appear in the inventory. This includes the MIT, BSD, Apache, PSF and MPL terms
  used by MLX, NumPy, MCP and their dependencies. Unmodified `tqdm` Python source
  is included in the app's `python` site-packages together with its MPL/MIT text.
- **SentencePiece:** Apache 2.0 and its Darts, esaxx and protobuf-lite notices are
  included separately because the macOS wheel omits them.
- **Feather SVG icons:** MIT; copyright and full text in `ui/licenses/feather.txt`.
- **Stable Audio 3 inference code:** MIT, Copyright (c) 2026 Stability AI. The
  original runtime license accompanies the copied source. The Mac and Windows
  runtime revisions are pinned separately in the project.

## Audio libraries and corresponding source

The Mac exporter uses **FFmpeg 8.0.1, LGPL 2.1 or later**, built from unmodified
release source with GPL/nonfree components and automatic external-library
detection disabled. It uses the shared **LAME 3.100 library, LGPL 2.0 or later**.
The previous Homebrew FFmpeg with GPL video codecs is not in this release.

**libsndfile 1.2.2** and its statically incorporated audio codecs retain their
own LGPL/BSD license texts. The libsndfile binary's SHA-256 and matching upstream
Git revision are recorded in `packaging/macos-sources.json`. Sources of the
actual libsndfile, LAME, mpg123, Ogg, Vorbis, FLAC and Opus versions are supplied.

The app includes complete source archives, SHA-256 hashes and build recipes in
`ui/licenses/sources/`. These are available offline from the same download as
the binaries. `source-manifest.json` records original download locations.
FFmpeg build flags and source changes are documented in `exporter-build.json`;
`prepare_audio_exporter.py` is the FX Studio build recipe. `lame.rb` records the
Homebrew LAME configuration and symbol-list change. The matching libsndfile
builder is included in `libsndfile-mac-build.sh` and its upstream recipe files in `software/native/libsndfile/build-source/`.
Homebrew build recipes retain Homebrew's BSD 2-Clause license.

To rebuild FFmpeg, extract `ffmpeg-8.0.1.tar.xz`, install or build shared LAME
3.100, run the recorded configure flags with your own prefix/include/library
paths, and run `make ffmpeg`. To rebuild libsndfile, copy its supplied recipe files and extract the accompanying source
archives, then follow its `mac_build.sh arm64` recipe. The libsndfile source
archive uses the unmodified 1.2.2 Git tag (`sndfile-source.tar.gz`); use `tar xzf`
for that archive in place of the recipe's release-tarball extraction command. Its scripts may fetch the same upstream archives; the exact archives
are supplied alongside. There are no FX Studio changes to libsndfile source.

Users may modify or replace the LGPL components and debug those changes. No
FX Studio restriction prohibits reverse engineering for that purpose. The
FFmpeg executable and LAME shared library are in `app/tools/`; the libsndfile
shared library is in `app/python/.../site-packages/_soundfile_data/`. Replacement
components must preserve compatible file names, interfaces and loader paths.
macOS may require a fresh local ad hoc signature after changing a bundle;
Apple Developer Program membership is not needed for that local signature.

Windows native components are checked separately. Its builder requires the
version-matched native license/source directory; it must not claim that the
Mac FFmpeg or libsndfile source evidence covers another Windows binary.

## Separately downloaded model materials

**Powered by Stability AI**

This Stability AI Model is licensed under the Stability AI Community License,
Copyright © Stability AI Ltd. All Rights Reserved

Gemma is provided under and subject to the Gemma Terms of Use found at
https://ai.google.dev/gemma/terms.

Full original agreement texts and the original model NOTICE are in
`ui/licenses/models/`. Stable Audio 3 Medium weights are downloaded directly
from the pinned upstream repository; they are not in the app ZIP or the Git
repository. They are not relicensed under MIT.

The supplied Stability agreement requires registration for commercial use and
limits that grant by annual revenue, including affiliates; it also contains
an integrated end-user product exception. Use restrictions and the incorporated
acceptable-use policy continue to apply. Applicable registration or enterprise
licensing is the publisher/user's own action; FX Studio does not register,
accept agreements or grant exceptions on anyone's behalf.

Official terms: https://stability.ai/license,
https://stability.ai/use-policy, https://ai.google.dev/gemma/terms and
https://ai.google.dev/gemma/prohibited_use_policy.

The MIT app license does not automatically license generated audio. The model's
output provisions apply; the source/settings/license metadata is preserved in
agent pack exports. External library sounds keep their separately documented
licenses and are read from the user's library rather than distributed here.
