#!/usr/bin/env python3
"""One released malformed-response gate, foreground and without retries."""
from pathlib import Path
import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import traceback

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'execution-plan.json').read_text())
OUT = HERE / 'evidence'
OUT.mkdir(exist_ok=False)
state = {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(') ', 1)[1].split()[19],
         'status': 'running', 'started': time.time(), 'plan': PLAN, 'phases': [], 'cleanup': []}
record = OUT / 'supervisor.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save():
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(record)


def run(name, command, environment, timeout=600):
    phase = {'name': name, 'argv': command, 'cwd': str(HERE), 'started': time.time(),
             'log': str(OUT / (name + '.log')), 'timeout_seconds': timeout}
    state['phases'].append(phase)
    state['current_phase'] = name
    with Path(phase['log']).open('wb') as log:
        child = subprocess.Popen(command, cwd=HERE, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        phase.update(pid=child.pid, start_ticks=Path('/proc', str(child.pid), 'stat').read_text().rsplit(') ', 1)[1].split()[19])
        save()
        print(json.dumps({'phase': name, 'child_pid': child.pid, 'start_ticks': phase['start_ticks'], 'log': phase['log']}), flush=True)
        try:
            phase['exit'] = child.wait(timeout=timeout)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            phase.update(finished=time.time(), reaped=child.poll() is not None, log_sha256=sha(phase['log']))
            save()
    if phase['exit'] != 0:
        raise RuntimeError(name + ' failed; no automatic retry: ' + phase['log'])
    return Path(phase['log'])


def artifact(log):
    paths = set()
    for line in log.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value.get('reason') == 'compiler-artifact' and value.get('profile', {}).get('test') and value.get('executable'):
            paths.add(value['executable'])
    assert len(paths) == 1, paths
    return Path(paths.pop())


def events():
    values = []
    for name in ['linux-native-client', 'windows-native-client']:
        path = OUT / (name + '.log')
        if not path.exists():
            continue
        for line in path.read_text(errors='replace').splitlines():
            if '{' not in line:
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(line[line.index('{'):])
            except ValueError:
                continue
            if value.get('phase') in ['fixture-installed', 'before-malformed-response', 'passed-before-connection-drop']:
                values.append(dict(value, test=name))
    return values


def cleanup_owned():
    proofs = events()
    state['test_events'] = proofs
    for value in proofs:
        if value['phase'] != 'before-malformed-response':
            continue
        native = value['native_identity']
        if value['test'] == 'linux-native-client':
            encoded = base64.b64encode(json.dumps(native).encode()).decode()
            script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$i=ConvertFrom-Json([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "')));$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$i.pid);$killed=$false;if($p -and $p.CreationDate.ToString('o') -eq $i.identity -and $p.ExecutablePath -eq $i.exe){$h=Get-Process -Id $p.ProcessId;$null=$h.Handle;$again=Get-CimInstance Win32_Process -Filter ('ProcessId='+$i.pid);if($again.CreationDate.ToString('o') -ne $i.identity){throw 'Native identity changed'};$h.Kill();$null=$h.WaitForExit(10000);$killed=$true};$left=Get-CimInstance Win32_Process -Filter ('ProcessId='+$i.pid);if($left -and $left.CreationDate.ToString('o') -eq $i.identity){throw 'Owned native worker remained'};@{pid=$i.pid;cleanup_killed=$killed;gone=$true}|ConvertTo-Json -Compress"
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=30, check=True)
            state['cleanup'].append(json.loads(result.stdout))
        else:
            proc = Path('/proc', str(native['pid']))
            killed = False
            try:
                fields = (proc / 'stat').read_text().rsplit(') ', 1)[1].split()
                if fields[19] == native['identity']:
                    assert str((proc / 'exe').resolve()) == native['exe']
                    handle = os.pidfd_open(native['pid'])
                    try:
                        signal.pidfd_send_signal(handle, signal.SIGKILL)
                        killed = True
                    finally:
                        os.close(handle)
            except (FileNotFoundError, ProcessLookupError):
                pass
            deadline = time.monotonic() + 5
            while proc.exists():
                try:
                    if (proc / 'stat').read_text().rsplit(') ', 1)[1].split()[19] != native['identity']:
                        break
                except FileNotFoundError:
                    break
                assert time.monotonic() < deadline, 'Owned native Linux PID remained'
                time.sleep(.05)
            state['cleanup'].append({'pid': native['pid'], 'cleanup_killed': killed, 'gone': True})
    unique = {}
    for value in proofs:
        if value['phase'] == 'fixture-installed':
            unique[value['owned_helper']] = value['owned_digest']
        if value['phase'] == 'before-malformed-response' and value['test'] == 'windows-native-client':
            unique[value['native_identity']['image']] = value['owned_digest']
    for name, digest in unique.items():
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
        path = Path(name)
        if len(name) > 2 and name[1] == ':':
            path = Path(subprocess.check_output(['/usr/bin/wslpath', '-u', name], text=True).strip())
        assert path.name in ['branchline-git-worker-' + digest, 'branchline-git-worker-' + digest + '.exe']
        existed = path.exists()
        if existed:
            assert sha(path) == digest, ('Owned cache bytes changed; preserve', str(path))
            path.unlink()
        state['cleanup'].append({'owned_cache': str(path), 'already_absent': not existed, 'removed': existed})


try:
    save()
    print(json.dumps({'supervisor_pid': state['pid'], 'start_ticks': state['start_ticks'], 'record': str(record)}), flush=True)
    for name, expected in PLAN['files'].items():
        assert sha(HERE / name) == expected, name
    state['source_files_verified_before'] = True
    env = dict(os.environ, PATH='/home/max/.cargo/bin:' + os.environ.get('PATH', ''),
               CARGO_BUILD_JOBS='1', CMAKE_BUILD_PARALLEL_LEVEL='1',
               CARGO_TARGET_DIR='/home/max/workspace/diff-tool/src-tauri/target',
               XWIN_MSVC_SYSROOT='/home/max/workspace/diff-tool/build/prebuilt-msvc/windows-msvc-sysroot',
               XWIN_CROSS_COMPILER='clang', XWIN_CACHE_DIR='/home/max/workspace/diff-tool/build/xwin')
    env.pop('RUSTFLAGS', None)
    state['environment'] = {k: env[k] for k in ['CARGO_BUILD_JOBS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'CARGO_TARGET_DIR', 'XWIN_MSVC_SYSROOT', 'XWIN_CROSS_COMPILER', 'XWIN_CACHE_DIR']}
    state['versions'] = {n: subprocess.check_output(c, env=env, text=True, timeout=30).strip() for n, c in
                         {'rustc': ['rustc', '-Vv'], 'cargo': ['cargo', '-V'], 'cargo_xwin': ['cargo', 'xwin', '--version']}.items()}
    windows = dict(env, RUSTFLAGS='-C target-feature=+crt-static')
    run('one-windows-fixture-build', ['cargo', 'xwin', 'build', '--offline', '--locked', '--release',
        '--manifest-path', 'windows-fixture/Cargo.toml', '--target', 'x86_64-pc-windows-msvc'], windows)
    compiled = Path(env['CARGO_TARGET_DIR']) / 'x86_64-pc-windows-msvc/release/branchline-malformed-response-fixture.exe'
    fixture = HERE / 'source/src-tauri/src/git/fixtures/malformed-windows.exe'
    assert not fixture.exists()
    shutil.copy2(compiled, fixture)
    assert sha(compiled) == sha(fixture)
    imports = subprocess.check_output(['objdump', '-p', str(fixture)], text=True)
    (OUT / 'windows-fixture-imports.txt').write_text(imports)
    assert not any(x in imports.lower() for x in ['vcruntime', 'msvcp', 'ucrtbase'])
    state['fixture'] = {'path': str(fixture), 'sha256': sha(fixture), 'bytes': fixture.stat().st_size, 'static_crt_import_check': True}
    save()
    name = PLAN['test_filter']
    linux = artifact(run('linux-focused-harness-build', ['cargo', 'test', '--offline', '--locked', '--manifest-path',
        'host-harness/Cargo.toml', '--no-run', '--message-format=json'], env))
    state['linux_test_executable'] = {'path': str(linux), 'sha256': sha(linux)}
    run('linux-native-client', [str(linux), name, '--ignored', '--exact', '--nocapture', '--test-threads=1'], env, 120)
    windows_test = artifact(run('windows-focused-harness-build', ['cargo', 'xwin', 'test', '--offline', '--locked', '--release',
        '--manifest-path', 'host-harness/Cargo.toml', '--target', 'x86_64-pc-windows-msvc', '--no-run', '--message-format=json'], windows))
    native = Path('/mnt/c/Users/max/branchline-bench/nmf252/test.exe')
    native.parent.mkdir(exist_ok=False)
    shutil.copy2(windows_test, native)
    assert sha(windows_test) == sha(native)
    state['windows_test_executable'] = {'path': str(native), 'sha256': sha(native)}
    run('windows-native-client', [str(native), name, '--ignored', '--exact', '--nocapture', '--test-threads=1'], env, 120)
    state['status'] = 'passed-both-native-malformed-response-cleanup-gates'
except BaseException:
    state.update(status='failed-no-automatic-retry', error=traceback.format_exc())
finally:
    try:
        cleanup_owned()
        for name, expected in PLAN['files'].items():
            assert sha(HERE / name) == expected, name
        state['source_files_verified_after'] = True
    except BaseException:
        state.update(cleanup_error=traceback.format_exc(), status='failed-no-automatic-retry')
    state['finished'] = time.time()
    save()
    print(json.dumps({'status': state['status'], 'record': str(record), 'error': state.get('error'),
                      'cleanup_error': state.get('cleanup_error')}), flush=True)
raise SystemExit(0 if state['status'].startswith('passed-') else 1)
