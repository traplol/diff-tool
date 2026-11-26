#!/usr/bin/env python3
"""Run the frozen integrated candidate's serial VM build after explicit release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tarfile
import time


RELEASE = 'VM INTEGRATED CLI BUILD RELEASED'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_start(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != RELEASE:
        parser.error("Wait for root's explicit " + RELEASE)
    base = Path(__file__).resolve().parent
    candidate = base.parent
    state_path = base / 'native-build-supervisor.json'
    for path in [state_path, base / 'native-evidence', base / 'native-evidence.tar']:
        if path.exists():
            raise RuntimeError('Existing run evidence: inspect ownership/results before retrying: ' + str(path))
    plan = json.loads((base / 'build-plan.json').read_text())
    archive = json.loads((base / 'input-tar.json').read_text())
    proof = json.loads((candidate / 'proof.json').read_text())
    if plan['release_required'] != RELEASE or plan['protocol'] != 1:
        raise RuntimeError('Prepared build has another release or worker protocol')
    if plan['app_files'] != plan['source']['files'] or len(plan['app_files']) != 49:
        raise RuntimeError('Expected the canonical 49-file app source')
    if (proof['source_hash'] != plan['source']['source_hash']
            or proof['git_head'] != plan['source']['git_head']
            or proof['canonical_app_files'] != 49):
        raise RuntimeError('Host proof belongs to another source')
    if any(proof['host_worker'][name] != value for name, value in
           [('unit_passed', 25), ('real_stdio_passed', 1), ('failed', 0), ('ignored', 0)]):
        raise RuntimeError('Expected the successful 25-unit and one-stdio host proof')
    if any(proof['host_gui_rust'][name] != value for name, value in
           [('passed', 70), ('failed', 0), ('ignored', 1)]):
        raise RuntimeError('Expected the successful 70-test host GUI proof with one ignored test')
    for name, expected in plan['host_proof_files'].items():
        if sha(candidate / name) != expected:
            raise RuntimeError('Host proof changed: ' + name)
    for name, expected in plan['snapshot_files'].items():
        if sha(candidate / 'source' / name) != expected:
            raise RuntimeError('Frozen source changed: ' + name)
    for name, expected in plan['app_files'].items():
        if sha(candidate / 'source' / name) != expected:
            raise RuntimeError('Frozen app source changed: ' + name)
    if sha(base / archive['name']) != archive['sha256']:
        raise RuntimeError('Input tar changed')
    for name, field in [('build-plan.json', 'build_plan_sha256'),
                        ('vm-build-supervisor.py', 'vm_supervisor_sha256'),
                        ('build-after-release.py', 'host_launcher_sha256'),
                        ('verify-package.py', 'host_verifier_sha256')]:
        if sha(base / name) != archive[field]:
            raise RuntimeError('Prepared build control changed: ' + name)
    if sha(base / 'controls/workload.py') != plan['workload_sha256']:
        raise RuntimeError('Prepared workload control changed')
    with tarfile.open(base / archive['name']) as packed:
        for name in ['build-plan.json', 'vm-build-supervisor.py', 'controls/workload.py']:
            if hashlib.sha256(packed.extractfile(name).read()).hexdigest() != sha(base / name):
                raise RuntimeError('Packed control differs: ' + name)
    if sha(base / plan['bundle']['name']) != plan['bundle']['sha256']:
        raise RuntimeError('Source bundle changed')
    subprocess.run([sys.executable, str(base / 'verify-package.py')], check=True)
    state = {'pid': os.getpid(), 'start_ticks': process_start(os.getpid()),
             'started': time.time(), 'status': 'running', 'release': args.release,
             'source_hash': plan['source']['source_hash'], 'archive': archive, 'phases': [],
             'host_checks': 'unchanged successful 70 GUI (one ignored), 25 worker and one stdio proof',
             'windows_gui_requested': True, 'linux_gui_requested': True}

    def save():
        temporary = state_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(state_path)

    # Reserve this run without replacing an earlier owner or failed record.
    with state_path.open('x') as record:
        record.write(json.dumps(state, indent=2) + '\n')

    def request_stop(signum, frame):
        state.setdefault('stop_requested', {'signal': signum, 'at': time.time()})
        save()

    for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
        signal.signal(signum, request_stop)

    def run(name, command, data=None, output_name=None, check=True):
        phase = {'name': name, 'argv': command, 'started': time.time(),
                 'log': str(base / (output_name or name + '.log'))}
        state['phases'].append(phase)
        save()
        with Path(phase['log']).open('xb') as log:
            child = subprocess.Popen(command, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT)
            phase.update(pid=child.pid, start_ticks=process_start(child.pid))
            save()
            try:
                child.communicate(input=data)
            finally:
                # Keep the owned SSH connection until its remote command exits.
                # Disconnecting it could leave a live build with uncertain ownership.
                if child.poll() is None:
                    child.wait()
                phase.update(exit=child.returncode, finished=time.time(),
                             exact_actor_absent=process_start(child.pid) != phase['start_ticks'])
                save()
        if not phase['exact_actor_absent']:
            raise RuntimeError('Exact phase actor remains live: ' + name)
        if check and child.returncode:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])
        return child.returncode

    try:
        ssh = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', 'windows-vm']
        windows_archive = '/c/Users/max/branchline-bench/' + archive['name']
        run('integrated-upload-input', ssh + ['set -C; cat > ' + shlex.quote(windows_archive)],
            data=(base / archive['name']).read_bytes())
        if state.get('stop_requested'):
            raise KeyboardInterrupt('Stopped after the owned input upload exited')
        mounted_archive = '/mnt/c/Users/max/branchline-bench/' + archive['name']
        supervisor_arguments = ['--release', args.release, '--input', plan['source_input_directory']]
        extract_and_run = (
            'import hashlib, os, pathlib, tarfile; '
            'a=pathlib.Path(' + repr(mounted_archive) + '); '
            'assert hashlib.sha256(a.read_bytes()).hexdigest() == ' + repr(archive['sha256']) + '; '
            'p=pathlib.Path(' + repr(plan['source_input_directory']) + '); p.mkdir(exist_ok=False); '
            'tarfile.open(a).extractall(p, filter="data"); '
            'os.execv("/usr/bin/python3", ["/usr/bin/python3", "-u", str(p/"vm-build-supervisor.py"), '
            + ', '.join(repr(value) for value in supervisor_arguments) + '])'
        )
        shell = 'export PATH="$HOME/.cargo/bin:$PATH"; exec ' + shlex.join([
            '/usr/bin/python3', '-u', '-c', extract_and_run])
        remote = 'MSYS_NO_PATHCONV=1 ' + shlex.join([
            'wsl.exe', '--distribution', 'Ubuntu-26.04', '--user', 'max', '--exec', '/bin/sh', '-lc', shell])
        build_exit = run('integrated-vm-build', ssh + [remote], check=False)
        native_gui = '/mnt/c/' + plan['windows_binary'][3:]
        collect = f"""import json, pathlib, sys, tarfile
