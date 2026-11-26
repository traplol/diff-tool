#!/usr/bin/env python3
"""Run the frozen Linux-CLI candidate's serial VM build only after explicit release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import sys
import tarfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM LINUX CLI BRANCH BUILD RELEASED':
        parser.error("Wait for root's explicit VM LINUX CLI BRANCH BUILD RELEASED")
    base = Path(__file__).resolve().parent
    candidate = base.parent
    plan = json.loads((base / 'build-plan.json').read_text())
    archive = json.loads((base / 'input-tar.json').read_text())
    proof = json.loads((candidate / 'proof.json').read_text())
    if proof['source_hash'] != plan['source']['source_hash']:
        raise RuntimeError('Host proof belongs to another source')
    for name, expected in plan['host_proof_files'].items():
        if sha(candidate / name) != expected:
            raise RuntimeError('Host proof changed: ' + name)
    for name, expected in plan['app_files'].items():
        if sha(candidate / 'source' / name) != expected:
            raise RuntimeError('Frozen source changed: ' + name)
    if sha(base / archive['name']) != archive['sha256']:
        raise RuntimeError('Input tar changed')
    for name, field in [('build-plan.json', 'build_plan_sha256'),
                        ('vm-build-supervisor.py', 'vm_supervisor_sha256'),
                        ('build-after-release.py', 'host_launcher_sha256')]:
        if sha(base / name) != archive[field]:
            raise RuntimeError('Prepared build control changed: ' + name)
    import tarfile
    with tarfile.open(base / archive['name']) as packed:
        for name in ['build-plan.json', 'vm-build-supervisor.py']:
            if hashlib.sha256(packed.extractfile(name).read()).hexdigest() != sha(base / name):
                raise RuntimeError('Packed control differs: ' + name)
    if sha(base / plan['bundle']['name']) != plan['bundle']['sha256']:
        raise RuntimeError('Source bundle changed')
    state_path = base / 'native-build-supervisor.json'
    if state_path.exists():
        raise RuntimeError('Existing run record: inspect ownership/results before retrying')
    subprocess.run([sys.executable,str(base/'verify-package.py')],check=True)
    state = {'pid': os.getpid(), 'started': time.time(), 'status': 'running', 'release': args.release,
             'source_hash': plan['source']['source_hash'], 'archive': archive, 'phases': [],
             'host_checks': 'reused unchanged successful70 GUI+25 worker+1 stdio proof',
             'windows_gui_requested': True}

    def save():
        temporary = state_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(state_path)

    def run(name, command, data=None, output_name=None):
        phase = {'name': name, 'argv': command, 'started': time.time(), 'log': str(base / (output_name or name+'.log'))}
        state['phases'].append(phase)
        save()
        with Path(phase['log']).open('wb') as log:
            child = subprocess.Popen(command, stdin=subprocess.PIPE if data else subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT)
            phase['pid'] = child.pid
            save()
            try:
                child.communicate(input=data)
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            phase.update(exit=child.returncode, finished=time.time())
        save()
        if child.returncode:
            raise RuntimeError(name + ' failed; inspect ' + phase['log'])

    try:
        save()
        ssh = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', 'windows-vm']
        windows_archive = '/c/Users/max/branchline-bench/' + archive['name']
        run('linux-cli-upload-input', ssh + ['cat > ' + shlex.quote(windows_archive)],
            data=(base / archive['name']).read_bytes())
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
        run('linux-cli-vm-build', ssh + [remote])
        native_gui='/mnt/c/'+plan['windows_binary'][3:]
        collect=("import json,pathlib,sys,tarfile; "
                 f"p=pathlib.Path({plan['artifact_directory']!r});s=json.loads((p/'supervisor.json').read_text()); "
                 "assert s['status']=='built; canonical GUI evaluation pending'; "
                 "current=pathlib.Path('/proc')/str(s['pid'])/'stat'; "
                 "assert not current.exists() or current.read_text().rsplit(') ',1)[1].split()[19]!=s['start_ticks']; "
                 "t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|');t.add(p,arcname='.'); "
                 f"t.add({native_gui!r},arcname='branchline.exe');t.close()")
        command='MSYS_NO_PATHCONV=1 '+shlex.join(['wsl.exe','-d','Ubuntu-26.04','-u','max','--exec','/usr/bin/python3','-u','-c',collect])
        run('copy-native-evidence',ssh+[command],output_name='native-evidence.tar')
        with tarfile.open(base/'native-evidence.tar') as packed:packed.extractall(base/'native-evidence',filter='data')
        proof=json.loads((base/'native-evidence/supervisor.json').read_text())
        assert proof['source']==plan['source'] and proof['fixture_before']==proof['fixture_after']
        assert all(phase['exit']==0 for phase in proof['phases'])
        assert all(value['fresh'] is False for value in proof['producer_artifacts'].values())
        assert sha(base/'native-evidence/branchline.exe')==proof['windows_gui']['sha256']
        assert sha(base/'native-evidence/branchline-git-worker')==proof['workers']['linux']['sha256']
        state['copied_binary_hashes']={'windows_gui':proof['windows_gui']['sha256'],'linux_worker':proof['workers']['linux']['sha256']}
        state.update(status='native GNU worker/checks and Windows GUI build complete; GUI scoring pending', finished=time.time())
        save()
        print(json.dumps(state, indent=2))
    except BaseException as error:
        state.update(status='failed; inspect remote supervisor ownership before retry', error=str(error), finished=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
