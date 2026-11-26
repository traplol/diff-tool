#!/usr/bin/env python3
"""Build only after root explicitly releases this staged candidate's VM slot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time
import traceback

BENCH = Path('/home/max/benchmarks/branchline-boundary')
WORKSPACE = Path('/home/max/workspace/diff-tool')
NATIVE_BENCH = Path('/mnt/c/Users/max/branchline-bench')
OLD_WORKERS = {
    '328c0680bb2d74b61cdc42b242dd944500a7240307ded0869d753dfd0842acaa',
    '6a4067ebc57d88b0e8b6c25a53ea92531acfc07fcb5b3b267fd2fbe19564d3f2',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_start(pid):
    path = Path('/proc') / str(pid) / 'stat'
    return path.read_text().rsplit(') ', 1)[1].split()[19] if path.exists() else None


def stop(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            child.wait()
            return
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--windows-gui', action='store_true')
    args = parser.parse_args()
    if args.release != 'VM STAGED BUILD RELEASED':
        parser.error("Wait for root's VM STAGED BUILD RELEASED")
    inputs = args.input.resolve()
    plan = json.loads((inputs / 'build-plan.json').read_text())
    source = inputs / 'source'
    output = BENCH / (plan['label'] + '-native')
    output.mkdir(exist_ok=False)
    native_output = NATIVE_BENCH / 'binaries' / plan['label']
    native_output.mkdir(parents=True, exist_ok=False)
    record_path = output / 'supervisor.json'
    state = {'pid': os.getpid(), 'start_ticks': process_start(os.getpid()), 'started': time.time(),
             'status': 'running', 'source': plan['source'], 'release': args.release,
             'input': str(inputs), 'phases': [], 'windows_gui_requested': args.windows_gui}

    def save():
        temporary = record_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(record_path)

    def run(name, command, environment, cwd=None):
        cwd = cwd or source
        phase = {'name': name, 'argv': command, 'cwd': str(cwd), 'started': time.time(),
                 'log': str(output / (name + '.log'))}
        state['phases'].append(phase)
        state['current_phase'] = name
        save()
        with Path(phase['log']).open('wb') as log:
            child = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            phase.update(pid=child.pid, start_ticks=process_start(child.pid))
            save()
            try:
                phase['exit'] = child.wait()
            finally:
                stop(child)
        phase['finished'] = time.time()
        save()
        if phase['exit']:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])
        return Path(phase['log'])

    def verify_source():
        for name, expected in plan['snapshot_files'].items():
            if sha(source / name) != expected:
                raise RuntimeError('Source changed: ' + name)
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if head != plan['source']['git_head']:
            raise RuntimeError('Pinned source HEAD changed')

    sys.path.insert(0, str(source / 'tools/autoresearch/wsl-boundary'))
    import workload
    git_environment = {key: workload.ENV[key] for key in [
        'GIT_OPTIONAL_LOCKS', 'GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_TERMINAL_PROMPT']}
    state['kernel_git_environment'] = {'linux': git_environment,
                                      'windows': dict(git_environment, GIT_CONFIG_GLOBAL='NUL')}

    def native_git(root, *arguments):
        # The canonical helper chooses native Git for each volume and disables
        # optional index writes. Explicitly disable diff's independent refresh.
        data = workload.git(root, '-c', 'diff.autoRefreshIndex=false', *arguments)
        state.setdefault('kernel_read_commands', []).append({
            'platform': 'windows' if root == workload.WINDOWS_ROOT else 'linux',
            'executable': str(workload.WINDOWS_GIT) if root == workload.WINDOWS_ROOT else 'git',
            'cwd': workload.WINDOWS_NATIVE_ROOT if root == workload.WINDOWS_ROOT else str(root),
            'argv': ['--no-optional-locks', '-C', workload.WINDOWS_NATIVE_ROOT if root == workload.WINDOWS_ROOT else str(root),
                     '-c', 'diff.autoRefreshIndex=false', *arguments],
            'stdout_sha256': hashlib.sha256(data).hexdigest(), 'stdout_bytes': len(data)})
        return data

    def fingerprint():
        values = {}

        def file_state(root):
            files = {}
            for relative in ['.git/index', '.git/HEAD', '.git/config']:
                path = root / relative
                info = path.stat()
                files[relative] = {'sha256': sha(path), 'size': info.st_size,
                                   'mtime_ns': info.st_mtime_ns, 'inode': info.st_ino, 'mode': info.st_mode}
            return files

        for name, root in [('linux', workload.LINUX_ROOT), ('windows', workload.WINDOWS_ROOT)]:
            files = file_state(root)
            digest = hashlib.sha256()
            for arguments in [
                ['rev-parse', 'HEAD'], ['show-ref'], ['ls-files', '--stage', '-z'],
                ['status', '--porcelain=v1', '-z', '--untracked-files=all'],
                ['diff', '--cached', '--binary', '--no-ext-diff'],
                ['diff', '--binary', '--no-ext-diff'],
            ]:
                digest.update(native_git(root, *arguments))
            for path in sorted(native_git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')):
                if path:
                    digest.update(path)
                    digest.update((root / os.fsdecode(path)).read_bytes())
            if file_state(root) != files:
                raise RuntimeError('Kernel metadata changed during fingerprint: ' + name)
            values[name] = {'git_state_sha256': digest.hexdigest(), 'files': files}
            if values[name]['git_state_sha256'] != plan['fixture_sha256']:
                raise RuntimeError('Kernel fixture differs: ' + name)
        return values

    def kernel_proof(platform, executable):
        root = workload.LINUX_ROOT if platform == 'linux' else workload.WINDOWS_ROOT
        path = str(root) if platform == 'linux' else workload.WINDOWS_NATIVE_ROOT
        manifest = json.loads(workload.MANIFEST.read_text())
        paths = sorted(manifest['local']['Staged'])
        old, staged = {}, {}
        for row in native_git(root, 'ls-tree', '-z', 'HEAD', '--', *paths).split(b'\0'):
            if row:
                metadata, name = row.split(b'\t', 1)
                mode, kind, oid = metadata.decode().split()
                if kind != 'blob':
                    raise RuntimeError('Expected regular kernel blob')
                old[name.decode()] = (mode, oid)
        for row in native_git(root, 'ls-files', '--stage', '-z', '--', *paths).split(b'\0'):
            if row:
                metadata, name = row.split(b'\t', 1)
                mode, oid, stage = metadata.decode().split()
                if stage != '0':
                    raise RuntimeError('Kernel fixture is conflicted')
                staged[name.decode()] = (mode, oid)
        expected = [{'path': name, 'old_mode': old[name][0], 'old_oid': old[name][1],
                     'mode': staged[name][0], 'oid': staged[name][1]} for name in paths]
        proof = {'platform': platform, 'executable': str(executable), 'sha256': sha(executable),
                 'cwd': str(native_output if platform == 'windows' else output), 'started': time.time()}
        state.setdefault('kernel_proofs', []).append(proof)
        save()
        with (output / (platform + '-kernel-proof.stderr')).open('wb') as errors:
            child = subprocess.Popen([str(executable), '--stdio'], cwd=proof['cwd'], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
            proof.update(interop_pid=child.pid, start_ticks=process_start(child.pid))
            serial = 0

            def request(operation):
                nonlocal serial
                serial += 1
                child.stdin.write((json.dumps(dict(operation, id=serial)) + '\n').encode())
                child.stdin.flush()
                if not select.select([child.stdout], [], [], 120)[0]:
                    raise RuntimeError('Worker request timed out')
                response = json.loads(child.stdout.readline())
                if response.get('id') != serial or 'error' in response:
                    raise RuntimeError('Worker request failed: ' + repr(response))
                return response['result']

            try:
                hello = request({'op': 'hello'})
                proof['hello'] = hello
                save()
                if hello.get('protocol') != 2 or hello.get('os') != platform:
                    raise RuntimeError('Worker protocol/platform mismatch')
                view = request({'op': 'open', 'path': path})['repo']
                result = request({'op': 'verify_staged_versions', 'view': view,
                                  'checkout': view['checkout'], 'expected': expected})
                if result is None or sorted(result['versions'], key=lambda value: value['path']) != expected:
                    raise RuntimeError('Kernel staged-version proof mismatch')
                if result['base'] != view['refs'][view['checkout']] or not result['location_head'].startswith('staged:'):
                    raise RuntimeError('Kernel proof identity mismatch')
                if request({'op': 'hello'}) != hello:
                    raise RuntimeError('Persistent worker identity changed')
                proof.update(expected=expected, result=result)
                child.stdin.close()
                proof['exit'] = child.wait(timeout=30)
                if proof['exit'] != 0:
                    raise RuntimeError('Worker did not exit normally')
            finally:
                stop(child)
            proof['finished'] = time.time()
            save()

    def interrupt(signum, frame):
        raise KeyboardInterrupt('Supervisor interrupted by signal ' + str(signum))

    for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        signal.signal(signum, interrupt)
    common = dict(os.environ, CARGO_BUILD_JOBS='1', CMAKE_BUILD_PARALLEL_LEVEL='1', CARGO_NET_OFFLINE='true',
                  XWIN_MSVC_SYSROOT=str(WORKSPACE / 'build/prebuilt-msvc/windows-msvc-sysroot'),
                  XWIN_CROSS_COMPILER='clang', XWIN_CACHE_DIR=str(WORKSPACE / 'build/xwin'))
    for key in ['RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'BRANCHLINE_GIT_WORKER_PATH']:
        common.pop(key, None)
    worker_target = WORKSPACE / 'src-tauri/target/git-worker'
    worker_environment = dict(common, CARGO_TARGET_DIR=str(worker_target), RUSTFLAGS='-C target-feature=+crt-static')
    linux_worker_environment = dict(worker_environment, LIBZ_SYS_STATIC='1')
    manifest = str(source / 'src-tauri/git-worker/Cargo.toml')
    linux_target, windows_target = 'x86_64-unknown-linux-gnu', 'x86_64-pc-windows-msvc'
    state['build_environments'] = {name: {key: env[key] for key in [
        'CARGO_BUILD_JOBS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'CARGO_NET_OFFLINE', 'CARGO_TARGET_DIR',
        'RUSTFLAGS', 'XWIN_MSVC_SYSROOT', 'XWIN_CROSS_COMPILER', 'XWIN_CACHE_DIR']}
        for name, env in [('linux_worker', linux_worker_environment), ('windows_worker', worker_environment)]}
    state['build_environments']['linux_worker']['LIBZ_SYS_STATIC'] = '1'
    failure = None
    try:
        save()
        print(json.dumps({'supervisor_pid': os.getpid(), 'record': str(record_path)}), flush=True)
        verify_source()
        state['fixture_before'] = fingerprint()
        save()
        run('linux-worker-build', ['cargo', 'build', '--offline', '--locked', '--release', '--manifest-path', manifest,
                                  '--target', linux_target], linux_worker_environment)
        run('windows-worker-build', ['cargo', 'xwin', 'build', '--offline', '--locked', '--release',
                                    '--manifest-path', manifest, '--target', windows_target], worker_environment)
        linux_worker, windows_worker = output / 'branchline-git-worker', native_output / 'branchline-git-worker.exe'
        for original, destination in [
            (worker_target / linux_target / 'release/branchline-git-worker', linux_worker),
            (worker_target / windows_target / 'release/branchline-git-worker.exe', windows_worker),
        ]:
            shutil.copy2(original, destination)
            if sha(original) != sha(destination) or sha(destination) in OLD_WORKERS:
                raise RuntimeError('Worker copy differs or reuses an old protocol1 artifact')
        state['workers'] = {name: {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}
                            for name, path in [('linux', linux_worker), ('windows', windows_worker)]}
        run('linux-worker-format', ['file', str(linux_worker)], common)
        program_headers = run('linux-worker-program-headers', ['readelf', '-l', str(linux_worker)], common)
        if 'INTERP' in program_headers.read_text():
            raise RuntimeError('GNU Linux worker is not static')
        run('linux-worker-tests', ['cargo', 'test', '--offline', '--locked', '--release', '--manifest-path', manifest,
                                  '--target', linux_target, '--', '--test-threads=1'], linux_worker_environment)
        log = run('windows-worker-tests-build', ['cargo', 'xwin', 'test', '--offline', '--locked', '--release',
                  '--manifest-path', manifest, '--target', windows_target, '--bin', 'branchline-git-worker',
                  '--no-run', '--message-format=json'], worker_environment)
        artifacts = []
        for line in log.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('reason') == 'compiler-artifact' and value.get('profile', {}).get('test') and value.get('executable'):
                artifacts.append(Path(value['executable']))
        if len(artifacts) != 1:
            raise RuntimeError('Expected exactly one Windows worker unit-test binary')
        native_tests = native_output / 'worker-unit-tests.exe'
        shutil.copy2(artifacts[0], native_tests)
        if sha(artifacts[0]) != sha(native_tests):
            raise RuntimeError('Windows unit-test copy differs')
        run('windows-worker-unit-tests', [str(native_tests), '--test-threads=1'], common, cwd=native_output)
        kernel_proof('linux', linux_worker)
        kernel_proof('windows', windows_worker)
        gui_common = dict(common, CARGO_TARGET_DIR=str(WORKSPACE / 'src-tauri/target'))
        linux_gui_environment = dict(gui_common, BRANCHLINE_GIT_WORKER_PATH=str(windows_worker))
        windows_gui_environment = dict(gui_common, BRANCHLINE_GIT_WORKER_PATH=str(linux_worker))
        state['build_environments']['linux_gui'] = {'CARGO_TARGET_DIR': gui_common['CARGO_TARGET_DIR'],
                                                   'BRANCHLINE_GIT_WORKER_PATH': str(windows_worker)}
        state['build_environments']['windows_gui'] = {'CARGO_TARGET_DIR': gui_common['CARGO_TARGET_DIR'],
                                                     'BRANCHLINE_GIT_WORKER_PATH': str(linux_worker),
                                                     'RUSTFLAGS': 'build.sh adds -C target-feature=+crt-static'}
        run('linux-gui-build', ['./build.sh', '--no-bundle'], linux_gui_environment)
        linux_binary = BENCH / 'binaries' / plan['label'] / 'branchline'
        linux_binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WORKSPACE / 'src-tauri/target/release/branchline', linux_binary)
        if windows_worker.read_bytes() not in linux_binary.read_bytes():
            raise RuntimeError('Fresh Windows worker is missing from Linux GUI')
        state['linux_gui'] = {'path': str(linux_binary), 'sha256': sha(linux_binary), 'bytes': linux_binary.stat().st_size,
                              'embedded_helper_sha256': sha(windows_worker), 'embedded_helper_verified': True,
                              'renderer': 'production default'}
        save()
        if args.windows_gui:
            run('windows-gui-build', ['./build.sh', '--windows'], windows_gui_environment)
            windows_binary = native_output / 'branchline.exe'
            shutil.copy2(WORKSPACE / 'src-tauri/target/x86_64-pc-windows-msvc/release/branchline.exe', windows_binary)
            if linux_worker.read_bytes() not in windows_binary.read_bytes():
                raise RuntimeError('Fresh Linux worker is missing from Windows GUI')
            state['windows_gui'] = {'path': str(windows_binary), 'sha256': sha(windows_binary),
                                    'bytes': windows_binary.stat().st_size, 'embedded_helper_sha256': sha(linux_worker),
                                    'embedded_helper_verified': True, 'renderer': 'production default'}
        verify_source()
    except BaseException as error:
        failure = error
        state.update(error=str(error), traceback=traceback.format_exc())
    finally:
        if 'fixture_before' in state:
            try:
                state['fixture_after'] = fingerprint()
                if state['fixture_before'] != state['fixture_after']:
                    raise RuntimeError('Kernel index/config/HEAD metadata or Git state changed')
            except BaseException as error:
                state['fixture_after_error'] = str(error)
                failure = failure or error
        state.update(status='failed' if failure else 'built; canonical GUI evaluation pending', finished=time.time())
        save()
    if failure:
        raise failure
    print(json.dumps({'record': str(record_path), 'linux_gui': state['linux_gui'],
                      'windows_gui': state.get('windows_gui'), 'workers': state['workers']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
