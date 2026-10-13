"""Exercise real HTTP routes with a temporary downloader, never model downloads."""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import core


class HTTPFixtureStudio(core.Studio):
    def __init__(self):
        super().__init__(command_factory=lambda settings, seed, target, reference: [sys.executable, '-u',
            str(ROOT / 'tests/fixture_worker.py'), settings['prompt'], str(target), str(settings['seconds'])],
            setup_command_factory=lambda model: [sys.executable, '-u',
            str(ROOT / 'tests/fixture_downloader.py'), 'success', str(self.data)])

    def model_status(self, model_id='medium'):
        result = super().model_status(model_id)
        result.update(ready=(self.data / 'ready').exists(), runtime_ready=True, dependencies=[])
        return result


core.Studio = HTTPFixtureStudio
runpy.run_path(str(ROOT / 'backend/server.py'), run_name='__main__')
