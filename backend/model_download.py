"""Pinned, resumable model downloads, verified before exposing usable files."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from runtime_paths import expose_cached_model


def valid_file(path, size):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != size:
        return False
    if path.suffix == '.npz':
        return zipfile.is_zipfile(path)
    if path.suffix == '.tflite':
        with path.open('rb') as stream:
            return stream.read(8)[4:8] == b'TFL3'
    return False


def download_bundle(spec, folder, download=None, metadata=None, progress=None):
    from huggingface_hub import HfApi, hf_hub_download, constants
    from tqdm.auto import tqdm
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    required = spec['files']
    total = sum(file['size'] for file in required)
    missing = [file for file in required if not valid_file(folder / file['name'], file['size'])]
    completed = total - sum(file['size'] for file in missing)
    progress = progress or (lambda data: print('FX_DOWNLOAD ' + json.dumps(data), flush=True))
    if not missing:
        progress({'phase': 'ready', 'bytes': total, 'total': total})
        return
    cache = Path(constants.HF_HUB_CACHE)
    existing = next((parent for parent in [cache, *cache.parents] if parent.is_dir()), folder)
    if shutil.disk_usage(existing).free < sum(file['size'] for file in missing) + 512 * 1024**2:
        raise RuntimeError('Not enough free disk space for Medium. Free some space and select Retry download.')
    if any(not file.get('sha256') for file in missing):
        info = metadata or HfApi(token=False).model_info(spec['repo'], revision=spec['revision'], files_metadata=True)
        published = {file.rfilename: file for file in info.siblings}
        for file in missing:
            remote = published[file['remote']]
            if remote.size != file['size'] or not remote.lfs:
                raise RuntimeError('The model revision metadata does not match: ' + file['name'])
            file['sha256'] = remote.lfs.sha256
    download = download or hf_hub_download
    for file in missing:
        progress({'phase': 'downloading', 'file': file['name'], 'bytes': completed, 'total': total})
        class DownloadProgress(tqdm):
            def update(self, amount=1):
                result = super().update(amount)
                if result:
                    progress({'phase': 'downloading', 'file': file['name'],
                              'bytes': min(total, completed + int(self.n)), 'total': total})
                return result
        for attempt in range(2):
            options = {'force_download': True} if attempt else {}
            cached = Path(download(repo_id=spec['repo'], revision=spec['revision'],
                                   filename=file['remote'], token=False, tqdm_class=DownloadProgress, **options))
            failure = 'The downloaded model file is incomplete: ' + file['name']
            if valid_file(cached, file['size']):
                progress({'phase': 'verifying', 'file': file['name'], 'bytes': completed + file['size'], 'total': total})
                with cached.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest == file['sha256']:
                    break
                failure = 'The model checksum does not match: ' + file['name']
            if attempt:
                raise RuntimeError(failure + '. Select Retry download to try again.')
            # Replace a damaged HF cache entry once instead of returning it on every retry.
            progress({'phase': 'downloading', 'file': file['name'], 'bytes': completed, 'total': total})
        expose_cached_model(cached, folder / file['name'])
        completed += file['size']
    progress({'phase': 'ready', 'bytes': total, 'total': total})
