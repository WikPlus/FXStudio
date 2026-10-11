"""Locate the installed app and use its bundled CLI; no extra packages needed."""
import os
import subprocess
import sys
from pathlib import Path


def command():
    override = os.environ.get('FX_STUDIO_APP')
    if sys.platform == 'darwin':
        apps = [Path(override)] if override else [Path('/Applications/FX Studio.app'), Path.home() / 'Applications/FX Studio.app']
        roots = [p / 'Contents/Resources/app' for p in apps]
        suffix = 'python/bin/python3'
    elif sys.platform == 'win32':
        apps = [Path(override)] if override else [
            Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Programs/FX Studio/FX Studio.exe',
            Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'FX Studio/FX Studio.exe']
        roots = [p.parent / 'resources/app' for p in apps]
        suffix = 'python/python.exe'
    else:
        raise ValueError('FX Studio supports Apple Silicon macOS and Windows x64.')
    for root in roots:
        if (root / suffix).is_file() and (root / 'backend/agent_cli.py').is_file():
            return [str(root / suffix), '-s', '-B', str(root / 'backend/agent_cli.py'), *sys.argv[1:]]
    raise ValueError('Install FX Studio first. For a custom install location set FX_STUDIO_APP to the .app or Windows executable path.')


if __name__ == '__main__':
    try:
        raise SystemExit(subprocess.call(command()))
    except (ValueError, OSError) as error:
        import json
        print(json.dumps({'error': str(error)}))
        raise SystemExit(1)
