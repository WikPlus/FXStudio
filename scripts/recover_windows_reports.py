"""Recover native reports printed by a successful CI run with missing artifacts."""
import json
import re
from pathlib import Path


def recover(log, folder):
    steps = {}
    for line in log.splitlines():
        match = re.match(r'[^\t]+\t([^\t]+)\t\ufeff?\d{4}-\d{2}-\d{2}T[^ ]+ (.*)', line)
        if match:
            steps.setdefault(match[1], []).append(match[2])
    build = '\n'.join(steps.get('Build native software, verify licenses, test and package', []))
    summary = re.search(r'(?m)^Ran (\d+) tests in ([\d.]+)s\n\nOK(?:\n|$)', build)
    if not summary or int(summary[1]) < 1:
        raise ValueError('No complete passing behavior test summary in native CI log')
    reports = {'behavior-tests.json': {'platform': 'win32', 'tests': int(summary[1]),
        'failures': 0, 'errors': 0, 'skipped': 0, 'passed': True,
        'real_model_generation': False, 'personal_library_used': False}}
    decoder = json.JSONDecoder()
    for step in ('Build native software, verify licenses, test and package',
                 'Real Medium generation (explicit opt-in only)'):
        text = '\n'.join(steps.get(step, []))
        for match in re.finditer(r'(?m)^\{', text):
            try:
                report, _ = decoder.raw_decode(text[match.start():])
            except json.JSONDecodeError:
                continue
            if not isinstance(report, dict) or report.get('platform') != 'win32' or report.get('standalone') is not True:
                continue
            if step.startswith('Real Medium') and report.get('model_generation') == 'passed':
                name = 'windows-model-acceptance.json'
            elif step.startswith('Build native') and report.get('silent_installer') == 'passed':
                name = 'windows-installer-acceptance.json'
            elif step.startswith('Build native') and report.get('model_generation') == 'not_run' and 'silent_installer' not in report:
                name = 'windows-bundle-acceptance.json'
            else:
                continue
            if name in reports:
                raise ValueError('Duplicate native report in CI log: ' + name)
            reports[name] = report
    if len(reports) != 4:
        raise ValueError('Native CI log omits a bundle, installer or real model report')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, report in reports.items():
        (folder / name).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return reports
