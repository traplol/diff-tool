#!/usr/bin/env python3
"""Serial native-helper candidate build. Do not run before root's VM BUILD RELEASED."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback

BENCH = Path('/home/max/benchmarks/branchline-boundary')
HELPERS = {
    'linux': (BENCH / 'helper-placement/placement-v3-01/linux/native/branchline-git-worker',
              '328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa'),
    'windows': (BENCH / 'helper-placement/placement-v3-01/windows/foreign/branchline-git-worker.exe',
                '6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    if args.release != 'VM BUILD RELEASED':
        parser.error("Root must explicitly release the VM first: --release 'VM BUILD RELEASED'")
    inputs = args.input.resolve()
    plan = json.loads((inputs / 'build-plan.json').read_text())
    source = inputs / 'source'
    output = BENCH / (plan['label'] + '-native')
    output.mkdir(exist_ok=True)
    record_path = output / 'supervisor.json'
    if record_path.exists():
        raise RuntimeError('Existing supervisor record: inspect it before selecting a fresh run directory')
    state = {'pid': os.getpid(), 'start_ticks': Path('/proc/self/stat').read_text().rsplit(') ', 1)[1].split()[19],
             'started': time.time(), 'status': 'running', 'source': plan['source'], 'phases': [],
             'release': args.release, 'input': str(inputs)}
    child = None

    def save():
        temporary = record_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(record_path)

    def run(name, command, environment):
        nonlocal child
        phase = {'name': name, 'argv': command, 'cwd': str(source), 'started': time.time(),
                 'log': str(output / (name + '.log'))}
        state['phases'].append(phase)
        state['current_phase'] = name
        save()
        with Path(phase['log']).open('wb') as log:
            child = subprocess.Popen(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT)
            phase['pid'] = child.pid
            save()
            try:
                phase['exit'] = child.wait()
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                child = None
        phase['finished'] = time.time()
        save()
        if phase['exit']:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])
        return Path(phase['log'])

    def verify_source():
        for name, expected in plan['snapshot_files'].items():
            if sha(source / name) != expected:
                raise RuntimeError('Source changed: ' + name)

    def fingerprint():
        sys.path.insert(0, str(source / 'tools/autoresearch/wsl-boundary'))
        import workload
        values = {name: workload.fingerprint(root) for name, root in
                  [('linux', workload.LINUX_ROOT), ('windows', workload.WINDOWS_ROOT)]}
        if set(values.values()) != {plan['fixture_sha256']}:
            raise RuntimeError('Fixture fingerprint changed: ' + repr(values))
        return values

    def interrupt(signum, frame):
        raise KeyboardInterrupt('Supervisor interrupted by signal ' + str(signum))

    for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        signal.signal(signum, interrupt)
    try:
        save()
        print(json.dumps({'supervisor_pid': os.getpid(), 'record': str(record_path), 'status': 'starting'}), flush=True)
        verify_source()
        state['fixture_before'] = fingerprint()
        embedded = {}
        for platform, (original, expected) in HELPERS.items():
            if sha(original) != expected:
                raise RuntimeError('Preserved helper SHA differs: ' + str(original))
            destination = output / ('embedded-' + platform + ('.exe' if platform == 'windows' else ''))
            if destination.exists() and sha(destination) != expected:
                raise RuntimeError('Existing owned embedding differs: ' + str(destination))
            if not destination.exists():
                shutil.copy2(original, destination)
            assert sha(destination) == expected
            embedded[platform] = destination
        state['embedded_helpers'] = {name: {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}
                                     for name, path in embedded.items()}
        common = dict(os.environ, CARGO_BUILD_JOBS='1', CMAKE_BUILD_PARALLEL_LEVEL='1',
                      CARGO_TARGET_DIR='/home/max/workspace/diff-tool/src-tauri/target',
                      XWIN_MSVC_SYSROOT='/home/max/workspace/diff-tool/build/prebuilt-msvc/windows-msvc-sysroot',
                      XWIN_CROSS_COMPILER='clang', XWIN_CACHE_DIR='/home/max/workspace/diff-tool/build/xwin')
        common.pop('RUSTFLAGS', None)
        linux = dict(common, BRANCHLINE_GIT_WORKER_PATH=str(embedded['windows']))
        windows = dict(common, BRANCHLINE_GIT_WORKER_PATH=str(embedded['linux']), RUSTFLAGS='-C target-feature=+crt-static')
        state['build_environments'] = {name: {key: environment[key] for key in
            ['CARGO_BUILD_JOBS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'CARGO_TARGET_DIR', 'BRANCHLINE_GIT_WORKER_PATH',
             'XWIN_MSVC_SYSROOT', 'XWIN_CROSS_COMPILER', 'XWIN_CACHE_DIR']} for name, environment in
             [('linux', linux), ('windows', windows)]}
        state['build_environments']['windows']['RUSTFLAGS'] = windows['RUSTFLAGS']
        save()
        run('linux-remote-tests', ['cargo', 'test', '--offline', '--locked', '--manifest-path',
            str(source / 'src-tauri/Cargo.toml'), 'git::remote', '--', '--test-threads=1'], linux)
        run('linux-gui-build', ['./build.sh', '--no-bundle'], linux)
        linux_binary = BENCH / 'binaries' / plan['label'] / 'branchline'
        linux_binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(common['CARGO_TARGET_DIR']) / 'release/branchline', linux_binary)
        assert embedded['windows'].read_bytes() in linux_binary.read_bytes()
        state['linux_gui'] = {'path': str(linux_binary), 'sha256': sha(linux_binary),
            'bytes': linux_binary.stat().st_size, 'embedded_helper_sha256': HELPERS['windows'][1],
            'embedded_helper_verified': True, 'renderer': 'production default'}
        save()
        log = run('windows-remote-tests-build', ['cargo', 'xwin', 'test', '--offline', '--locked', '--release',
            '--manifest-path', str(source / 'src-tauri/Cargo.toml'), '--target', 'x86_64-pc-windows-msvc',
            '--no-run', '--message-format=json'], windows)
        artifacts = []
        for line in log.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('reason') == 'compiler-artifact' and value.get('profile', {}).get('test') and value.get('executable'):
                artifacts.append(Path(value['executable']))
        assert artifacts, 'No Windows test artifacts were emitted'
        native_output = Path('/mnt/c/Users/max/branchline-bench/binaries') / plan['label']
        native_output.mkdir(parents=True, exist_ok=True)
        for index, artifact in enumerate(artifacts):
            copied = native_output / ('tests-' + str(index) + '.exe')
            shutil.copy2(artifact, copied)
            assert sha(artifact) == sha(copied)
            run('windows-remote-tests-' + str(index), [str(copied), 'git::remote', '--test-threads=1'], windows)
        run('windows-gui-build', ['./build.sh', '--windows'], linux | {'BRANCHLINE_GIT_WORKER_PATH': str(embedded['linux'])})
        windows_binary = native_output / 'branchline.exe'
        shutil.copy2(Path(common['CARGO_TARGET_DIR']) / 'x86_64-pc-windows-msvc/release/branchline.exe', windows_binary)
        assert embedded['linux'].read_bytes() in windows_binary.read_bytes()
        state['windows_gui'] = {'path': str(windows_binary), 'sha256': sha(windows_binary),
            'bytes': windows_binary.stat().st_size, 'embedded_helper_sha256': HELPERS['linux'][1],
            'embedded_helper_verified': True, 'renderer': 'production default'}
        verify_source()
        state['fixture_after'] = fingerprint()
        assert state['fixture_before'] == state['fixture_after']
        for platform, (original, expected) in HELPERS.items():
            assert sha(original) == expected
        state.update(status='built; native deployment/lifecycle/GUI evaluation pending', finished=time.time())
        save()
        print(json.dumps({'supervisor_pid': os.getpid(), 'record': str(record_path),
                          'linux_gui': state['linux_gui'], 'windows_gui': state['windows_gui']}, indent=2), flush=True)
    except BaseException as error:
        state.update(status='failed', error=str(error), traceback=traceback.format_exc(), finished=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
