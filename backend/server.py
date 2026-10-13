"""Authenticated loopback-only desktop service. No public sharing or telemetry."""
import functools
import http.cookies
import json
import mimetypes
import os
import secrets
import signal
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import Studio, ROOT
from agent_access import AgentAccess
from agent_api import AgentAPI, Conflict

TOKEN = os.environ.get('FX_SESSION_TOKEN', '')
if len(TOKEN) < 16:
    raise SystemExit('FX_SESSION_TOKEN is missing. Launch FX Studio using Starten.command.')
PORT = int(os.environ.get('FX_PORT', 3921))

@functools.lru_cache(maxsize=400)
def waveform(path, mtime, requested_bins=700):
    import numpy as np
    import soundfile as sf
    with sf.SoundFile(path) as stream:
        rate, frames = stream.samplerate, len(stream)
        bins = min(requested_bins, frames)
        peaks = []
        for i in range(bins):
            count = (i + 1) * frames // bins - i * frames // bins
            samples = stream.read(count, dtype='float32', always_2d=True)
            peaks.append(float(np.max(np.abs(samples))))
    maximum = max(peaks, default=0)
    return {'peaks': [round(x / max(maximum, .001), 4) for x in peaks], 'duration': frames / rate, 'sample_rate': rate, 'bins': requested_bins}

