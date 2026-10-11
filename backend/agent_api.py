"""Agent operations on the desktop's queue and saved, trimmed sounds."""
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath

from core import ROOT


class Conflict(ValueError):
    pass


class AgentAPI:
    def __init__(self, studio, access):
        self.studio, self.access = studio, access
        with studio.lock:
            studio.db.executescript('''
                CREATE TABLE IF NOT EXISTS agent_requests
                (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_packs
                (id TEXT PRIMARY KEY, name TEXT NOT NULL, jobs TEXT NOT NULL, created REAL NOT NULL);
            ''')

    def sound(self, sound_id):
        item = self.studio.item(sound_id)
        item['original_path'] = item.pop('path')
        item['audio_path'] = None if item.get('missing') else str(self.studio.media_path(sound_id))
        if item['kind'] == 'generated':
            model_id = item['settings'].get('model', 'sm-sfx')
            names = {'medium': ('Stable Audio 3 Medium', 'https://huggingface.co/stabilityai/stable-audio-3-medium'),
                     'sm-sfx': ('Stable Audio 3 Small SFX', 'https://huggingface.co/stabilityai/stable-audio-3-small-sfx'),
                     'unite': ('UNITE-AUDIO', 'https://huggingface.co/RunwuShi/UNITE-AUDIO')}
            model_name, url = names.get(model_id, (model_id, ''))
            item['source'] = {'model': model_name, 'url': url}
            item['license'] = ({'name': 'Stable Audio Community License', 'url': 'https://stability.ai/license',
                                'note': 'Model terms and registration apply. Reference asset terms also apply when present.'}
                               if model_id in ('medium', 'sm-sfx') else
                               {'name': 'Original model terms', 'url': url, 'note': 'Consult the original model license; reference terms also apply.'})
        return item

    def job(self, job_id):
        rows = self.studio.rows('SELECT * FROM jobs WHERE id=?', (job_id,))
        if not rows:
            raise KeyError('Job not found.')
        job = rows[0]
        job['settings'] = json.loads(job['settings'])
        job['elapsed'] = round((job['finished'] or time.time()) - (job['started'] or job['created']), 1)
        ids = self.studio.rows('SELECT id FROM items WHERE job_id=? ORDER BY variant', (job_id,))
        job['sounds'] = [self.sound(row['id']) for row in ids]
        return job

    def pack(self, pack_id):
        rows = self.studio.rows('SELECT * FROM agent_packs WHERE id=?', (pack_id,))
        if not rows:
            raise KeyError('Pack not found.')
        pack = rows[0]
        pack['jobs'] = [self.job(job_id) for job_id in json.loads(pack['jobs'])]
        project_ids = {job['settings'].get('project_id') for job in pack['jobs']}
        pack['project'] = self.studio.project(next(iter(project_ids))) if len(project_ids) == 1 and None not in project_ids else None
        states = [job['state'] for job in pack['jobs']]
        pack['state'] = ('running' if any(s in ('running', 'cancelling') for s in states) else
                         'queued' if 'queued' in states else
                         'completed' if all(s == 'completed' for s in states) else 'incomplete')
        return pack

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
            raise ValueError('Use 1–80 letters, numbers, underscores or hyphens for names.')
        if value.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
            raise ValueError('This name is reserved on Windows.')
        return value

    def generate(self, data, pack=False):
        request_id = data.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id):
            raise ValueError('Supply a unique request_id (1–100 letters, numbers, hyphens or underscores). Reuse it when retrying this request.')
        name = self.name(data.get('name', 'sound_pack')) if pack else None
        assets = data.get('assets') if pack else [data.get('settings')]
        if not isinstance(assets, list) or not 1 <= len(assets) <= 8 or not all(isinstance(a, dict) for a in assets):
            raise ValueError('Supply 1–8 assets with prompt, asset_name and optional generation settings.')
        for asset in assets:
            self.name(asset.get('asset_name', 'sound'))
            if not isinstance(asset.get('prompt'), str):
                raise ValueError('Each asset requires an English prompt string.')
        if pack and len({a.get('asset_name', 'sound') for a in assets}) != len(assets):
            raise ValueError('Give each pack asset a different asset_name.')
        fingerprint = hashlib.sha256(json.dumps({'pack': pack, 'data': data}, sort_keys=True).encode()).hexdigest()
        if pack and data.get('project_id') not in (None, ''):
            project_id = self.studio.project(data['project_id'])['id']
            if any(a.get('project_id') not in (None, '', project_id) for a in assets):
                raise ValueError('All assets must use the pack project_id.')
            assets = [{**asset, 'project_id': project_id} for asset in assets]
        with self.studio.lock:
            previous = self.studio.rows('SELECT * FROM agent_requests WHERE id=?', (request_id,))
            if previous:
                if previous[0]['fingerprint'] != fingerprint:
                    raise Conflict('This request_id was already used with different settings. Use a new id for a new request.')
                return json.loads(previous[0]['result'])
            result = {}
            def persist(jobs):
                if pack:
                    pack_id = secrets.token_hex(6)
                    self.studio.db.execute('INSERT INTO agent_packs VALUES(?,?,?,?)',
                                           (pack_id, name, json.dumps([j['id'] for j in jobs]), time.time()))
                    result.update(id=pack_id, name=name, jobs=jobs)
                else:
                    result.update(jobs[0])
                self.studio.db.execute('INSERT INTO agent_requests VALUES(?,?,?)',
                                       (request_id, fingerprint, json.dumps(result)))
            self.studio.enqueue_many(assets, origin='agent', persist=persist)
        return result

    def export_directory(self, folder=''):
        if not isinstance(folder, str) or '\\' in folder or ':' in folder:
            raise ValueError('Use a relative export folder, with forward slashes.')
        relative = PurePosixPath(folder)
        if relative.is_absolute() or '..' in relative.parts or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', p) for p in relative.parts):
            raise ValueError('Export folders must stay inside the selected export folder.')
        root = Path(self.access.config['export_root'])
        if root.is_symlink():
            raise ValueError('The export folder must not be a symbolic link. Choose it again in Setup.')
        root.mkdir(parents=True, exist_ok=True)
        target = root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('Export folders must stay inside the selected export folder.')
        if target.resolve().is_relative_to(self.studio.library_root.resolve()):
            raise ValueError('The shared sound library is read-only.')
        target.mkdir(parents=True, exist_ok=True)
        return target

    def write_sound(self, sound_id, folder, name, format):
        if format not in ('wav', 'mp3'):
            raise ValueError('Choose wav or mp3.')
        name = self.name(name)
        item = self.sound(sound_id)
        if not item['audio_path']:
            raise ValueError('The original audio file is missing. Its saved settings are still available.')
        source = Path(item['audio_path'])
        target = folder / (name + '.' + format)
        # Exclusive creation protects existing editor assets, including symlinks.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
        try:
            with tempfile.TemporaryDirectory(prefix='.fx-export-', dir=folder) as temp:
                rendered = Path(temp) / ('sound.' + format)
                if source.suffix.lower() == '.' + format:
                    shutil.copyfile(source, rendered)
                else:
                    self.studio.convert(source, rendered, format)
                os.replace(rendered, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {'path': str(target.resolve()), 'bytes': target.stat().st_size, 'format': format,
                'sound_id': sound_id, 'duration': item['duration'], 'trim': item['trim'],
                'prompt': item.get('prompt'), 'settings': item.get('settings'),
                'seed': item.get('seed'), 'source': item.get('source'), 'license': item.get('license'),
                'reference': item.get('reference'), 'projects': item['projects']}

    def export_sound(self, data):
        item = self.studio.item(data['sound_id'])
        name = data.get('name') or item.get('settings', {}).get('asset_name') or ('sound_' + item['id'])
        with self.studio.render_lock:
            return self.write_sound(item['id'], self.export_directory(data.get('folder', '')), name, data.get('format', 'wav'))

    def export_pack(self, data):
        pack = self.pack(data['pack_id'])
        if pack['state'] != 'completed':
            raise ValueError('This pack is not complete. Read its jobs and errors; export individual finished sounds if needed.')
        format = data.get('format', 'wav')
        if format not in ('wav', 'mp3'):
            raise ValueError('Choose wav or mp3.')
        folder = self.export_directory(data.get('folder', '')) / (pack['name'] + '_' + pack['id'])
        # A pack gets its own new directory; failed exports remove only that directory.
        folder.mkdir()
        try:
            exports = []
            with self.studio.render_lock:
                for job in pack['jobs']:
                    for sound in job['sounds']:
                        asset_name = job['settings']['asset_name']
                        if len(asset_name) > 77:
                            asset_name = asset_name[:64] + '_' + job['id']
                        name = asset_name + f"_{sound['variant']:02d}"
                        exports.append(self.write_sound(sound['id'], folder, name, format))
                manifest = folder / 'manifest.json'
                manifest.write_text(json.dumps({'app': 'FX Studio', 'pack_id': pack['id'], 'name': pack['name'],
                                                'created': time.time(), 'project': pack['project'], 'sounds': exports}, indent=2, ensure_ascii=False) + '\n')
        except Exception:
            shutil.rmtree(folder)
            raise
        return {'folder': str(folder.resolve()), 'manifest': str(manifest.resolve()), 'sounds': exports}

    def get(self, path, query):
        value = lambda key, default='': query.get(key, [default])[0]
        if path == '/status':
            status = self.studio.status()
            return {**status, 'agent_access': self.access.status(), 'queue_capacity': 8}
        if path == '/guide':
            return {'guide': (ROOT / 'ui/skills/fx-studio/SKILL.md').read_text()}
        if path == '/projects':
            return {'projects': self.studio.projects(value('q'))}
        if path.startswith('/projects/'):
            project_id = path.rsplit('/', 1)[-1]
            offset, limit = int(value('offset', '0')), int(value('limit', '30'))
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError('Use offset >= 0 and limit 1–100.')
            items = self.studio.project_items(project_id, value('q'))
            return {**self.studio.project(project_id), 'total': len(items), 'offset': offset,
                    'items': items[offset:offset + limit], 'jobs': self.studio.project_jobs(project_id),
                    'note': 'Use get_sound for saved-crop audio_path. Project membership shares the sound and its trim.'}
        if path.startswith('/jobs/'):
            return self.job(path.rsplit('/', 1)[-1])
        if path.startswith('/packs/'):
            return self.pack(path.rsplit('/', 1)[-1])
        if path.startswith('/sounds/'):
            return self.sound(path.rsplit('/', 1)[-1])
        if path in ('/history', '/library'):
            offset, limit = int(value('offset', '0')), int(value('limit', '30'))
            if not 0 <= offset or not 1 <= limit <= 100:
                raise ValueError('Use offset >= 0 and limit 1–100.')
            items = (self.studio.items(value('q'), value('favorites') == '1') if path == '/history' else
                     self.studio.library_items(value('q'), value('category'), value('favorites') == '1'))
            return {'total': len(items), 'offset': offset, 'items': items[offset:offset + limit],
                    'note': 'Use get_sound to obtain audio_path for the saved crop. path in search results is the original.'}
        raise KeyError('Agent route not found.')

    def post(self, path, data):
        if path == '/projects':
            return self.studio.create_project(data)
        if path == '/project-update':
            return self.studio.update_project(data['project_id'], data)
        if path == '/project-sound':
            return self.studio.set_project_sound(data['project_id'], data['sound_id'], data.get('included', True))
        if path == '/generate':
            return self.generate(data)
        if path == '/packs':
            return self.generate(data, pack=True)
        if path == '/cancel':
            return self.studio.cancel(data['job_id'])
        if path == '/cancel-pack':
            pack = self.pack(data['pack_id'])
            return {'jobs': [self.studio.cancel(job['id']) for job in pack['jobs']]}
        if path == '/trim':
            self.studio.set_trim(data['sound_id'], data)
            return self.sound(data['sound_id'])
        if path == '/favorite':
            if not isinstance(data.get('favorite'), bool):
                raise ValueError('Favorite must be true or false.')
            return self.studio.favorite(data['sound_id'], data['favorite'])
        if path == '/export':
            return self.export_sound(data)
        if path == '/export-pack':
            return self.export_pack(data)
        raise KeyError('Agent route not found.')
