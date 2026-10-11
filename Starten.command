#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h}"
cd "$TASK_ROOT"
unset ELECTRON_RUN_AS_NODE
export HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
FX_EXECUTABLE="$TASK_ROOT/.runtime/FX Studio.app/Contents/MacOS/Electron"
if [[ ! -x "$FX_EXECUTABLE" || ! -x "$TASK_ROOT/.venv/bin/python" ]]; then
  print 'FX Studio setup is incomplete. Run Einrichten.command in the same folder.'
  read '?Press Enter to close.'
  exit 1
fi
# Foundation reads this before Electron starts, including native file dialogs.
exec "$FX_EXECUTABLE" -AppleLanguages '(en)' -AppleLocale en_US
