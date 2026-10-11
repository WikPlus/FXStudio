# Distribution

FX Studio's source and agent skill are MIT licensed. Model weights and bundled dependencies retain their separate terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Source: https://github.com/WikPlus/FXStudio

Compiled downloads: https://github.com/WikPlus/FXStudio/releases

The Mac arm64 app is built and tested on Apple Silicon. Windows x64 uses the native [build/test workflow](.github/workflows/windows.yml); inspect its acceptance reports before publishing an asset. Desktop playback and drag/import into a particular editing application need hands-on review on that platform.

Both packages bundle the software runtime, not weights or user data. Medium downloads automatically on first launch. No paid agent feature or cloud agent service is included. Builds have no paid Apple signing/notarization or Windows certificate.

Read [README.md](README.md) for installation and [packaging/GITHUB-RELEASE.md](packaging/GITHUB-RELEASE.md) for release engineering.
