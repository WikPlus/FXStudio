"""Cancel complete worker trees on both supported desktop platforms."""
import os
import signal
import subprocess
import threading


def process_options():
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {'start_new_session': True}


def terminate_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        # No console is attached to a packaged Electron app, so CTRL_BREAK
        # cannot reliably stop Python children. taskkill handles the tree.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    def force():
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    threading.Thread(target=force, daemon=True).start()
