"""Progress adapters for the official platform CLIs; one cancellable process."""
import json
import os
import sys
import types
from pathlib import Path
from runtime_paths import runtime_folder, runtime_kind, model_folder

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = runtime_folder()
sys.path.insert(0, str(RUNTIME / 'scripts'))


def event(**values):
    print('FX_EVENT ' + json.dumps(values), flush=True)


if runtime_kind() == 'tflite':
    # The upstream 'models' namespace must not resolve to our models.py.
    package = types.ModuleType('models')
    package.__path__ = [str(RUNTIME / 'models')]
    sys.modules['models'] = package
    import sa3_tflite as engine
    manifest = json.loads((ROOT / 'backend/windows_model.json').read_text(encoding='utf-8'))
    paths = {'models/tflite/' + file['name']: model_folder() / file['name']
             for file in manifest['files']}
    def local_weight(relative, verbose=True):
        target = paths.get(str(relative))
        if target is None or not target.is_file():
            raise FileNotFoundError('Medium is incomplete. Resume the model download in Setup.')
        return target
    engine.ensure_local = local_weight
    engine.is_present = lambda relative: str(relative) in paths and paths[str(relative)].is_file()
    original_stage = engine.stage
    def stage(tag, text, *args, **kwargs):
        label = text.lower()
        number = 1 if 't5gemma' in label else 2 if 'encode init' in label else 3 if 'dit' in label else 4
        event(stage=number, message=text)
        return original_stage(tag, text, *args, **kwargs)
    original_sample = engine.P.sample
    def sample(*args, **kwargs):
        prior = kwargs.get('on_step')
        def step(i, total):
            event(stage=3, step=i, total=total)
            if prior:
                prior(i, total)
        kwargs['on_step'] = step
        return original_sample(*args, **kwargs)
    engine.P.sample = sample
else:
    import sa3_mlx as engine
    if os.environ.get('FX_MODEL_DIR'):
        def local_weight(relative, verbose=True):
            target = model_folder() / Path(relative).name
            if not target.is_file():
                raise FileNotFoundError('Medium is incomplete. Resume the model download in Setup.')
            return target
        engine.ensure_local = local_weight
        engine.is_present = lambda relative: (model_folder() / Path(relative).name).is_file()
    original_stage = engine.stage
    def stage(tag, text, *args, **kwargs):
        number = int(tag[1]) if tag.startswith('[') and len(tag) > 1 and tag[1].isdigit() else 0
        event(stage=number, message=text)
        return original_stage(tag, text, *args, **kwargs)
    original_sample = engine.sample_flow_pingpong
    def sample(*args, **kwargs):
        prior = kwargs.get('on_step')
        def step(i, total):
            event(stage=3, step=i, total=total)
            if prior:
                prior(i, total)
        kwargs['on_step'] = step
        return original_sample(*args, **kwargs)
    engine.sample_flow_pingpong = sample

engine.stage = stage
engine.main()
