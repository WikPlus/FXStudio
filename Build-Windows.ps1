param([string]$FFmpegPath = '', [string]$NativeLicenseDir = '', [string]$MSYSRoot = 'C:\msys64')
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Run this build on Windows x64. GitHub Actions can provide the Windows build machine.' }
function Invoke-BuildStep([string]$Executable, [string[]]$StepArguments) {
    & $Executable @StepArguments
    if ($LASTEXITCODE -ne 0) { throw "Build step failed: $Executable" }
}
Invoke-BuildStep 'uv' @('run', '--no-project', '--python', '3.11.11', '--with', 'zstandard==0.25.0', 'scripts/prepare_windows_native.py', '--prepare-only')
Invoke-BuildStep 'uv' @('venv', '--python', '.runtime/windows-native/runtime/python/python.exe', '.venv')
Invoke-BuildStep 'uv' @('pip', 'install', '--python', '.venv/Scripts/python.exe', '--only-binary=:all:', '-r', 'requirements-windows.txt')
Invoke-BuildStep 'npm.cmd' @('ci')
# Electron 44 downloads its binary separately from npm's package installation.
Invoke-BuildStep 'node' @('node_modules/electron/install.js')
if (-not (Test-Path 'node_modules/electron/dist/electron.exe')) { throw 'Electron installer did not produce the Windows executable.' }
Invoke-BuildStep '.venv/Scripts/python.exe' @('scripts/prepare_windows.py')
if (-not $FFmpegPath -and -not $NativeLicenseDir) {
    Invoke-BuildStep 'uv' @('run', '--no-project', '--python', '3.11.11', '--with', 'zstandard==0.25.0', 'scripts/prepare_windows_native.py', '--msys-root', $MSYSRoot)
    $FFmpegPath = '.runtime/windows-native/bin/ffmpeg.exe'
    $NativeLicenseDir = '.runtime/windows-native-materials'
} elseif (-not $FFmpegPath -or -not $NativeLicenseDir) {
    throw 'For a custom exporter, supply both FFmpegPath and its matching NativeLicenseDir.'
}
$env:FX_FFMPEG_PATH = (Resolve-Path $FFmpegPath).Path
Invoke-BuildStep '.venv/Scripts/python.exe' @('scripts/run_behavior_tests.py')
Invoke-BuildStep 'npm.cmd' @('run', 'check')
$BuildArguments = @('scripts/build_windows.py')
if ($FFmpegPath) { $BuildArguments += @('--ffmpeg', $FFmpegPath) }
if ($NativeLicenseDir) { $BuildArguments += @('--native-license-dir', $NativeLicenseDir) }
Invoke-BuildStep '.venv/Scripts/python.exe' $BuildArguments
