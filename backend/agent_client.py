"""Standard-library client shared by MCP and the installable skill's CLI."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from runtime_paths import default_data_dir


class AgentClient:
    def __init__(self):
        self.data = Path(os.environ.get('FX_DATA_DIR') or default_data_dir())
        self.credentials = self.data / 'agent-access.json'
        port = int(os.environ.get('FX_PORT', '3921'))
        self.base = f'http://127.0.0.1:{port}/agent/v1'
        # Loopback requests must not pass through system or shell HTTP proxies.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def launch(self):
        if os.environ.get('FX_AGENT_NO_LAUNCH') == '1':
            raise ValueError('FX Studio is not running. Start the desktop app.')
        override = os.environ.get('FX_STUDIO_APP')
        if sys.platform == 'darwin':
            app = Path(override) if override else Path('/Applications/FX Studio.app')
            if not app.is_dir():
                app = Path.home() / 'Applications/FX Studio.app'
            if not app.is_dir():
                raise ValueError('Install FX Studio in Applications or set FX_STUDIO_APP to its .app path.')
            subprocess.run(['/usr/bin/open', str(app)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == 'win32':
            candidates = [Path(override)] if override else [
                Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Programs/FX Studio/FX Studio.exe',
                Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'FX Studio/FX Studio.exe']
            executable = next((p for p in candidates if p.is_file()), None)
            if not executable:
                raise ValueError('Install FX Studio or set FX_STUDIO_APP to FX Studio.exe.')
            subprocess.Popen([str(executable)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            raise ValueError('Start FX Studio on a supported Apple Silicon Mac or Windows x64 computer.')

    def token(self):
        if self.credentials.is_symlink():
            raise ValueError('The agent credential file must not be a symbolic link.')
        try:
            config = json.loads(self.credentials.read_text())
        except FileNotFoundError:
            raise ValueError('Open FX Studio > Setup > Local agents and enable access.') from None
        if config.get('enabled') is not True:
            raise ValueError('Local agent access is off. Open FX Studio > Setup > Local agents and enable access.')
        return config['token']

    def request(self, route, data=None):
        launched = False
        deadline = time.monotonic() + 25
        while True:
            try:
                token = self.token()
                request = urllib.request.Request(self.base + route,
                    data=json.dumps(data).encode() if data is not None else None,
                    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                with self.http.open(request, timeout=120 if route.startswith('/export') else 10) as response:
                    return json.load(response)
            except urllib.error.HTTPError as e:
                try:
                    message = json.load(e).get('error', f'Local API returned {e.code}.')
                except (ValueError, AttributeError):
                    message = f'Local API returned {e.code}.'
                raise ValueError(message) from None
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if not launched:
                    self.launch()
                    launched = True
                if time.monotonic() >= deadline:
                    raise ValueError('FX Studio did not become reachable. Open it and check Setup or the service log.') from None
                time.sleep(.2)
            except ValueError:
                # Launch a newly installed app to let it create its opt-in settings.
                if not self.credentials.exists() and not launched:
                    self.launch()
                    launched = True
                    time.sleep(.5)
                    continue
                raise

    @staticmethod
    def query(route, **values):
        return route + '?' + urllib.parse.urlencode({key: int(value) if isinstance(value, bool) else value for key, value in values.items()})