class Handler(BaseHTTPRequestHandler):
    server_version = 'FXStudio/0.1'
    def log_message(self, fmt, *args):
        if args and str(args[0]).split()[0] not in ('GET',):
            super().log_message(fmt, *args)

    def authenticated(self):
        raw = self.headers.get('X-FX-Token', '')
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            if not raw and 'fx_session' in cookie:
                raw = cookie['fx_session'].value
        except http.cookies.CookieError:
            pass
        return secrets.compare_digest(raw, TOKEN)

    def send_headers(self, code, content_type, length=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if length is not None:
            self.send_header('Content-Length', str(length))

    def respond(self, data, code=200):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_headers(code, 'application/json; charset=utf-8', len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def file(self, path, download=False):
        path = Path(path)
        size = path.stat().st_size
        start, end, code = 0, max(0, size - 1), 200
        range_header = self.headers.get('Range')
        if range_header and not download:
            try:
                units, values = range_header.split('=', 1)
                first, last = values.split('-', 1)
                if units != 'bytes' or ',' in values:
                    raise ValueError()
                if first:
                    start, end = int(first), int(last) if last else end
                else:
                    start = max(0, size - int(last))
                if not 0 <= start < size or end < start:
                    raise ValueError()
                end = min(end, size - 1)
                code = 206
            except (ValueError, TypeError):
                self.send_headers(416, 'text/plain', 0)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
        length = end - start + 1 if size else 0
        mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        self.send_headers(code, mime, length)
        self.send_header('Accept-Ranges', 'bytes')
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="sound' + path.suffix + '"')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                block = stream.read(min(65536, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def gate(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):
            self.respond({'error': 'This service is available locally only.'}, 403)
            return False
        agent_request = urllib.parse.urlparse(self.path).path.startswith('/agent/v1/')
        authorized = ACCESS.authorized(self.headers.get('Authorization')) if agent_request else self.authenticated()
        if not authorized:
            if agent_request:
                self.respond({'error': 'Local agent access is disabled or unauthorized. Open FX Studio > Setup > Local agents and enable access.'}, 401)
                return False
            self.respond({'error': 'This session is not authorized. Launch FX Studio using Starten.command.'}, 401)
            return False
        return True

    def do_GET(self):
        try:
            if not self.gate():
                return
            url = urllib.parse.urlparse(self.path)
            path = url.path
            query = urllib.parse.parse_qs(url.query)
            get = lambda key, default='': query.get(key, [default])[0]
            if path == '/api/status':
                self.respond({**STUDIO.status(), 'agents': ACCESS.status(PORT)})
            elif path == '/api/agents':
                self.respond(ACCESS.status(PORT))
            elif path == '/api/agent-credentials':
                self.respond({'token': ACCESS.config['token']})
            elif path.startswith('/agent/v1/audio/'):
                self.file(STUDIO.media_path(path.rsplit('/', 1)[-1]))
            elif path.startswith('/agent/v1/'):
                self.respond(AGENTS.get(path[len('/agent/v1'):], query))
            elif path == '/api/history':
                self.respond({'items': STUDIO.items(get('q'), get('favorites') == '1', get('job') or None)})
            elif path == '/api/projects':
                self.respond({'projects': STUDIO.projects(get('q'))})
            elif path == '/api/project-deletion':
                self.respond(STUDIO.project_deletion(get('project_id')))
            elif path.startswith('/api/projects/'):
                project_id = path.rsplit('/', 1)[-1]
                self.respond({**STUDIO.project(project_id), 'items': STUDIO.project_items(project_id, get('q')), 'jobs': STUDIO.project_jobs(project_id)})
            elif path == '/api/library':
                items = STUDIO.library_items(get('q'), get('category'), get('favorites') == '1')
                categories = sorted({x['category'] for x in STUDIO.library.values()})
                self.respond({'items': items, 'categories': categories, 'error': STUDIO.library_error})
            elif path.startswith('/api/item/'):
                self.respond(STUDIO.item(path.rsplit('/', 1)[-1]))
            elif path.startswith('/api/waveform/'):
                item = STUDIO.item(path.rsplit('/', 1)[-1])
                bins = int(get('bins', '700'))
                if not 100 <= bins <= 11200:
                    raise ValueError('Waveform detail must be between 100 and 11200 points.')
                self.respond(waveform(item['path'], Path(item['path']).stat().st_mtime, bins))
            elif path.startswith('/api/audio/'):
                self.file(STUDIO.media_path(path.rsplit('/', 1)[-1]))
            elif path.startswith('/api/export/'):
                item = STUDIO.item(path.rsplit('/', 1)[-1])
                source = STUDIO.media_path(item['id'])
                format = get('format', 'ogg')
                if format not in ('wav', 'mp3', 'ogg'):
                    raise ValueError('Choose WAV, OGG or MP3.')
                if source.suffix == '.' + format:
                    self.file(source, True)
                else:
                    with tempfile.TemporaryDirectory(prefix='fx-export-', dir=STUDIO.data) as folder:
                        target = Path(folder) / ('sound.' + format)
                        STUDIO.convert(source, target, format)
                        self.file(target, True)
            else:
                if path not in ('/', '/app.js', '/styles.css', '/assets/wik-dev.png'):
                    self.respond({'error': 'This view does not exist.'}, 404)
                    return
                self.file(ROOT / 'ui' / ('index.html' if path == '/' else path[1:]))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except KeyError as e:
            self.respond({'error': str(e).strip("'")}, 404)
        except (ValueError, FileNotFoundError) as e:
            self.respond({'error': str(e)}, 400)
        except Exception as e:
            print(type(e).__name__, str(e), flush=True)
            self.respond({'error': 'The local service could not complete this action. ' + str(e)}, 500)

    def do_POST(self):
        try:
            if not self.gate():
                return
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{PORT}':
                self.respond({'error': 'Request from another application denied.'}, 403)
                return
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('The request must contain JSON.')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= (32000 if self.path.startswith('/agent/v1/') else 16000):
                raise ValueError('The request is too large.')
            data = json.loads(self.rfile.read(size) or '{}')
            if not isinstance(data, dict):
                raise ValueError('The request must contain a JSON object.')
            path = urllib.parse.urlparse(self.path).path
            if path == '/api/generate':
                self.respond(STUDIO.enqueue(data), 202)
            elif path == '/api/generation-format':
                self.respond(STUDIO.set_generation_format(data.get('format')))
            elif path.startswith('/api/regenerate/'):
                self.respond(STUDIO.regenerate(path.rsplit('/', 1)[-1]), 202)
            elif path == '/api/agents':
                self.respond(ACCESS.configure(data, STUDIO))
            elif path == '/api/projects':
                self.respond(STUDIO.create_project(data))
            elif path == '/api/project-update':
                self.respond(STUDIO.update_project(data['project_id'], data))
            elif path == '/api/project-delete':
                self.respond(STUDIO.delete_project(data['project_id'], data))
            elif path == '/api/project-sound':
                self.respond(STUDIO.set_project_sound(data['project_id'], data['sound_id'], data.get('included', True)))
            elif path.startswith('/agent/v1/'):
                self.respond(AGENTS.post(path[len('/agent/v1'):], data), 202 if path in ('/agent/v1/generate', '/agent/v1/packs') else 200)
            elif path.startswith('/api/cancel/'):
                self.respond(STUDIO.cancel(path.rsplit('/', 1)[-1]))
            elif path.startswith('/api/favorite/'):
                if not isinstance(data.get('favorite'), bool):
                    raise ValueError('Favorite must be true or false.')
                self.respond(STUDIO.favorite(path.rsplit('/', 1)[-1], data['favorite']))
            elif path.startswith('/api/trim/'):
                self.respond({'item': STUDIO.set_trim(path.rsplit('/', 1)[-1], data)})
            elif path.startswith('/api/prepare-drag/'):
                self.respond(STUDIO.prepare_drag(path.rsplit('/', 1)[-1]))
            elif path == '/api/setup':
                self.respond(STUDIO.setup(data['model']) if 'model' in data else STUDIO.setup(), 202)
            elif path == '/api/cancel-setup':
                self.respond(STUDIO.cancel_setup())
            else:
                self.respond({'error': 'This action does not exist.'}, 404)
        except Conflict as e:
            self.respond({'error': str(e)}, 409)
        except FileExistsError:
            self.respond({'error': 'This export already exists. Choose a new name or folder; existing files are preserved.'}, 409)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            self.respond({'error': str(e)}, 400)
        except KeyError as e:
            self.respond({'error': str(e).strip("'")}, 404)
        except Exception as e:
            self.respond({'error': str(e)}, 500)

class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

server = LocalServer(('127.0.0.1', PORT), Handler)
STUDIO = Studio()
ACCESS = AgentAccess(STUDIO.data)
AGENTS = AgentAPI(STUDIO, ACCESS)
def shutdown(signum, frame):
    STUDIO.close()
    threading.Thread(target=server.shutdown, daemon=True).start()
signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
print(f'FX Studio ready at http://127.0.0.1:{PORT}', flush=True)
try:
    server.serve_forever()
finally:
    STUDIO.close()
    server.server_close()
