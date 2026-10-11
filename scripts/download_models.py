"""Download only Medium for the current platform. Never accept model gates."""
import argparse
import os
import sys
from pathlib import Path

os.environ.update(HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1', DO_NOT_TRACK='1')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from models import DEFAULT_MODEL, MODELS, weight_spec
from runtime_paths import model_folder
from model_download import download_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=list(MODELS), default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        download_bundle(weight_spec(args.model), model_folder())
    except Exception as error:
        from huggingface_hub.errors import GatedRepoError
        if isinstance(error, GatedRepoError):
            raise SystemExit('Model access requires your own approval on Hugging Face. FX Studio does not accept agreements for you.')
        raise SystemExit(str(error))
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
