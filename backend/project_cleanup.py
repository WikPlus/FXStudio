"""Delete app-owned project media atomically; shared and external assets survive."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil

OWNED_FOLDERS = {'audio', 'edits', 'drag-exports', 'jobs'}


def owned_path(studio, path):
    path = Path(path)
    root = studio.data.resolve()
    try:
        relative = path.relative_to(studio.data)
    except ValueError:
        return None
    if not relative.parts or relative.parts[0] not in OWNED_FOLDERS:
        return None
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        return None
    if any((studio.data / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts))):
        return None
    if path.resolve().is_relative_to(studio.library_root.resolve()):
        return None
    return path


def recover_deletions(studio):
    root = studio.data / '.project-deletions'
    if not root.exists():
        return
    if root.is_symlink():
        raise ValueError('The project deletion folder must not be a symbolic link.')
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('The project deletion folder contains an unexpected entry.')
        manifest = folder / 'manifest.json'
        if not manifest.exists():
            # A crash before writing the journal can leave an empty directory.
            folder.rmdir()
            continue
        plan = json.loads(manifest.read_text(encoding='utf-8'))
        if studio.rows('SELECT id FROM projects WHERE id=?', (plan['project_id'],)):
            for index, relative in enumerate(plan['files']):
                target = owned_path(studio, studio.data / relative)
                staged = folder / str(index)
                if target is None or staged.is_symlink():
                    raise ValueError('A project deletion recovery path is invalid.')
                if staged.exists():
                    if target.exists():
                        raise ValueError('Project recovery found a conflicting audio file; its backup is retained.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, target)
        shutil.rmtree(folder)


def deletion_plan(studio, project_id):
    project = studio.project(project_id)
    memberships = studio.rows('SELECT sound_id FROM project_sounds WHERE project_id=?', (project_id,))
    ids = {row['sound_id'] for row in memberships}
    all_items = studio.rows('SELECT * FROM items')
    other_ids = {row['sound_id'] for row in studio.rows('SELECT sound_id FROM project_sounds WHERE project_id<>?', (project_id,))}
    removed = [item for item in all_items if item['id'] in ids and item['id'] not in other_ids]
    removed_ids = {item['id'] for item in removed}
    jobs, deleted_jobs, updated_jobs, blocked = studio.rows('SELECT * FROM jobs'), [], [], []
    for job in jobs:
        settings = json.loads(job['settings'])
        kept = [item for item in all_items if item['job_id'] == job['id'] and item['id'] not in removed_ids]
        affected = settings.get('project_id') == project_id or settings.get('replace_id') in removed_ids or any(item['job_id'] == job['id'] for item in removed)
        referenced = settings.get('reference_id') in removed_ids
        if (affected or referenced) and job['state'] in ('queued', 'running', 'cancelling'):
            blocked.append(job['id'])
        if affected:
            if kept:
                if settings.get('project_id') == project_id:
                    settings.pop('project_id', None)
                    updated_jobs.append((job['id'], settings))
            else:
                deleted_jobs.append(job['id'])
    revisions = [row for row in studio.rows('SELECT * FROM sound_revisions') if row['sound_id'] in removed_ids]
    sources = [Path(item['path']) for item in removed] + [Path(json.loads(row['item'])['path']) for row in revisions]
    protected = {Path(item['path']).resolve() for item in all_items if item['id'] not in removed_ids}
    protected.update(Path(item['path']).resolve() for item in studio.library.values())
    protected.update(Path(json.loads(row['item'])['path']).resolve() for row in studio.rows('SELECT * FROM sound_revisions') if row['sound_id'] not in removed_ids)
    paths = set(sources)
    edits = studio.data / 'edits'
    if edits.is_dir():
        paths.update(path for path in edits.iterdir() if any(path.name.startswith(sound_id + '-') for sound_id in removed_ids))
    stems = {path.stem for path in paths}
    drag = studio.data / 'drag-exports'
    if drag.is_dir():
        paths.update(path for path in drag.iterdir() if path.stem.rsplit('--', 1)[-1] in stems)
    for job_id in deleted_jobs:
        paths.update(studio.logs.glob(job_id + '.*'))
        paths.update(studio.logs.glob(job_id + '-reference.*'))
    paths = sorted((path for path in paths if owned_path(studio, path) and path.is_file() and path.resolve() not in protected), key=str)
    revision = hashlib.sha256(json.dumps([project['name'], sorted(ids), sorted(other_ids & ids),
        [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths], sorted(deleted_jobs)], sort_keys=True).encode()).hexdigest()
    public = {'project_id': project_id, 'name': project['name'], 'generated_sounds': len(removed),
              'shared_sounds_kept': len(ids & other_ids), 'library_links_removed': len(ids - {item['id'] for item in all_items}),
              'files': len(paths), 'bytes': sum(path.stat().st_size for path in paths),
              'blocked_jobs': blocked, 'can_delete': not blocked, 'revision': revision,
              'note': 'Shared sounds, the read-only sound library and files exported outside FX Studio are preserved.'}
    return public, removed_ids, deleted_jobs, updated_jobs, paths


def delete_project(studio, project_id, raw):
    with studio.render_lock, studio.lock:
        public, removed_ids, deleted_jobs, updated_jobs, paths = deletion_plan(studio, project_id)
        if raw.get('confirm_name') != public['name']:
            raise ValueError('Confirm deletion with the exact project name.')
        if not public['can_delete']:
            raise ValueError('Finish or cancel the affected generation jobs before deleting this project.')
        if raw.get('revision') and raw['revision'] != public['revision']:
            raise ValueError('The project changed. Review the deletion again before confirming.')
        recover_deletions(studio)
        folder = studio.data / '.project-deletions' / secrets.token_hex(12)
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps({'project_id': project_id,
            'files': [str(path.relative_to(studio.data)) for path in paths]}), encoding='utf-8')
        try:
            for index, path in enumerate(paths):
                os.replace(path, folder / str(index))
            with studio.db:
                studio.db.execute('DELETE FROM project_sounds WHERE project_id=?', (project_id,))
                for sound_id in removed_ids:
                    studio.db.execute('DELETE FROM items WHERE id=?', (sound_id,))
                    studio.db.execute('DELETE FROM sound_trims WHERE item_id=?', (sound_id,))
                    studio.db.execute('DELETE FROM sound_revisions WHERE sound_id=?', (sound_id,))
                for job_id in deleted_jobs:
                    studio.db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
                for job_id, settings in updated_jobs:
                    studio.db.execute('UPDATE jobs SET settings=? WHERE id=?', (json.dumps(settings), job_id))
                if studio.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_packs'"):
                    deleted_packs = []
                    for pack in studio.rows('SELECT * FROM agent_packs'):
                        jobs = [job_id for job_id in json.loads(pack['jobs']) if job_id not in deleted_jobs]
                        if jobs:
                            studio.db.execute('UPDATE agent_packs SET jobs=? WHERE id=?', (json.dumps(jobs), pack['id']))
                        else:
                            deleted_packs.append(pack['id'])
                            studio.db.execute('DELETE FROM agent_packs WHERE id=?', (pack['id'],))
                    for request in studio.rows('SELECT * FROM agent_requests'):
                        result = json.loads(request['result'])
                        if result.get('id') in deleted_jobs + deleted_packs:
                            result.update(deleted=True, message='This result was deleted with its project. Use a new request_id for new work.')
                            studio.db.execute('UPDATE agent_requests SET result=? WHERE id=?', (json.dumps(result), request['id']))
                        elif 'jobs' in result:
                            result['jobs'] = [job for job in result['jobs'] if job['id'] not in deleted_jobs]
                            studio.db.execute('UPDATE agent_requests SET result=? WHERE id=?', (json.dumps(result), request['id']))
                for item in studio.rows('SELECT id,settings FROM items'):
                    settings = json.loads(item['settings'])
                    if settings.get('project_id') == project_id:
                        settings.pop('project_id', None)
                        studio.db.execute('UPDATE items SET settings=? WHERE id=?', (json.dumps(settings), item['id']))
                studio.db.execute('DELETE FROM projects WHERE id=?', (project_id,))
        except Exception:
            # The transaction rolled back; the journal restores all staged files.
            recover_deletions(studio)
            raise
        # If cleanup fails (or the app closes now), startup finishes it using the journal.
        recover_deletions(studio)
        return {**public, 'deleted': True, 'sound_ids': sorted(removed_ids)}
