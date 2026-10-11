"""Portable skill bundle with machine-specific MCP recipes, without credentials."""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    python = ROOT / ('python/python.exe' if sys.platform == 'win32' else 'python/bin/python3')
    if not python.is_file():
        python = ROOT / ('.venv/Scripts/python.exe' if sys.platform == 'win32' else '.venv/bin/python')
    return {'command': str(python), 'args': ['-s', '-B', str(ROOT / 'backend/mcp_server.py')]}


def codex_configuration():
    config = configuration()
    return '[mcp_servers.fx_studio]\ncommand = ' + json.dumps(config['command']) + '\nargs = ' + json.dumps(config['args']) + '\nstartup_timeout_sec = 20\ntool_timeout_sec = 120\n'


def save_kit(target):
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (ROOT / 'ui/skills/fx-studio').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                archive.write(path, Path('fx-studio') / path.relative_to(ROOT / 'ui/skills/fx-studio'))
        archive.writestr('mcp-config.json', json.dumps({'mcpServers': {'fx_studio': configuration()}}, indent=2) + '\n')
        archive.writestr('codex-mcp.toml', codex_configuration())
        archive.write(ROOT / 'LICENSE', 'LICENSE')
        archive.write(ROOT / 'NOTICE', 'NOTICE')
        archive.writestr('INSTALL.txt',
            'FX Studio — local agent kit\n\n'
            '1. Install FX Studio. Open Setup > Local agents > Enable agent access.\n'
            '2. Put the fx-studio folder in your local agent\'s skills directory, or use Install skill in Setup.\n'
            '   Codex: ~/.codex/skills/fx-studio ; Claude Code: ~/.claude/skills/fx-studio.\n'
            '3. Start a new agent conversation so it discovers the skill. Ask: Use FX Studio to create a camera shutter sound.\n'
            '4. MCP is optional: add the STDIO command/args from mcp-config.json to your client\'s MCP settings.\n'
            '   Codex uses the TOML block in codex-mcp.toml. Reload the MCP server after adding it.\n'
            '   Recipes use this installation\'s paths; export another kit on a different computer.\n'
            '5. Without MCP, the skill uses scripts/fxstudio.py and the app\'s bundled runtime.\n'
            '   You can also call backend/agent_cli.py with the bundled Python shown in the MCP recipe.\n'
            'The app starts automatically when access is enabled. Generation runs locally and appears in its history.\n'
            'No API subscription, cloud connection or payment unlock is required.\n'
            'Keep the local credential private; it is not included in this kit. Disable access in Setup to stop agents.\n')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply the destination .zip file.')
    save_kit(sys.argv[1])
