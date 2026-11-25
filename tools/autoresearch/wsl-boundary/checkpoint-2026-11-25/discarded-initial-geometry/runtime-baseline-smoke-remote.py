"""Run the existing resize workflow once against the exact baseline GUI."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time
import traceback

ROOT = Path('/home/max/benchmarks/branchline-boundary')
SOURCE = ROOT / 'initial-editor-geometry-b2de070-071ee12ca22b-input/source'
BINARY = ROOT / 'binaries/checkpoint-b2de070/branchline'
OUTPUT = ROOT / ('geometry-baseline-smoke-' + sys.argv[1])
OUTPUT.mkdir(exist_ok=False)
assert hashlib.sha256(BINARY.read_bytes()).hexdigest() == '78106ff431e6433195867048f5fae946bb1e63cc0f04f23d668be32956c444c4'
sys.path.insert(0, str(SOURCE / 'tools'))
import smoke_native as smoke
import check_diff_resize as resize
import check_review_context as context
spec = importlib.util.spec_from_file_location('canonical_cleanup', SOURCE / 'tools/autoresearch/wsl-boundary/launch_linux.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
os.environ.update(DISPLAY=':0', BRANCHLINE_MCP_PORT='28869')
identity = launcher.process_info(os.getpid())
state = {'kind': 'existing-native-smoke-workflows', 'controller': identity, 'binary': str(BINARY),
         'binary_sha256': hashlib.sha256(BINARY.read_bytes()).hexdigest(), 'output': str(OUTPUT),
         'status': 'running', 'started_unix': time.time(), 'stages': []}
original_tmp = smoke.tempfile.TemporaryDirectory
original_fixture = smoke.fixture
temps = []
def remember_tmp(*args, **kwargs):
    temporary = original_tmp(*args, **kwargs)
    temps.append(Path(temporary.name))
    return temporary
smoke.tempfile.TemporaryDirectory = remember_tmp
def save():
    (OUTPUT / 'result.json').write_text(json.dumps(state, indent=2) + '\n')
def expire(_signum, _frame): raise TimeoutError('Native smoke exceeded240seconds')
signal.signal(signal.SIGALRM, expire)
signal.alarm(240)
save()
print(json.dumps({'controller': identity, 'output': str(OUTPUT)}), flush=True)
try:
    for name, fixture, exercise in [('resize', original_fixture, resize.exercise)]:
        with socket.socket() as check: check.bind(('127.0.0.1', 28869))
        stage = {'name': name, 'started_unix': time.time(), 'correct': False, 'owned_processes_stopped': []}
        state['stages'].append(stage)
        smoke.fixture, smoke.exercise = fixture, exercise
        sys.argv = ['existing-native-smoke', '--binary', str(BINARY), '--screenshot', str(OUTPUT / (name + '.png'))]
        saved_out, saved_err = os.dup(1), os.dup(2)
        try:
            with (OUTPUT / (name + '.log')).open('w') as log:
                os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
                smoke.main()
            stage['correct'] = True
        finally:
            sys.stdout.flush(); sys.stderr.flush()
            os.dup2(saved_out, 1); os.dup2(saved_err, 2)
            os.close(saved_out); os.close(saved_err)
            for profile in temps:
                for process in launcher.profile_processes(BINARY, profile):
                    stage['owned_processes_stopped'].append(process)
                    launcher.terminate(process)
            deadline = time.monotonic() + 8
            while any(launcher.profile_processes(BINARY, profile) for profile in temps) and time.monotonic() < deadline:
                time.sleep(.05)
            assert not any(launcher.profile_processes(BINARY, profile) for profile in temps)
            with socket.socket() as check:
                check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                check.bind(('127.0.0.1', 28869))
            stage.update(finished_unix=time.time(), owned_profile_processes_absent=True, mcp_port_free=True)
            save()
        print(json.dumps({'stage': name, 'correct': stage['correct'], 'cleanup': stage['owned_processes_stopped']}), flush=True)
    state['status'] = 'complete-correct-stopped'
except BaseException:
    state['status'] = 'failed-no-retry'
    state['error'] = traceback.format_exc()
finally:
    signal.alarm(0)
    state['finished_unix'] = time.time()
    save()
    print(json.dumps(state), flush=True)
if state['status'] != 'complete-correct-stopped': raise SystemExit(1)
