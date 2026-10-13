# Changelog

## Unreleased

### Added

- **Regenerate** replaces a generated sound in its current row with a fresh seed and the same prompt/settings. List position, expanded results, project membership, favorite, waveform zoom and saved crop remain. Progress and Cancel stay in the sound row; a failed or cancelled attempt preserves the previous take.
- **Generate → Format** chooses OGG Vorbis (quality 5), lossless WAV or MP3 (320 kbps). OGG is the initial default. The preference persists across app restarts and supplies the agent default. Each queued job captures the selected format; Regenerate retains the sound's format.
- **Save OGG** exports the saved crop from the app or agents. Playback, crop and drag preserve the stored format. Compressed storage removes the engine's temporary WAV after a successful save.
- **Delete project** previews sound/file counts and asks for confirmation. It removes exclusive generated sounds, previous takes, saved crops, internal drag files and related logs. Sounds shared with another project, library files and external exports remain. Active affected jobs block deletion; interrupted deletion recovers consistently on restart.
- MCP project deletion preview/confirmation, HTTP API and CLI support. The MCP server now exposes 22 tools. Sound and pack generation accept an optional `format`; the English skill and agent guide describe the new behavior.

### Validation

- 89 automated behavior tests passed on macOS, covering queue/cancellation/recovery, real codecs, format persistence, regeneration, deletion/rollback, authentication, MCP stdio and CLI.
- The real Electron renderer and local HTTP service were tested with disposable synthetic sounds: all three storage/playback/drag formats, restart persistence, settings reuse, regeneration with stable list position, and confirmed project deletion. Layout checked at 1260 and 920 pixels.
- The standalone Apple Silicon build generated a real one-second Medium clip in each format and verified 44.1 kHz stereo, crop and drag. Results are recorded in [the macOS validation report](docs/validation/macos-2026-10-13.json). These checks do not guarantee sound quality or speed on other machines.
- Updated Windows source uses the native CI workflow. The Windows v0.1.0 acceptance predates these changes; check the current [workflow run](https://github.com/WikPlus/FXStudio/actions/workflows/windows.yml) before using its newer artifacts.

The existing v0.1.0 release downloads do not include these changes.
