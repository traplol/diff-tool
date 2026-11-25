#!/usr/bin/env python3
"""Transfer and build this one candidate after root releases the VM."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import shlex
import subprocess
import tarfile
import time
import traceback

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM GEOMETRY BUILD RELEASED':
        parser.error('Wait for root: VM GEOMETRY BUILD RELEASED')
    plan = json.loads((HERE / 'build-plan.json').read_text())
    source = HERE / 'source'
    proof = json.loads((HERE / 'host-proof.json').read_text())
    assert proof['source_hash'] == plan['source']['source_hash'] and proof['build'] == 'passed'
    assert proof['test_suites_passed'] == 5 and proof['test_suites_failed'] == 0
    assert sha(HERE / 'host-proof.json') == plan['host_proof_sha256']
    assert sha(HERE / 'vm-build-supervisor.py') == plan['supervisor_sha256']
    for name, expected in plan['snapshot_files'].items():
        assert sha(source / name) == expected, name
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == plan['source']['git_head']
    output = HERE / 'native-build-evidence'
    output.mkdir(exist_ok=False)
    state = {'host_pid': os.getpid(), 'host_start_ticks': Path('/proc/self/stat').read_text().rsplit(') ', 1)[1].split()[19],
             'started': time.time(), 'status': 'running', 'plan': plan, 'phases': []}

    def save():
        (output / 'host-owner.json').write_text(json.dumps(state, indent=2) + '\n')

    ssh = ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'windows-vm']

    def remote_python(code):
        return ssh + ['MSYS_NO_PATHCONV=1 ' + shlex.join([
            'wsl.exe', '--distribution', 'Ubuntu-26.04', '--user', 'max', '--exec', '/usr/bin/python3', '-u', '-c', code])]

    try:
        archive = output / 'frozen-input.tar'
        with tarfile.open(archive, 'w') as bundle:
            for name in plan['snapshot_files']:
                bundle.add(source / name, arcname='source/' + name, recursive=False)
            for name in ('build-plan.json', 'vm-build-supervisor.py'):
                bundle.add(HERE / name, arcname=name, recursive=False)
        state['archive'] = {'path': str(archive), 'sha256': sha(archive), 'bytes': archive.stat().st_size}
        save()
        print(json.dumps({'host_pid': os.getpid(), 'owner': str(output / 'host-owner.json'), 'phase': 'upload'}), flush=True)
        upload = 'test ! -e ' + shlex.quote(plan['windows_archive']) + ' && cat > ' + shlex.quote(plan['windows_archive'])
        subprocess.run(ssh + [upload], input=archive.read_bytes(), check=True, timeout=120)
        bootstrap = (
            'import pathlib,tarfile,os,hashlib; '
            'a=pathlib.Path(' + repr(plan['mounted_archive']) + '); '
            'assert hashlib.sha256(a.read_bytes()).hexdigest()==' + repr(state['archive']['sha256']) + '; '
            'p=pathlib.Path(' + repr(plan['vm_input']) + '); p.mkdir(exist_ok=False); '
            'tarfile.open(a).extractall(p,filter="data"); '
            'os.execv("/usr/bin/python3",["/usr/bin/python3","-u",str(p/"vm-build-supervisor.py"),"--release",' + repr(args.release) + '])')
        command = remote_python(bootstrap)
        state['command'] = command
        with (output / 'supervisor.stdout.log').open('w') as log:
            child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            state['ssh_pid'] = child.pid
            save()
            for line in child.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
                try:
                    event = json.loads(line)
                    if event.get('supervisor_pid'):
                        state['vm_supervisor'] = event
                    if event.get('build_pid'):
                        state['vm_build'] = event
                    save()
                except json.JSONDecodeError:
                    pass
            state['supervisor_exit'] = child.wait()
        save()
        evidence = subprocess.check_output(remote_python(
            'import subprocess,sys; subprocess.run(["tar","-C",' + repr(plan['vm_output']) + ',"-cf","-","."],check=True)'), timeout=120)
        (output / 'vm-evidence.tar').write_bytes(evidence)
        with tarfile.open(fileobj=io.BytesIO(evidence)) as bundle:
            bundle.extractall(output / 'vm', filter='data')
        result = json.loads((output / 'vm/supervisor.json').read_text())
        build_proof = {'label': plan['label'], 'source': plan['source'],
                       'source_hash': plan['source']['source_hash'], 'vm_source': plan['vm_input'] + '/source',
                       'supervisor_pid': result['pid'], 'supervisor_start_ticks': result['start_ticks'],
                       'supervisor_status': result['status'], 'status': result['status'],
                       'linux_gui': result.get('linux_gui'), 'embedded_helper': result.get('helper'),
                       'build_environment': result.get('effective_build_environment'),
                       'versions': result.get('versions'), 'phases': [result['build']] if result.get('build') else [],
                       'fixture_checks_passed': result.get('fixture_checks_passed', False),
                       'vm_record': plan['vm_output'] + '/supervisor.json', 'promoted': False}
        (HERE / 'native-build-proof.json').write_text(json.dumps(build_proof, indent=2) + '\n')
        if result.get('linux_gui'):
            binary = subprocess.check_output(remote_python('import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(' + repr(plan['artifact']) + ').read_bytes())'), timeout=120)
            (output / 'branchline').write_bytes(binary)
            (output / 'branchline').chmod(0o755)
            assert hashlib.sha256(binary).hexdigest() == result['linux_gui']['sha256']
        for name, expected in plan['snapshot_files'].items():
            assert sha(source / name) == expected, name
        assert state['supervisor_exit'] == 0, 'Native supervisor failed; evidence copied'
        state['status'] = 'single Linux GUI built; no runtime evaluation'
    except BaseException:
        state.update(status='failed-no-automatic-retry', error=traceback.format_exc())
        raise
    finally:
        state['finished'] = time.time()
        save()


if __name__ == '__main__':
    main()
