"""Only the explicitly selected local sound models; no eager loading."""
import json
from pathlib import Path
DEFAULT_MODEL = 'medium'
WEIGHTS_REPO = 'stabilityai/stable-audio-3-optimized'
WEIGHTS_REVISION = 'da6edc54ddba10bfd79a077102ded687f80e882b'
SHARED_FILE = ('t5gemma_f16.npz', 567_443_068)
MODELS = {
    'medium': {
        'name': 'Stable Audio 3 Medium', 'decoder': 'same-l',
        'url': 'https://huggingface.co/stabilityai/stable-audio-3-medium',
        'files': [SHARED_FILE, ('dit_medium_f16.npz', 2_907_300_946),
                  ('same_l_decoder_f32.npz', 1_704_311_976), ('same_l_encoder_f32.npz', 1_704_313_504)],
    },
}

for model in MODELS.values():
    model.update(engine='Official MLX · Apple Silicon', runtime='MLX', max_seconds=30,
                 max_steps=16, default_steps=8, default_cfg=1, editing=True, negative_prompt=True)
def selected_model(value=DEFAULT_MODEL):
    if not isinstance(value, str) or value not in MODELS:
        raise ValueError('Choose Stable Audio 3 Medium. Small SFX and UNITE-AUDIO have been removed.')
    return MODELS[value]


def weight_spec(model_id=DEFAULT_MODEL, runtime=None):
    model = selected_model(model_id)
    if runtime is None:
        from runtime_paths import runtime_kind
        runtime = runtime_kind()
    if runtime == 'tflite':
        return json.loads((Path(__file__).parent / 'windows_model.json').read_text())
    return {'repo': WEIGHTS_REPO, 'revision': WEIGHTS_REVISION,
            'files': [{'name': name, 'size': size, 'remote': 'MLX/' + name}
                      for name, size in model['files']]}

def generation_prompt(model_id, prompt):
    # Medium handles music and SFX; use the upstream SFX conditioning tag.
    if model_id == 'medium' and not prompt.lower().startswith('tracktype: sfx,'):
        return 'TrackType: SFX, ' + prompt
    return prompt
