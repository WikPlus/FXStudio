# Build and publish a release

Publish compiled assets on GitHub Releases, separately from source code. Never commit `.runtime`, `.venv`, `node_modules`, `dist`, weights, history, audio or credentials.

## macOS arm64

Use the pinned uv standalone CPython 3.11.11 and packages in `requirements.txt`, the official runtime revision from `Einrichten.command`, Node.js and Xcode Command Line Tools. The license seeds in `ui/licenses/software/python-3.11.11` must match this runtime. The SoundFile wheel's libsndfile hash is pinned in `macos-sources.json`.

Install pkg-config and shared LAME 3.100. `scripts/prepare_audio_exporter.py` builds the minimal LGPL FFmpeg exporter and records the actual linked LAME and recipe. `scripts/prepare_release_sources.py` fetches checksum-pinned corresponding sources; neither downloads model weights.

Run `npm run prepare:release`, `npm test`, `npm run check`, `npm run build`, then `npm run package:mac`. The packager validates signatures, symlinks, ZIP contents and the complete license inventory, producing `dist/FXStudio-macOS-arm64.zip` and `.sha256`. The signature is local ad hoc, not Developer ID or notarization. A clean standalone runtime and real Medium check should precede release publication.

## Windows x64

Push to main or manually run [Windows build and tests](../.github/workflows/windows.yml). The workflow provisions Node.js, uv and MSYS2 on a real Windows x64 runner. Inno Setup is installed on the runner. `Build-Windows.ps1` then:

1. Verifies official pinned CPython inputs and prepares the native environment.
2. Installs the Windows Python wheels and checksum-pinned official LiteRT source/tokenizer.
3. Compiles FFmpeg, LAME, libsndfile and its audio codecs from pinned original sources. Replaces the wheel's libsndfile with the compiled matching DLL.
4. Verifies native dependencies and inventories the actual binaries, source archives and license texts.
5. Runs portable behavior tests and JavaScript syntax checks.
6. Builds/audits the portable app, runs the bundled interpreter/HTTP/trim/MP3/project acceptance checks, and tests silent installation and uninstallation of the Inno Setup package.
7. Uploads ZIP, Setup EXE, SHA-256 files and acceptance reports.

Normal runs skip model downloads and report that inference was not tested. For a real Medium CPU acceptance run, use workflow dispatch and explicitly select `run_model_test`. It temporarily downloads about 3 GiB, generates a one-second real sound, validates audio and MP3 export, and records a separate result. This is a CI test, not a hosted generation service. It does not prove performance or audio quality on every Windows PC.

For local builds, install Git, Node.js/npm, uv, MSYS2 in `C:\msys64` and Inno Setup 6. Install `make`, `mingw-w64-x86_64-gcc`, `mingw-w64-x86_64-cmake`, `mingw-w64-x86_64-ninja`, `mingw-w64-x86_64-pkgconf`, then run `./Build-Windows.ps1` in PowerShell. The packages are unsigned; installers use per-user paths without elevation.

## Publish

Use only a successful workflow's assets. Download and inspect the acceptance reports. Attach the Mac ZIP, Windows ZIP and Setup EXE with their SHA-256 files to the release. Include actual test results, hardware/platform constraints, unsigned installation guidance, first-launch download sizes and model-license links. Use a prerelease tag while collecting platform feedback. Avoid claiming native GUI/editor integration was verified by a headless runtime test.

The app's **Save agent kit** feature generates install-specific paths; do not publish your personal exported kit as a universal configuration. The repository contains the portable skill and complete integration guide.