p = pathlib.Path({plan['artifact_directory']!r})
s = json.loads((p / 'supervisor.json').read_text())
assert s['status'] in ['failed', 'built; canonical GUI evaluation pending'] and s.get('finished')
def absent(actor):
    current = pathlib.Path('/proc') / str(actor['pid']) / 'stat'
    return not current.exists() or current.read_text().rsplit(') ', 1)[1].split()[19] != actor['start_ticks']
assert absent(s) and all(absent(phase) for phase in s['phases'] if 'pid' in phase)
paths = [(pathlib.Path({plan['linux_binary']!r}), 'branchline'),
         (pathlib.Path({native_gui!r}), 'branchline.exe'),
         (pathlib.Path({native_gui!r}).parent / 'branchline-git-worker.exe', 'branchline-git-worker.exe')]
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as packed:
    packed.add(p, arcname='.')
    for path, name in paths:
        if path.is_file():
            packed.add(path, arcname=name)
"""
        command = 'MSYS_NO_PATHCONV=1 ' + shlex.join([
            'wsl.exe', '-d', 'Ubuntu-26.04', '-u', 'max', '--exec', '/usr/bin/python3', '-u', '-c', collect])
        run('copy-native-evidence', ssh + [command], output_name='native-evidence.tar')
        with tarfile.open(base / 'native-evidence.tar') as packed:
            packed.extractall(base / 'native-evidence', filter='data')
        proof = json.loads((base / 'native-evidence/supervisor.json').read_text())
        if build_exit or proof['status'] != 'built; canonical GUI evaluation pending':
            raise RuntimeError('Native build failed; terminal evidence was copied without retrying')
        if proof['source'] != plan['source'] or proof['fixture_before'] != proof['fixture_after']:
            raise RuntimeError('Native source or fixture proof differs')
        provenance = proof['source_git_provenance']
        if (provenance['head'] != plan['source']['git_head']
                or provenance['tree'] != plan['bundle']['git_tree']
                or provenance['bundle_sha256'] != plan['bundle']['sha256']
                or provenance['external_alternates'] is not False
                or provenance['working_files_preserved'] is not True):
            raise RuntimeError('Native source Git provenance differs')
        if not all(phase['exit'] == 0 for phase in proof['phases']):
            raise RuntimeError('A native phase did not pass')
        if not all(value['fresh'] is False for value in proof['producer_artifacts'].values()):
            raise RuntimeError('A native root producer artifact was reused')
        artifacts = {'linux_worker': ('branchline-git-worker', proof['workers']['linux']),
                     'windows_worker': ('branchline-git-worker.exe', proof['workers']['windows']),
                     'linux_gui': ('branchline', proof['linux_gui']),
                     'windows_gui': ('branchline.exe', proof['windows_gui'])}
        state['copied_binary_hashes'] = {}
        for name, (filename, artifact) in artifacts.items():
            if sha(base / 'native-evidence' / filename) != artifact['sha256']:
                raise RuntimeError('Copied native artifact differs: ' + name)
            state['copied_binary_hashes'][name] = artifact['sha256']
        state.update(status='native GNU/PE workers, checks and both GUI builds complete; GUI scoring pending',
                     finished=time.time())
        save()
        print(json.dumps(state, indent=2))
    except BaseException as error:
        state.update(status='failed; inspect remote supervisor ownership before retry',
                     error=str(error), finished=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
