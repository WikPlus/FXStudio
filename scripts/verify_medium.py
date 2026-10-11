"""Opt-in hardware acceptance: closed app, one serial queue, actual MLX models."""
import json
import os
import socket
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from core import Studio

with socket.socket() as connection:
    connection.settimeout(1)
    if connection.connect_ex(('127.0.0.1', 3921)) == 0:
        raise SystemExit('FX Studio zuerst schließen, damit kein zweiter GPU-Auftrag startet.')

studio = Studio()
report = {'model_switch': [], 'worker_pids': []}
last_pid = None

def state(job_id):
    global last_pid
    job = next(job for job in studio.status()['jobs'] if job['id'] == job_id)
    with studio.lock:
        process = studio.process
        if process and process.pid != last_pid:
            if last_pid:
                try:
                    os.kill(last_pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('Das vorherige Modell ist noch im Speicher.')
            last_pid = process.pid
            report['worker_pids'].append(last_pid)
    return job

def wait(job_id):
    previous = None
    while True:
        job = state(job_id)
        mark = (job['state'], job['stage'], job['step'])
        if mark != previous:
            print(job['settings']['model'], job['state'], job['message'], job['elapsed'], flush=True)
            previous = mark
        if job['state'] not in ('queued', 'running', 'cancelling'):
            return job
        time.sleep(.025)

def check(job_id):
    job = wait(job_id)
    assert job['state'] == 'completed', job
    items = studio.items(job_id=job_id)
    for item in items:
        audio, rate = sf.read(item['path'], always_2d=True)
        assert rate == 44100 and audio.shape[1] == 2
        assert abs(len(audio) / rate - job['settings']['seconds']) < .05
        assert np.isfinite(audio).all() and np.max(np.abs(audio)) > .001
        assert item['settings']['model'] == job['settings']['model']
        item['peak'] = round(float(np.max(np.abs(audio))), 4)
        item['rms'] = round(float(np.sqrt(np.mean(audio ** 2))), 4)
    lines = (studio.logs / (job_id + '.log')).read_text().splitlines()
    memory = [line.strip() for line in lines if 'GB' in line or 'MB' in line or 'Peak RAM' in line]
    return {'job': job, 'items': items, 'memory_report': memory}

try:
    assert all(model['ready'] for model in studio.status()['models'])
    ids = []
    for model in ('medium', 'medium', 'medium'):
        ids.append(studio.enqueue({'model': model, 'prompt': 'A heavy metal door slamming shut with a short echo, isolated sound effect, no music or voices', 'seconds': 3, 'steps': 8, 'seed': 52601})['id'])
    report['model_switch'] = [check(job_id) for job_id in ids]
    for previous, current in zip(report['model_switch'], report['model_switch'][1:]):
        assert current['job']['started'] >= previous['job']['finished']

    cancelled = studio.enqueue({'model': 'medium', 'prompt': 'Strong wind blowing through a dark stone tunnel, no music or voices', 'seconds': 30, 'steps': 16, 'seed': 52602})['id']
    recovery = studio.enqueue({'model': 'medium', 'prompt': 'An isolated camera shutter click', 'seconds': 2, 'steps': 8, 'seed': 52603})['id']
    while True:
        job = state(cancelled)
        if job['state'] not in ('queued', 'running'):
            raise AssertionError(job)
        with studio.lock:
            if job['stage'] == 3 and job['step'] >= 1 and studio.process:
                pid = studio.process.pid
                started = time.monotonic()
                studio.cancel(cancelled)
                break
        time.sleep(.01)
    stopped = wait(cancelled)
    assert stopped['state'] == 'cancelled' and not studio.items(job_id=cancelled)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError('Der abgebrochene Medium-Worker läuft noch.')
    report['cancel'] = {'pid': pid, 'seconds': round(time.monotonic() - started, 3)}
    report['recovery_medium'] = check(recovery)

    source = report['model_switch'][0]['items'][0]
    for mode in ('variation', 'inpaint'):
        settings = {'model': 'medium', 'mode': mode, 'reference_id': source['id'], 'prompt': 'A heavy metal door slamming with a deeper echo, isolated sound effect, no music or voices', 'seconds': 3, 'strength': .65, 'steps': 8, 'seed': 52604}
        if mode == 'inpaint':
            settings.update(start=.8, end=1.8)
        report[mode] = check(studio.enqueue(settings)['id'])

    exported = studio.data / 'acceptance-exports' / 'Medium-Metal-Door.mp3'
    exported.parent.mkdir(exist_ok=True)
    studio.convert(source['path'], exported, 'mp3')
    info = sf.info(str(exported))
    assert info.channels == 2 and abs(info.duration - 3) < .05
    report['mp3'] = {'path': str(exported), 'duration': info.duration}
    studio.close()
    studio = Studio()
    assert studio.item(source['id'])['settings']['model'] == 'medium'
    report['persistence'] = True
    output = studio.data / 'medium-acceptance.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('ABNAHME BESTANDEN', str(output), flush=True)
    print('ZEITEN', [(result['job']['settings']['model'], result['job']['elapsed']) for result in report['model_switch']], flush=True)
    print('SPEICHER', report['model_switch'][0]['memory_report'], flush=True)
finally:
    studio.close()
