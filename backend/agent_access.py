"""Local opt-in credentials, separate from the desktop session cookie."""
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path


class AgentAccess:
    def __init__(self, data):
        self.path = Path(data) / 'agent-access.json'
        self.lock = threading.RLock()
        self.last_used = None
        if self.path.is_symlink():
            raise ValueError('The agent credential file must not be a symbolic link.')
        if self.path.exists():
            self.config = json.loads(self.path.read_text())
            if not isinstance(self.config.get('token'), str) or len(self.config['token']) < 32:
                raise ValueError('The local agent credential file is invalid.')
            if os.name != 'nt':
                self.path.chmod(0o600)
        else:
            self.config = {'version': 1, 'enabled': False, 'token': secrets.token_hex(32),
                           'export_root': str(Path(data).resolve() / 'agent-exports')}
            self.save()

    def save(self):
        fd, name = tempfile.mkstemp(prefix='.agent-access-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.config, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self, port=3921):
        with self.lock:
            return {'enabled': self.config['enabled'], 'api_url': f'http://127.0.0.1:{port}/agent/v1',
                    'export_root': self.config['export_root'], 'last_used': self.last_used}

    def configure(self, values, studio):
        with self.lock:
            config = self.config.copy()
            if 'enabled' in values:
                if not isinstance(values['enabled'], bool):
                    raise ValueError('Enabled must be true or false.')
                config['enabled'] = values['enabled']
            if 'export_root' in values:
                folder = Path(values['export_root']).expanduser()
                if not folder.is_absolute() or not folder.is_dir():
                    raise ValueError('Choose an existing export folder.')
                folder = folder.resolve()
                default = studio.data.resolve() / 'agent-exports'
                if folder.is_relative_to(studio.library_root.resolve()):
                    raise ValueError('The shared sound library is read-only. Choose another folder.')
                if folder.is_relative_to(studio.data.resolve()) and not folder.is_relative_to(default):
                    raise ValueError('Choose a folder outside the app data, or agent-exports.')
                config['export_root'] = str(folder)
            if values.get('rotate') is True:
                config['token'] = secrets.token_hex(32)
            self.config = config
            self.save()
        return self.status()

    def authorized(self, header):
        with self.lock:
            if not self.config['enabled'] or not isinstance(header, str):
                return False
            prefix, _, supplied = header.partition(' ')
            valid = prefix == 'Bearer' and secrets.compare_digest(supplied, self.config['token'])
            if valid:
                self.last_used = time.time()
            return valid
