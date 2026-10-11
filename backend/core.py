"""Local job queue, persistent media catalogue and strict parameter validation."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from models import DEFAULT_MODEL, MODELS, generation_prompt, selected_model, weight_spec
from runtime_paths import default_data_dir, ffmpeg_binary, library_folder, link_cached_models, model_folder, runtime_folder, runtime_kind
from processes import process_options, terminate_tree
from audio_edits import trim_bounds, render_trim

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ('queued', 'running', 'cancelling')

class Studio:
    def __init__(self, data_dir=None, library_root=None, command_factory=None, setup_command_factory=None):
        self.data = Path(data_dir or os.environ.get('FX_DATA_DIR') or default_data_dir())
        self.audio = self.data / 'audio'
        self.audio.mkdir(parents=True, exist_ok=True)
        self.logs = self.data / 'jobs'
        self.logs.mkdir(exist_ok=True)
        link_cached_models()
        self.db = sqlite3.connect(self.data / 'studio.sqlite', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.render_lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = False
        self.process = None
        self.current = None
        self.setup_process = None
        self.setup_cancelled = False
        self.setup_thread = None
        self.setup_state = {'state': 'idle', 'message': ''}
        self.command_factory = command_factory or self.command
        self.setup_command_factory = setup_command_factory or (lambda model: [sys.executable, '-u', str(ROOT / 'scripts/download_models.py'), '--model', model])
        self.library_root = Path(library_root) if library_root else library_folder(self.data)
        self.library = {}
        self.library_error = ''
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, settings TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, started REAL, finished REAL, stage INTEGER DEFAULT 0, step INTEGER DEFAULT 0, total INTEGER DEFAULT 0, message TEXT DEFAULT '', error TEXT DEFAULT '', cancelled INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, job_id TEXT, title TEXT, prompt TEXT, settings TEXT, seed INTEGER, path TEXT, created REAL, duration REAL, favorite INTEGER DEFAULT 0, variant INTEGER);
        CREATE TABLE IF NOT EXISTS library_favorites (id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS sound_trims (item_id TEXT PRIMARY KEY, start REAL NOT NULL, end REAL NOT NULL, source_duration REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, description TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS project_sounds (project_id TEXT NOT NULL, sound_id TEXT NOT NULL, added REAL NOT NULL, PRIMARY KEY(project_id,sound_id));
        CREATE INDEX IF NOT EXISTS project_sounds_sound ON project_sounds(sound_id);
        ''')
        self.db.execute("UPDATE jobs SET state='interrupted', finished=?, error='The app closed during this job. You can start it again.' WHERE state IN ('queued','running','cancelling')", (time.time(),))
        self.db.commit()
        try:
            english_titles = dict(line.split('\t', 1) for line in (ROOT / 'backend/library_titles_en.tsv').read_text(encoding='utf-8').splitlines() if line)
            catalog = json.loads((self.library_root / 'katalog.json').read_text(encoding='utf-8'))
            for asset in catalog['assets']:
                path = (self.library_root / asset['path']).resolve()
                if not path.is_relative_to(self.library_root.resolve()):
                    continue
                title = english_titles.get(asset['id']) or asset.get('title_en') or Path(asset['source']['original_filename']).stem.replace('_', ' ')
                self.library[asset['id']] = {**asset, 'path': str(path), 'title': title, 'duration': asset['duration_seconds'], 'kind': 'library'}
        except (OSError, ValueError, KeyError) as e:
            self.library_error = 'The sound library is unavailable: ' + str(e)
        self.thread = threading.Thread(target=self.run, name='fx-queue', daemon=True)
        self.thread.start()
        if os.environ.get('FX_AUTO_SETUP') == '1':
            self.auto_setup()

    def rows(self, query, args=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(query, args).fetchall()]

    def execute(self, query, args=()):
        with self.lock:
            self.db.execute(query, args)
            self.db.commit()

    def model_status(self, model_id=DEFAULT_MODEL):
        model = selected_model(model_id)
        folder = model_folder()
        spec = weight_spec(model_id)
        from model_download import valid_file
        missing = [file['name'] for file in spec['files'] if not valid_file(folder / file['name'], file['size'])]
        runtime = runtime_kind()
        dependencies = [name for name in (('mlx',) if runtime == 'mlx' else ('ai_edge_litert',)) + ('numpy', 'soundfile', 'sentencepiece', 'huggingface_hub') if importlib.util.find_spec(name) is None]
        runtime_ready = (runtime_folder() / ('scripts/sa3_mlx.py' if runtime == 'mlx' else 'scripts/sa3_tflite.py')).is_file()
        if runtime == 'tflite':
            runtime_ready = runtime_ready and (runtime_folder() / 'models/tokenizer.model').is_file()
        ready = not missing and not dependencies and runtime_ready
        download_bytes = sum(file['size'] for file in spec['files'] if file['name'] in missing)
        setup = self.setup_state.copy() if self.setup_state.get('model') == model_id else {'state': 'idle', 'message': ''}
        return {'id': model_id, 'ready': ready, 'runtime_ready': runtime_ready, 'missing': missing, 'dependencies': dependencies, 'model': model['name'], 'engine': model['engine'] if runtime == 'mlx' else 'Official LiteRT · CPU', 'runtime': 'MLX' if runtime == 'mlx' else 'CPU', 'max_seconds': model['max_seconds'], 'max_steps': model['max_steps'], 'default_steps': model['default_steps'], 'default_cfg': model['default_cfg'], 'editing': model['editing'], 'negative_prompt': model['negative_prompt'], 'download_gib': round(download_bytes / 1024 ** 3, 2), 'license_url': 'https://stability.ai/license', 'model_url': model['url'], 'setup': setup}

    def status(self):
        jobs = self.rows('SELECT * FROM jobs ORDER BY created DESC LIMIT 80')
        for job in jobs:
            job['settings'] = json.loads(job['settings'])
            job['elapsed'] = round((job['finished'] or time.time()) - (job['started'] or job['created']), 1)
        return {'ready': True, 'service': 'fx-studio', 'version': '0.1.0', 'packaged': os.environ.get('FX_PACKAGED_RUNTIME') == '1', 'platform': sys.platform, 'model': self.model_status(), 'models': [self.model_status(model_id) for model_id in MODELS], 'setup': self.setup_state.copy(), 'jobs': jobs, 'projects': self.projects(), 'library_count': len(self.library), 'library_root': str(self.library_root.resolve()), 'library_error': self.library_error, 'export_mp3': bool(ffmpeg_binary()), 'data_dir': str(self.data), 'free_gb': round(shutil.disk_usage(self.data).free / 1024 ** 3, 1)}

    def validate(self, raw):
        if not isinstance(raw, dict):
            raise ValueError('Invalid settings.')
        prompt = str(raw.get('prompt', '')).strip()
        if not prompt or len(prompt) > 2000:
            raise ValueError('Describe your sound using 1 to 2,000 characters.')
        def number(name, default, low, high, integer=False):
            value = raw.get(name, default)
            if isinstance(value, bool):
                raise ValueError('Invalid value: ' + name)
            try:
                result = float(value)
            except (ValueError, TypeError):
                raise ValueError('Invalid value: ' + name)
            if not math.isfinite(result) or not low <= result <= high or integer and result != int(result):
                raise ValueError(f'{name} must be between {low} and {high}.')
            return int(result) if integer else result
        seed = raw.get('seed')
        model_id = raw.get('model', DEFAULT_MODEL)
        model = selected_model(model_id)
        settings = {'model': model_id, 'prompt': prompt, 'seconds': number('seconds', 3, .5, model['max_seconds']), 'variants': number('variants', 1, 1, 4, True), 'steps': number('steps', model['default_steps'], 1, model['max_steps'], True), 'cfg': number('cfg', model['default_cfg'], 0, 10), 'seed': secrets.randbelow(2 ** 31 - 4) if seed is None or seed == '' else number('seed', 0, 0, 2 ** 31 - 4, True), 'negative_prompt': str(raw.get('negative_prompt', '')).strip()[:2000], 'mode': str(raw.get('mode', 'text'))}
        if raw.get('project_id') not in (None, ''):
            settings['project_id'] = self.project(raw['project_id'])['id']
        if settings['mode'] not in ('text', 'variation', 'inpaint'):
            raise ValueError('This workflow is unavailable.')
        if settings['mode'] != 'text':
            item = self.item(str(raw.get('reference_id', '')))
            settings['reference_id'] = item['id']
            if abs(settings['seconds'] - item['duration']) > .06:
                raise ValueError('Duration must match the reference.')
            settings['strength'] = number('strength', .65, .1, 1)
            if settings['mode'] == 'inpaint':
                settings['start'] = number('start', 0, 0, settings['seconds'])
                settings['end'] = number('end', settings['seconds'], 0, settings['seconds'])
                if settings['start'] >= settings['end']:
                    raise ValueError('The section must end after it starts.')
        return settings

    def enqueue(self, raw):
        return self.enqueue_many([raw])[0]

    def enqueue_many(self, requests, origin='desktop', persist=None):
        """Validate and save a whole pack atomically, on the shared serial queue."""
        if not isinstance(requests, list) or not 1 <= len(requests) <= 8:
            raise ValueError('A pack must contain between 1 and 8 assets.')
        settings_list = [self.validate(raw) for raw in requests]
        if origin == 'agent':
            for raw, settings in zip(requests, settings_list):
                name = raw.get('asset_name', 'sound')
                if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
                    raise ValueError('Asset names must use 1–80 letters, numbers, underscores or hyphens.')
                settings.update(origin='agent', asset_name=name)
        if self.command_factory == self.command and not self.model_status()['ready']:
            raise ValueError('Weights for ' + MODELS[DEFAULT_MODEL]['name'] + ' are missing or incomplete. Download them in Setup.')
        with self.lock:
            if self.closed:
                raise ValueError('The app is shutting down.')
            if self.setup_state['state'] in ('running', 'cancelling'):
                raise ValueError('Wait for model setup to finish.')
            count = self.db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running','cancelling')").fetchone()[0]
            if count + len(settings_list) > 8:
                raise ValueError('The queue is full. Wait for a job to finish or cancel one.')
            results = []
            try:
                for settings in settings_list:
                    job_id = secrets.token_hex(6)
                    self.db.execute('INSERT INTO jobs(id,settings,state,created) VALUES(?,?,?,?)', (job_id, json.dumps(settings), 'queued', time.time()))
                    results.append({'id': job_id, 'settings': settings})
                if persist:
                    persist(results)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        self.wake.set()
        return results

    def command(self, settings, seed, target, reference):
        model_id = settings.get('model', DEFAULT_MODEL)
        model = selected_model(model_id)
        cmd = [sys.executable, '-u', str(ROOT / 'backend/worker.py'), '--dit', model_id, '--decoder', model['decoder'], '--prompt', generation_prompt(model_id, settings['prompt']), '--seconds', str(settings['seconds']), '--steps', str(settings['steps']), '--seed', str(seed), '--cfg', str(settings['cfg']), '--free-models', '--out', str(target)]
        if runtime_kind() == 'tflite':
            cmd += ['--dit-precision', 'w8a8', '--encoder-precision', 'w8a8', '--decoder-precision', 'w8a8']
        if settings['negative_prompt'] and settings['cfg'] != 1:
            cmd += ['--negative-prompt', settings['negative_prompt']]
        if reference:
            cmd += ['--init-audio', str(reference), '--init-noise-level', str(settings['strength'])]
            if settings['mode'] == 'inpaint':
                cmd += ['--inpaint-range', f"{settings['start']},{settings['end']}"]
        return cmd

    def cancel(self, job_id):
        with self.lock:
            row = self.db.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError('Job not found.')
            if row['state'] not in ACTIVE:
                return {'state': row['state']}
            now = time.time()
            if row['state'] == 'queued':
                self.db.execute("UPDATE jobs SET state='cancelled', cancelled=1, finished=?, message='Cancelled' WHERE id=?", (now, job_id))
            else:
                self.db.execute("UPDATE jobs SET state='cancelling', cancelled=1, message='Stopping generation …' WHERE id=?", (job_id,))
                process = self.process if self.current == job_id else None
                if process:
                    self.terminate(process)
            self.db.commit()
        self.wake.set()
        return {'state': 'cancelled' if row['state'] == 'queued' else 'cancelling'}

    @staticmethod
    def terminate(process):
        terminate_tree(process)

    def is_cancelled(self, job_id):
        with self.lock:
            return self.closed or bool(self.db.execute('SELECT cancelled FROM jobs WHERE id=?', (job_id,)).fetchone()[0])

    def run(self):
        while not self.closed:
            jobs = self.rows("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1")
            if not jobs:
                self.wake.wait(.5)
                self.wake.clear()
                continue
            job = jobs[0]
            with self.lock:
                if self.is_cancelled(job['id']):
                    continue
                self.current = job['id']
                self.execute("UPDATE jobs SET state='running', started=?, message='Loading model …' WHERE id=?", (time.time(), job['id']))
            settings = json.loads(job['settings'])
            temporary = []
            try:
                reference = None
                if settings['mode'] != 'text':
                    reference = self.logs / (job['id'] + '-reference.wav')
                    temporary.append(reference)
                    source = self.item(settings['reference_id'])
                    self.convert(self.media_path(source['id']), reference, 'wav')
                for variant in range(settings['variants']):
                    if self.is_cancelled(job['id']):
                        break
                    item_id = secrets.token_hex(6)
                    seed = settings['seed'] + variant
                    target = self.audio / (item_id + '.wav')
                    temporary.append(target)
                    self.execute('UPDATE jobs SET stage=0, step=0, total=0, message=? WHERE id=?', (f"Variant {variant + 1} of {settings['variants']} · Loading model …", job['id']))
                    env = {**os.environ, 'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONUNBUFFERED': '1', 'PYTHONUTF8': '1', 'PYTORCH_ENABLE_MPS_FALLBACK': '1', 'TOKENIZERS_PARALLELISM': 'false'}
                    with self.lock:
                        if self.is_cancelled(job['id']):
                            break
                        self.process = subprocess.Popen(self.command_factory(settings, seed, target, reference), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, env=env, cwd=ROOT, **process_options())
                    tail = []
                    with (self.logs / (job['id'] + '.log')).open('a', encoding='utf-8') as log:
                        for line in self.process.stdout:
                            log.write(line)
                            log.flush()
                            tail.append(line.strip())
                            tail = tail[-12:]
                            if line.startswith('FX_EVENT '):
                                try:
                                    event = json.loads(line[9:])
                                    self.execute('UPDATE jobs SET stage=?, step=?, total=?, message=? WHERE id=?', (event.get('stage', 0), event.get('step', 0), event.get('total', 0), f"Variant {variant + 1} of {settings['variants']} · " + self.stage_message(event), job['id']))
                                except (ValueError, TypeError):
                                    pass
                    code = self.process.wait()
                    self.process.stdout.close()
                    with self.lock:
                        self.process = None
                    if self.is_cancelled(job['id']):
                        break
                    if code or not target.is_file():
                        raise RuntimeError('Sound generation failed. ' + (' '.join(tail[-4:])[:700] if tail else f'Process exit code {code}'))
                    import soundfile as sf
                    info = sf.info(str(target))
                    if info.frames <= 0 or abs(info.duration - settings['seconds']) > .05:
                        raise RuntimeError('The engine did not produce a complete audio file.')
                    title = settings.get('asset_name') or settings['prompt'].split('.')[0][:75]
                    if settings['variants'] > 1:
                        title += f' · {variant + 1}'
                    with self.lock:
                        if self.is_cancelled(job['id']):
                            break
                        self.db.execute('INSERT INTO items(id,job_id,title,prompt,settings,seed,path,created,duration,variant) VALUES(?,?,?,?,?,?,?,?,?,?)', (item_id, job['id'], title, settings['prompt'], json.dumps({**settings, 'seed': seed, 'variants': 1}), seed, str(target), time.time(), info.duration, variant + 1))
                        if settings.get('project_id'):
                            self.db.execute('INSERT INTO project_sounds VALUES(?,?,?)', (settings['project_id'], item_id, time.time()))
                            self.db.execute('UPDATE projects SET updated=? WHERE id=?', (time.time(), settings['project_id']))
                        self.db.commit()
                    temporary.remove(target)
                cancelled = self.is_cancelled(job['id'])
                self.execute('UPDATE jobs SET state=?, finished=?, message=? WHERE id=?', ('cancelled' if cancelled else 'completed', time.time(), 'Cancelled · finished variants are kept' if cancelled else 'Done', job['id']))
            except Exception as error:
                if self.process:
                    self.terminate(self.process)
                    self.process.wait()
                    self.process.stdout.close()
                cancelled = self.is_cancelled(job['id'])
                self.execute('UPDATE jobs SET state=?, finished=?, error=? WHERE id=?', ('cancelled' if cancelled else 'failed', time.time(), '' if cancelled else str(error), job['id']))
            finally:
                for path in temporary:
                    path.unlink(missing_ok=True)
                with self.lock:
                    self.process = None
                    self.current = None

    @staticmethod
    def stage_message(event):
        messages = {1: 'Loading text encoder', 2: 'Encoding description', 3: 'Generating sound', 4: 'Decoding audio', 5: 'Writing audio file'}
        text = messages.get(event.get('stage'), 'Generating')
        if event.get('step'):
            text += f" · Step {event['step']}/{event['total']}"
        return text

    def item(self, item_id):
        if item_id in self.library:
            asset = self.library[item_id].copy()
            asset['favorite'] = bool(self.rows('SELECT id FROM library_favorites WHERE id=?', (item_id,)))
            if not Path(asset['path']).is_file():
                raise KeyError('The audio file is no longer at its saved location.')
            return self.with_trim(asset)
        rows = self.rows('SELECT * FROM items WHERE id=?', (item_id,))
        if not rows:
            raise KeyError('Sound not found.')
        item = rows[0]
        item['settings'] = json.loads(item['settings'])
        reference_id = item['settings'].get('reference_id')
        if reference_id in self.library:
            source = self.library[reference_id]
            item['reference'] = {key: source[key] for key in ('id', 'title', 'source', 'license', 'kind')}
        elif reference_id:
            source = self.rows('SELECT id,title FROM items WHERE id=?', (reference_id,))
            if source:
                item['reference'] = {**source[0], 'kind': 'generated'}
        item['kind'] = 'generated'
        item['missing'] = not Path(item['path']).is_file()
        return self.with_trim(item)

    def with_trim(self, item):
        item['projects'] = self.rows('SELECT p.id,p.name FROM projects p JOIN project_sounds s ON s.project_id=p.id WHERE s.sound_id=? ORDER BY p.name_key', (item['id'],))
        item['source_duration'] = item['duration']
        rows = self.rows('SELECT start,end,source_duration,updated FROM sound_trims WHERE item_id=?', (item['id'],))
        item['trim'] = {**rows[0], 'fade_ms': 5} if rows else None
        if item['trim']:
            item['source_duration'] = item['trim']['source_duration']
            item['duration'] = item['trim']['end'] - item['trim']['start']
        return item

    def set_trim(self, item_id, raw):
        if not isinstance(raw, dict):
            raise ValueError('Invalid trim settings.')
        item = self.item(item_id)
        if not Path(item['path']).is_file():
            raise KeyError('The original audio file is missing.')
        with self.render_lock:
            if raw.get('reset') is True:
                self.execute('DELETE FROM sound_trims WHERE item_id=?', (item_id,))
            else:
                trim = trim_bounds(item['path'], raw)
                if trim['start'] == 0 and trim['end'] == trim['source_duration']:
                    self.execute('DELETE FROM sound_trims WHERE item_id=?', (item_id,))
                else:
                    # Finish rendering before saving metadata: a failed edit stays usable.
                    self.rendered_path(item, trim)
                    self.execute('INSERT OR REPLACE INTO sound_trims VALUES(?,?,?,?,?)',
                                 (item_id, trim['start'], trim['end'], trim['source_duration'], time.time()))
        return self.item(item_id)

    def rendered_path(self, item, trim):
        source = Path(item['path'])
        stat = source.stat()
        key = json.dumps([str(source), stat.st_size, stat.st_mtime_ns,
                          trim['start'], trim['end'], trim['fade_ms']], separators=(',', ':'))
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        folder = self.data / 'edits'
        folder.mkdir(exist_ok=True)
        target = folder / (item['id'] + '-' + digest + '.wav')
        with self.render_lock:
            if not target.is_file():
                render_trim(source, target, trim)
        return target

    def media_path(self, item_id):
        item = self.item(item_id)
        source = Path(item['path'])
        if not source.is_file():
            raise KeyError('The original audio file is missing.')
        return self.rendered_path(item, item['trim']) if item['trim'] else source

    def prepare_drag(self, item_id):
        item = self.item(item_id)
        source = self.media_path(item_id)
        # Existing library files are dragged directly; never mirror the collection.
        if item['kind'] == 'library' and not item['trim']:
            return {'path': str(source), 'format': source.suffix[1:]}
        folder = self.data / 'drag-exports'
        folder.mkdir(exist_ok=True)
        title = re.sub(r'[\\/:\x00-\x1f<>"|?*]', '-', item['title']).strip(' .')[:80] or 'FX Studio Sound'
        revision = source.stem if item['trim'] else item_id
        target = folder / (title + '--' + revision + source.suffix)
        with self.render_lock:
            if not target.is_file():
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
        # These stable paths must survive app exits and later edits: NLEs reference them.
        return {'path': str(target), 'format': target.suffix[1:]}

    @staticmethod
    def project_fields(raw):
        name, description = raw.get('name'), raw.get('description', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Use a project name with 1–80 characters.')
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError('Project descriptions may contain up to 1,000 characters.')
        return name.strip(), description.strip()

    def projects(self, query=''):
        result = self.rows('''SELECT p.*, (SELECT count(*) FROM project_sounds s WHERE s.project_id=p.id) AS sound_count,
            (SELECT count(*) FROM jobs j WHERE json_extract(j.settings,'$.project_id')=p.id AND j.state IN ('queued','running','cancelling')) AS active_jobs
            FROM projects p ORDER BY p.updated DESC, p.name_key''')
        words = query.casefold().split()
        return [p for p in result if all(w in (p['name'] + ' ' + p['description']).casefold() for w in words)]

    def project(self, project_id):
        if not isinstance(project_id, str):
            raise ValueError('Supply a project id returned by FX Studio.')
        result = next((p for p in self.projects() if p['id'] == project_id), None)
        if not result:
            raise KeyError('Project not found. Select an existing project or create one first.')
        return result

    def create_project(self, raw):
        name, description = self.project_fields(raw)
        with self.lock:
            existing = self.rows('SELECT id FROM projects WHERE name_key=?', (name.casefold(),))
            if existing:
                return {**self.project(existing[0]['id']), 'created_new': False}
            project_id, now = secrets.token_hex(6), time.time()
            self.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)', (project_id, name, name.casefold(), description, now, now))
            return {**self.project(project_id), 'created_new': True}

    def update_project(self, project_id, raw):
        with self.lock:
            previous = self.project(project_id)
            name, description = self.project_fields({**previous, **raw})
            if self.rows('SELECT id FROM projects WHERE name_key=? AND id<>?', (name.casefold(), project_id)):
                raise ValueError('A project with that name already exists. Choose another name.')
            self.execute('UPDATE projects SET name=?,name_key=?,description=?,updated=? WHERE id=?', (name, name.casefold(), description, time.time(), project_id))
            return self.project(project_id)

    def set_project_sound(self, project_id, sound_id, included=True):
        if not isinstance(included, bool):
            raise ValueError('Included must be true or false.')
        with self.lock:
            self.project(project_id)
            self.item(sound_id)
            if included:
                self.db.execute('INSERT OR IGNORE INTO project_sounds VALUES(?,?,?)', (project_id, sound_id, time.time()))
            else:
                self.db.execute('DELETE FROM project_sounds WHERE project_id=? AND sound_id=?', (project_id, sound_id))
            self.db.execute('UPDATE projects SET updated=? WHERE id=?', (time.time(), project_id))
            self.db.commit()
            return {'project': self.project(project_id), 'sound_id': sound_id, 'included': included}

    def project_items(self, project_id, query=''):
        self.project(project_id)
        rows = self.rows('SELECT sound_id FROM project_sounds WHERE project_id=? ORDER BY added DESC, sound_id', (project_id,))
        words, result = query.casefold().split(), []
        for row in rows:
            try:
                item = self.item(row['sound_id'])
            except KeyError:
                # A disconnected external library must not hide this project's generated sounds.
                continue
            text = (item['title'] + ' ' + item.get('prompt', '')).casefold()
            if all(w in text for w in words):
                result.append(item)
        return result

    def project_jobs(self, project_id):
        self.project(project_id)
        jobs = self.rows("SELECT * FROM jobs WHERE json_extract(settings,'$.project_id')=? ORDER BY created DESC LIMIT 80", (project_id,))
        for job in jobs:
            job['settings'] = json.loads(job['settings'])
            job['elapsed'] = round((job['finished'] or time.time()) - (job['started'] or job['created']), 1)
        return jobs

    def items(self, query='', favorites=False, job_id=None):
        rows = self.rows('SELECT id FROM items ORDER BY created DESC')
        result = [self.item(row['id']) for row in rows]
        words = query.casefold().split()
        return [x for x in result if (not favorites or x['favorite']) and (not job_id or x['job_id'] == job_id) and all(w in (x['title'] + ' ' + x['prompt']).casefold() for w in words)]

    def library_items(self, query='', category='', favorites=False):
        words = query.casefold().split()
        result = []
        fave_ids = {row['id'] for row in self.rows('SELECT id FROM library_favorites')}
        for item in self.library.values():
            text = ' '.join([item['title'], item.get('title_de', ''), item['source'].get('original_filename') or '', item['source'].get('supplier') or '', *item.get('tags_de', []), *item.get('tags_en', [])]).casefold()
            if category and item['category'] != category or favorites and item['id'] not in fave_ids or not all(w in text for w in words):
                continue
            result.append(self.with_trim({**item, 'favorite': item['id'] in fave_ids}))
        return result

    def favorite(self, item_id, value):
        self.item(item_id)
        if item_id in self.library:
            self.execute('INSERT OR IGNORE INTO library_favorites VALUES(?)' if value else 'DELETE FROM library_favorites WHERE id=?', (item_id,))
        else:
            self.execute('UPDATE items SET favorite=? WHERE id=?', (int(bool(value)), item_id))
        return {'favorite': bool(value)}

    @staticmethod
    def convert(source, target, format):
        ffmpeg = ffmpeg_binary()
        if not ffmpeg:
            raise ValueError('FFmpeg is required for this conversion. Install it and restart the app.')
        codec = ['-c:a', 'libmp3lame', '-b:a', '320k'] if format == 'mp3' else ['-c:a', 'pcm_s16le', '-ar', '44100', '-ac', '2']
        subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source), *codec, str(target)], check=True, capture_output=True, timeout=120,
                       **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))

    def remember_setup(self):
        self.execute('INSERT OR REPLACE INTO app_settings VALUES(?,?)',
                     ('model-setup', json.dumps(self.setup_state)))

    def auto_setup(self):
        state = self.model_status()
        if state['ready']:
            return
        saved = self.rows("SELECT value FROM app_settings WHERE key='model-setup'")
        if saved:
            previous = json.loads(saved[0]['value'])
            if previous.get('state') in ('paused', 'failed'):
                self.setup_state = previous
                return
        if state['dependencies'] or not state.get('runtime_ready', True):
            self.setup_state = {'state': 'failed', 'model': DEFAULT_MODEL,
                                'message': 'The bundled runtime is incomplete. Reinstall FX Studio; your saved sounds are retained.'}
            return
        self.setup()

    def cancel_setup(self):
        with self.lock:
            if self.setup_state['state'] not in ('running', 'cancelling'):
                return self.setup_state.copy()
            self.setup_cancelled = True
            self.setup_state['state'] = 'cancelling'
            self.setup_state['message'] = 'Stopping the download…'
            # Persist a pause before signalling; quitting now must not resume it.
            self.execute('INSERT OR REPLACE INTO app_settings VALUES(?,?)',
                         ('model-setup', json.dumps({'state': 'paused', 'model': DEFAULT_MODEL,
                          'message': 'Model download paused. Select Resume download to continue.'})))
            if self.setup_process:
                self.terminate(self.setup_process)
            return self.setup_state.copy()

    def setup(self, model_id=DEFAULT_MODEL):
        model = selected_model(model_id)
        with self.lock:
            if self.closed:
                raise ValueError('The app is shutting down.')
            if self.setup_state['state'] in ('running', 'cancelling'):
                return self.setup_state.copy()
            if self.rows("SELECT id FROM jobs WHERE state IN ('queued','running','cancelling')"):
                raise ValueError('Wait for queued jobs to finish.')
            state = self.model_status(model_id)
            if state['ready']:
                return {'state': 'completed', 'model': model_id, 'message': 'The model is already installed.'}
            if state['dependencies'] or not state.get('runtime_ready', True):
                raise ValueError('The runtime is incomplete. Reinstall FX Studio before downloading Medium.')
            self.setup_cancelled = False
            self.setup_state = {'state': 'running', 'model': model_id,
                                'message': 'Downloading Medium. Existing model files are reused.',
                                'download_gib': state['download_gib']}
            self.remember_setup()
        def download():
            process = None
            tail = []
            try:
                with self.lock:
                    if self.closed or self.setup_cancelled:
                        return
                    process = subprocess.Popen(self.setup_command_factory(model_id), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                        cwd=ROOT, env={**os.environ, 'HF_HUB_DISABLE_TELEMETRY': '1',
                        'DO_NOT_TRACK': '1', 'HF_HUB_OFFLINE': '0', 'TRANSFORMERS_OFFLINE': '0', 'PYTHONUTF8': '1'}, **process_options())
                    self.setup_process = process
                for line in process.stdout:
                    tail.append(line.strip()); tail = tail[-6:]
                    if line.startswith('FX_DOWNLOAD '):
                        try:
                            event = json.loads(line[12:])
                            with self.lock:
                                if not self.setup_cancelled:
                                    self.setup_state['progress'] = event
                                    self.setup_state['message'] = ('Verifying model files…' if event['phase'] == 'verifying'
                                                                  else 'Downloading Medium. You can continue exploring the app.')
                        except (ValueError, KeyError, TypeError):
                            pass
                code = process.wait()
                with self.lock:
                    if self.setup_cancelled:
                        self.setup_state = {'state': 'paused', 'model': model_id,
                                            'message': 'Model download paused. Select Resume download to continue.'}
                    elif self.closed:
                        # Keep the persisted running state: resume after normal quit.
                        return
                    else:
                        ready = code == 0 and self.model_status(model_id)['ready']
                        self.setup_state = {'state': 'completed' if ready else 'failed', 'model': model_id,
                            'message': 'Medium is ready. Generate your first sound.' if ready else
                            'Download failed. Check your internet connection and free disk space, then retry. ' + ' '.join(tail)[-500:]}
                    self.remember_setup()
            except Exception as error:
                if process:
                    self.terminate(process)
                with self.lock:
                    self.setup_state = {'state': 'failed', 'model': model_id, 'message': 'Download failed: ' + str(error)}
                    self.remember_setup()
            finally:
                if process:
                    process.wait()
                    process.stdout.close()
                with self.lock:
                    if self.setup_process is process:
                        self.setup_process = None
                        if self.setup_cancelled and self.setup_state['state'] == 'cancelling':
                            self.setup_state = {'state': 'paused', 'model': model_id,
                                                'message': 'Model download paused. Select Resume download to continue.'}
                            self.remember_setup()
        self.setup_thread = threading.Thread(target=download, daemon=True)
        self.setup_thread.start()
        return self.setup_state.copy()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            setup_process = self.setup_process
            for process in (self.process, self.setup_process):
                if process:
                    self.terminate(process)
            self.db.execute("UPDATE jobs SET cancelled=1 WHERE state IN ('queued','running','cancelling')")
            self.db.commit()
        self.wake.set()
        # Keep the connection valid until its writers finish, then release the
        # actual SQLite handle. Windows cannot remove/reopen a still-held file.
        self.thread.join()
        if setup_process:
            try:
                setup_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if self.setup_thread:
            self.setup_thread.join()
        with self.lock:
            self.db.close()
