#!/usr/bin/env python3
"""Verify this candidate's completed host proof and run its serial VM build after release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM BUILD RELEASED':
        parser.error("Wait for root to say VM BUILD RELEASED, then pass --release 'VM BUILD RELEASED'")
    base = Path(__file__).resolve().parent
    repo = base.parents[2]
    plan = json.loads((base / 'build-plan.json').read_text())
    state_path = base / 'next-supervisor.json'
    if state_path.exists():
        raise RuntimeError('An earlier run record exists; inspect it before retrying')
    state = {'pid': os.getpid(), 'started': time.time(), 'status': 'running', 'phases': [],
             'source_hash': plan['source']['source_hash'], 'release': args.release}

    def save():
        state_path.write_text(json.dumps(state, indent=2) + '\n')

    def run(name, command, environment=None, data=None):
        phase = {'name': name, 'argv': command, 'started': time.time(), 'log': str(base / (name + '.log'))}
        state['phases'].append(phase)
        save()
        with Path(phase['log']).open('wb') as log:
            result = subprocess.run(command, input=data, cwd=repo, env=environment,
                                    stdout=log, stderr=subprocess.STDOUT)
        phase.update(exit=result.returncode, finished=time.time())
        save()
        if result.returncode:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])

    try:
        for name, digest in plan['snapshot_files'].items():
            assert hashlib.sha256((base / 'source' / name).read_bytes()).hexdigest() == digest, name
        assert hashlib.sha256((base / 'candidate.patch').read_bytes()).hexdigest() == plan['patch_sha256']
        proof_path = base / 'host-proof-cmd.json'
        proof = json.loads(proof_path.read_text())
        if proof['app_source_hash'] == plan['source']['source_hash']:
            assert proof['snapshot_sha256'] == plan['snapshot_sha256']
            assert proof['patch_sha256'] == plan['patch_sha256']
            for name, outcome in proof['logs'].items():
                assert hashlib.sha256((base / name).read_bytes()).hexdigest() == outcome['sha256'], name
                assert outcome.get('failed', 0) == 0, name
                assert outcome.get('status', 'pass') == 'pass', name
            state['host_checks'] = {'status': 'reused completed proof for unchanged exact source',
                'proof': str(proof_path), 'proof_sha256': hashlib.sha256(proof_path.read_bytes()).hexdigest()}
            save()
        else:
            state['host_checks'] = {'status': 'rerun required because app source changed',
                'previous_source_hash': proof['app_source_hash']}
            save()
            harness = str(base / 'host-harness/Cargo.toml')
            run('host-all-tests-localappdata', ['cargo', 'test', '--offline', '--manifest-path', harness],
                dict(os.environ, CARGO_TARGET_DIR='/tmp/branchline-native-helper-target'))
            embedded = dict(os.environ, CARGO_TARGET_DIR='/tmp/branchline-native-helper-embedded-target',
                BRANCHLINE_GIT_WORKER_PATH=str(base / 'baseline-remote.rs'), RUSTFLAGS='--cfg branchline_git_worker')
            run('host-embedded-tests-localappdata', ['cargo', 'test', '--offline', '--manifest-path', harness, 'git::remote'], embedded)
            windows = dict(embedded, CARGO_TARGET_DIR='/tmp/branchline-native-helper-windows-check',
                RUSTFLAGS='--sysroot /tmp/branchline-windows-check/sysroot --cfg branchline_git_worker')
            run('windows-source-check-localappdata', ['cargo', 'check', '--offline', '--target', 'x86_64-pc-windows-gnu',
                '--tests', '--manifest-path', harness], windows)
            state['host_checks']['status'] = 'passed for changed app source'
            save()
        archive = base / (plan['label'] + '-input.tar')
        with tarfile.open(archive, 'w') as output:
            for name in plan['snapshot_files']:
                output.add(base / 'source' / name, arcname='source/' + name, recursive=False)
            for name in ['build-plan.json', 'vm-build-supervisor.py']:
                output.add(base / name, arcname=name, recursive=False)
        state['archive'] = {'path': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
        save()
        ssh = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', 'windows-vm']
        windows_archive = '/c/Users/max/branchline-bench/' + archive.name
        run('upload-build-input', ssh + ['cat > ' + shlex.quote(windows_archive)], data=archive.read_bytes())
        mounted_archive = '/mnt/c/Users/max/branchline-bench/' + archive.name
        extract_and_run = (
            'import os, pathlib, tarfile; '
            'p=pathlib.Path(' + repr(plan['source_input_directory']) + '); p.mkdir(exist_ok=False); '
            'tarfile.open(' + repr(mounted_archive) + ').extractall(p, filter="data"); '
            'os.execv("/usr/bin/python3", ["/usr/bin/python3", "-u", str(p/"vm-build-supervisor.py"), '
            '"--release", "VM BUILD RELEASED", "--input", str(p)])'
        )
        shell = 'export PATH="$HOME/.cargo/bin:$PATH"; exec ' + shlex.join([
            '/usr/bin/python3', '-u', '-c', extract_and_run])
        remote = 'MSYS_NO_PATHCONV=1 ' + shlex.join([
            'wsl.exe', '--distribution', 'Ubuntu-26.04', '--user', 'max', '--exec', '/bin/sh', '-lc', shell])
        run('vm-build-supervisor', ssh + [remote])
        state.update(status='host proof verified and VM builds complete; runtime evaluation pending', finished=time.time())
        save()
        print(json.dumps(state, indent=2))
    except BaseException as error:
        state.update(status='failed', error=str(error), finished=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
