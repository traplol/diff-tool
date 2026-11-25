#!/usr/bin/env python3
"""One frozen Linux GUI build; no tests, worker build, or runtime launch."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import traceback

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'build-plan.json').read_text())
SOURCE = HERE / 'source'
OUTPUT = Path(PLAN['vm_output'])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def start_ticks(pid):
    return Path('/proc', str(pid), 'stat').read_text().rsplit(') ', 1)[1].split()[19]


def source_identity():
    for name, expected in PLAN['snapshot_files'].items():
        assert sha(SOURCE / name) == expected, ('Transferred file changed', name)
    value = {'git_head': PLAN['source']['git_head'],
             'files': {name: sha(SOURCE / name) for name in PLAN['source']['files']}}
    value['source_hash'] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert value == PLAN['source'], 'Frozen app source identity differs'
    return value


def guards(root):
    result = {}
    for name in ('index', 'config', 'HEAD'):
        path = Path(root) / '.git' / name
        before = path.stat()
        digest = sha(path)
        after = path.stat()
        def fields(info):
            return {'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
                    'inode': info.st_ino, 'device': info.st_dev, 'mode': info.st_mode}
        assert fields(before) == fields(after), (path, 'Changed while reading guard')
        result[name] = {'sha256': digest, **fields(after)}
    return result


def fingerprint(item, label):
    root = Path(item['root'])
    marker = json.loads((root / '.git/branchline-boundary-fixture.json').read_text())
    assert marker['status'] == 'complete' and marker['base'] == PLAN['kernel_base']
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GIT_NO_LAZY_FETCH='1')
    for name in ('GIT_INDEX_FILE', 'GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE'):
        assert not env.get(name), ('Unexpected repository routing', name)
    if item['platform'] == 'windows':
        shared = ('GIT_OPTIONAL_LOCKS', 'GIT_TERMINAL_PROMPT', 'GIT_NO_LAZY_FETCH')
        entries = [e for e in env.get('WSLENV', '').split(':') if e and e.split('/')[0] not in shared]
        env['WSLENV'] = ':'.join([*entries, *shared])
    commands = []

    def git(args):
        prefix = ['-c', 'diff.autoRefreshIndex=false'] if args[0] == 'diff' else []
        command = [item['git'], '--no-pager', '--literal-pathspecs', '-C', item['git_root'], *prefix, *args]
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=180, check=True)
        stem = label + '-' + item['platform'] + '-' + str(len(commands) + 1)
        (OUTPUT / (stem + '.stdout')).write_bytes(result.stdout)
        (OUTPUT / (stem + '.stderr')).write_bytes(result.stderr)
        commands.append({'argv': command, 'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
                         'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()})
        return result.stdout

    value = hashlib.sha256()
    for args in [
        ['rev-parse', 'HEAD'], ['show-ref'], ['ls-files', '--stage', '-z'],
        ['status', '--porcelain=v1', '-z', '--untracked-files=all'],
        ['diff', '--cached', '--binary', '--no-ext-diff'], ['diff', '--binary', '--no-ext-diff'],
    ]:
        value.update(git(args))
    for name in sorted(git(['ls-files', '--others', '--exclude-standard', '-z']).split(b'\0')):
        if name:
            value.update(name)
            value.update((root / os.fsdecode(name)).read_bytes())
    assert value.hexdigest() == PLAN['fixture_fingerprint'], (item['platform'], value.hexdigest())
    return {'sha256': value.hexdigest(), 'commands': commands}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM GEOMETRY BUILD RELEASED':
        parser.error('Wait for root: VM GEOMETRY BUILD RELEASED')
    OUTPUT.mkdir(exist_ok=False)
    state = {'pid': os.getpid(), 'start_ticks': start_ticks(os.getpid()), 'started': time.time(),
             'status': 'running', 'release': args.release, 'plan': PLAN}
    record = OUTPUT / 'supervisor.json'
    child = None

    def save():
        temporary = record.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(record)

    def interrupted(number, frame):
        raise KeyboardInterrupt('Supervisor interrupted by signal ' + str(number))

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, interrupted)
    try:
        save()
        print(json.dumps({'supervisor_pid': state['pid'], 'start_ticks': state['start_ticks'], 'record': str(record)}), flush=True)
        state['source_before'] = source_identity()
        assert not Path(PLAN['artifact']).exists(), 'Refusing to replace immutable GUI'
        original = Path(PLAN['helper']['source'])
        assert sha(original) == PLAN['helper']['sha256']
        helper = OUTPUT / 'embedded-windows-worker.exe'
        shutil.copy2(original, helper)
        assert sha(helper) == PLAN['helper']['sha256'] and helper.stat().st_size == PLAN['helper']['bytes']
        state['helper'] = {'path': str(helper), 'preserved_from': str(original), 'sha256': sha(helper), 'bytes': helper.stat().st_size}
        env = dict(os.environ, **PLAN['environment'], BRANCHLINE_GIT_WORKER_PATH=str(helper))
        env.pop('RUSTFLAGS', None)
        env['PATH'] = '/home/max/.cargo/bin:' + env.get('PATH', '')
        state['effective_build_environment'] = {key: env[key] for key in [*PLAN['environment'], 'BRANCHLINE_GIT_WORKER_PATH']}
        state['versions'] = {name: subprocess.check_output(command, env=env, text=True, timeout=30).strip()
                             for name, command in {'rustc': ['rustc', '-Vv'], 'cargo': ['cargo', '-V'],
                                 'cc': ['cc', '--version'], 'node': ['node', '--version'], 'npm': ['npm', '--version']}.items()}
        state['fixture_guards_before'] = {i['platform']: guards(i['root']) for i in PLAN['fixtures']}
        state['fixture_before'] = {i['platform']: fingerprint(i, 'before') for i in PLAN['fixtures']}
        assert state['fixture_guards_before'] == {i['platform']: guards(i['root']) for i in PLAN['fixtures']}
        phase = {'argv': ['./build.sh', '--no-bundle'], 'cwd': str(SOURCE), 'started': time.time(),
                 'log': str(OUTPUT / 'linux-gui-build.log')}
        state['build'] = phase
        save()
        with Path(phase['log']).open('wb') as log:
            child = subprocess.Popen(phase['argv'], cwd=SOURCE, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            phase.update(pid=child.pid, start_ticks=start_ticks(child.pid))
            save()
            print(json.dumps({'build_pid': child.pid, 'start_ticks': phase['start_ticks'], 'log': phase['log']}), flush=True)
            phase['exit'] = child.wait()
        phase.update(finished=time.time(), log_sha256=sha(phase['log']))
        save()
        assert phase['exit'] == 0, 'Build failed; inspect log'
        compiled = Path(env['CARGO_TARGET_DIR']) / 'release/branchline'
        data = compiled.read_bytes()
        assert data.startswith(b'\x7fELF') and helper.read_bytes() in data, 'GUI helper embedding differs'
        artifact = Path(PLAN['artifact'])
        artifact.parent.mkdir(parents=True, exist_ok=True)
        with artifact.open('xb') as output:
            output.write(data)
        shutil.copystat(compiled, artifact)
        assert sha(artifact) == sha(compiled)
        state['linux_gui'] = {'path': str(artifact), 'sha256': sha(artifact), 'bytes': len(data),
                             'embedded_helper_sha256': sha(helper), 'embedded_helper_verified': True,
                             'renderer': 'production default; no runtime launch'}
        assert sha(original) == PLAN['helper']['sha256'] and sha(helper) == PLAN['helper']['sha256']
        state['status'] = 'built; native correctness and canonical timing pending'
    except BaseException:
        state.update(status='failed-no-automatic-retry', error=traceback.format_exc())
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        try:
            state['source_after'] = source_identity()
            state['fixture_after'] = {i['platform']: fingerprint(i, 'after') for i in PLAN['fixtures']}
            state['fixture_guards_after'] = {i['platform']: guards(i['root']) for i in PLAN['fixtures']}
            assert state['fixture_guards_after'] == state['fixture_guards_before']
            assert state['source_before'] == state['source_after']
            state['fixture_checks_passed'] = True
        except BaseException:
            state.update(status='failed-no-automatic-retry', guard_error=traceback.format_exc())
        state.update(finished=time.time(), build_child_reaped=child is None or child.poll() is not None)
        save()
        print(json.dumps({'status': state['status'], 'record': str(record), 'linux_gui': state.get('linux_gui')}), flush=True)
    return 0 if state['status'].startswith('built;') else 1


if __name__ == '__main__':
    raise SystemExit(main())
