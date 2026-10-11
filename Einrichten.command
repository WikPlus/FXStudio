#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h}"
cd "$TASK_ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.pyenv/shims:$PATH"
export HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
if ! command -v node >/dev/null || ! command -v npm >/dev/null || ! command -v uv >/dev/null; then
  print 'Setup requires Node.js/npm and uv. See README.md for details.'
  read '?Press Enter to close.'
  exit 1
fi
if [[ ! -f .runtime/stable-audio-3/optimized/mlx/scripts/sa3_mlx.py ]]; then
  mkdir -p .runtime
  git clone --filter=blob:none --no-checkout https://github.com/Stability-AI/stable-audio-3.git .runtime/stable-audio-3
  git -C .runtime/stable-audio-3 sparse-checkout set optimized/mlx
  git -C .runtime/stable-audio-3 checkout 3a82c807b69cf4b7c5c05270011a5d5e47abac18
fi
if [[ ! -x .venv/bin/python ]]; then uv venv --python 3.11 .venv; fi
uv pip install --python .venv/bin/python -r requirements.txt
npm ci --ignore-scripts
node node_modules/electron/install.js
.venv/bin/python scripts/prepare_desktop.py
.venv/bin/python scripts/download_models.py
print 'FX Studio is set up. Launch Starten.command.'
read '?Press Enter to close.'
