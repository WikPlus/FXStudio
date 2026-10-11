"""Real local HTTP/MCP integration with tiny test-only audio subprocesses."""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import core

RealStudio = core.Studio


def fixture(settings, seed, target, reference):
    return [sys.executable, '-u', str(ROOT / 'tests/fixture_worker.py'), settings['prompt'], str(target), str(settings['seconds'])]


core.Studio = lambda: RealStudio(command_factory=fixture)
runpy.run_path(str(ROOT / 'backend/server.py'), run_name='__main__')
