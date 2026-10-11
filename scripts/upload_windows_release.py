"""Attach audited native CI downloads to an existing draft; never publish it."""
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from package_windows import audit_zip


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def main():
    repo = os.environ['GH_REPO']
    run_id = os.environ['FX_TESTED_RUN_ID']
    tag = os.environ['FX_RELEASE_TAG']
    if not re.fullmatch(r'[0-9]+', run_id) or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?', tag):
        raise ValueError('Invalid run ID or release tag')
    run = json.loads(gh('api', f'repos/{repo}/actions/runs/{run_id}'))
    workflow = json.loads(gh('api', f'repos/{repo}/actions/workflows/windows.yml'))
    if (run['conclusion'] != 'success' or run['workflow_id'] != workflow['id']
            or run['head_repository']['full_name'] != repo
            or run['head_branch'] != 'main' or run['event'] != 'workflow_dispatch'):
        raise ValueError('A successful manual native Windows run from this repository is required')
    release = json.loads(gh('release', 'view', tag, '--repo', repo, '--json', 'isDraft'))
    if not release['isDraft']:
        raise ValueError('Only an existing draft release may be changed')
    with tempfile.TemporaryDirectory(prefix='fx-release-') as temp:
        folder = Path(temp)
        downloads = folder / 'downloads'
        reports = folder / 'reports'
        gh('run', 'download', run_id, '--repo', repo, '--name', 'FXStudio-Windows-x64', '--dir', str(downloads))
        gh('run', 'download', run_id, '--repo', repo, '--name', 'Windows-test-reports', '--dir', str(reports))
        behavior = json.loads((reports / 'behavior-tests.json').read_text())
        if (behavior['platform'] != 'win32' or behavior['passed'] is not True
                or behavior['tests'] < 1 or any(behavior[key] for key in ('failures', 'errors', 'skipped'))):
            raise ValueError('Windows behavior tests did not pass completely')
        for name in ('windows-bundle-acceptance.json', 'windows-installer-acceptance.json', 'windows-model-acceptance.json'):
            report = json.loads((reports / name).read_text())
            required = ('standalone', 'trim_export_drag_path', 'mp3_roundtrip', 'restart_persistence',
                        'bundled_service_start', 'bundled_mcp_20_tools', 'bundled_mcp_project_workflow', 'bundled_agent_cli')
            if report['platform'] != 'win32' or not all(report[key] is True for key in required):
                raise ValueError('Incomplete native acceptance: ' + name)
            if 'installer' in name and report['silent_installer'] != 'passed':
                raise ValueError('The installer did not pass')
            if 'model' in name:
                if (report['model_generation'] != 'passed' or report['sample_rate'] != 44100
                        or not math.isfinite(report['peak']) or report['peak'] <= .001
                        or not math.isfinite(report['generation_seconds']) or report['generation_seconds'] <= 0):
                    raise ValueError('Real Medium inference did not pass')
        assets = []
        for name in ('FXStudio-Windows-x64.zip', 'FXStudio-Windows-x64-Setup.exe'):
            asset = downloads / name
            checksum = downloads / (name + '.sha256')
            expected = checksum.read_text().strip().split()
            with asset.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if expected != [actual, name]:
                raise ValueError('Download checksum mismatch: ' + name)
            assets.extend((str(asset), str(checksum)))
        audit_zip(downloads / 'FXStudio-Windows-x64.zip')
        with (downloads / 'FXStudio-Windows-x64-Setup.exe').open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('Installer is not a Windows executable')
        gh('release', 'upload', tag, *assets, '--repo', repo, '--clobber')
        print(f'Attached verified Windows assets from {run["head_sha"]} to draft {tag}.')


if __name__ == '__main__':
    main()
