"""Download process fixture: events and interruption, never actual model files."""
import json
import sys
import time
from pathlib import Path
mode, folder = sys.argv[1], Path(sys.argv[2])
(folder / 'started').write_text('started')
if mode == 'failure' and not (folder / 'failed-once').exists():
    (folder / 'failed-once').write_text('failed')
    raise SystemExit('Network is unavailable')
for index in range(20):
    print('FX_DOWNLOAD '+json.dumps({'phase':'downloading','bytes':index*5,'total':100}),flush=True)
    time.sleep(.025 if mode != 'slow' else .5)
(folder / 'ready').write_text('ready')
print('DONE',flush=True)
