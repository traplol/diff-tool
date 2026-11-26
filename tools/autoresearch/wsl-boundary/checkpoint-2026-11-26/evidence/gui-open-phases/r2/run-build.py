#!/usr/bin/env python3
"""Transfer and build this diagnostic source after root releases the VM."""
from pathlib import Path
import argparse
import base64
import hashlib
import io
import json
import os
import shlex
import subprocess
import tarfile
import time
import traceback
import tempfile
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def archive_roundtrip(archive, plan):
    root = HERE.parents[3]
    sys.path.insert(0, str(root / 'tools/autoresearch/wsl-boundary'))
    import score
    with tempfile.TemporaryDirectory(prefix='gui-open-r2-roundtrip-') as temporary:
        extracted = Path(temporary)
        with tarfile.open(archive) as bundle:
            bundle.extractall(extracted, filter='data')
        source = extracted / 'source'
        for name, expected in plan['snapshot_files'].items():
            assert sha(source / name) == expected, name
        for name in plan['snapshot_directories']:
            assert (source / name).is_dir(), name
        assert (source / '.git').is_dir() and not (source / '.git/objects/info/alternates').exists()
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        kind = subprocess.check_output(['git', '-C', str(source), 'cat-file', '-t', head], text=True).strip()
        identity = score.source_identity(source)
        assert head == plan['source']['git_head'] and kind == 'commit' and identity == plan['source']
        return {'status': 'host-archive-Git-and-source-roundtrip-passed', 'archive_sha256': sha(archive),
                'git_head': head, 'object_type': kind, 'source_hash': identity['source_hash'],
                'official_file_count': len(identity['files']), 'files_verified': len(plan['snapshot_files']),
                'actual_Git_directories_verified': plan['snapshot_directories'], 'alternates_absent': True,
                'build_or_tests_run': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.release != 'VM OPEN PHASE BUILD RELEASED':
        parser.error('Wait for root: VM OPEN PHASE BUILD RELEASED')
    plan = json.loads((HERE / 'build-plan.json').read_text())
    source = HERE.parent / 'source'
    proof = json.loads((HERE / 'host-proof.json').read_text())
    assert proof['source_hash'] == plan['source']['source_hash'] and proof['status'] == 'host-source-and-rust-syntax-only-passed'
    assert proof['syntax']['parse_passed'] and proof['build_or_tests_run'] is False
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
        encoded = base64.b64encode(code.encode()).decode()
        code = "import base64;exec(base64.b64decode('" + encoded + "'))"
        return ssh + ['MSYS_NO_PATHCONV=1 ' + shlex.join([
            'wsl.exe', '--distribution', 'Ubuntu-26.04', '--user', 'max', '--exec', '/usr/bin/python3', '-u', '-c', code])]

    try:
        archive = output / 'frozen-input.tar'
        with tarfile.open(archive, 'w') as bundle:
            for name in plan['snapshot_directories']:
                bundle.add(source / name, arcname='source/' + name, recursive=False)
            for name in plan['snapshot_files']:
                bundle.add(source / name, arcname='source/' + name, recursive=False)
            for name in ('build-plan.json', 'vm-build-supervisor.py'):
                bundle.add(HERE / name, arcname=name, recursive=False)
        state['archive_roundtrip'] = archive_roundtrip(archive, plan)
        (output / 'host-git-roundtrip.json').write_text(json.dumps(state['archive_roundtrip'], indent=2) + '\n')
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
            'exec("import pathlib,os,json\\nold={\'pid\': 195196, \'start_ticks\': \'15367023\', \'input\': \'/home/max/benchmarks/branchline-boundary/gui-open-phases-b2de070-29898a628ed5-input\', \'record\': \'/home/max/benchmarks/branchline-boundary/gui-open-phases-b2de070-29898a628ed5-native/supervisor.json\'};live=[]\\nfor proc in pathlib.Path(\'/proc\').iterdir():\\n if not proc.name.isdigit() or int(proc.name)==os.getpid():continue\\n try:\\n  f=(proc/\'stat\').read_text().rsplit(\') \',1)[1].split()\\n  args=(proc/\'cmdline\').read_bytes().decode(errors=\'replace\').split(\'\\\\0\')\\n  cwd=str((proc/\'cwd\').resolve())\\n  exact=int(proc.name)==old[\'pid\'] and f[19]==old[\'start_ticks\']\\n  owned_path=any(a.startswith(old[\'input\']+\'/\') for a in args) or cwd.startswith(old[\'input\']+\'/\')\\n  if exact or owned_path:live.append({\'pid\':int(proc.name),\'start_ticks\':f[19]})\\n except (FileNotFoundError,ProcessLookupError,PermissionError):pass\\nassert not live,(\'Previous failed owner or descendants still live\',live)\\n(p/\'old-owner-check.json\').write_text(json.dumps({\'previous\':old,\'exact_owner_and_private_descendants_absent\':True,\'observed\':live}))\\n"); ' +
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
                       'windows_gui': result.get('windows_gui'), 'embedded_helper': result.get('helper'),
                       'build_environment': result.get('effective_build_environment'),
                       'versions': result.get('versions'), 'phases': [result['build']] if result.get('build') else [],
                       'fixture_checks_passed': result.get('fixture_checks_passed', False),
                       'vm_record': plan['vm_output'] + '/supervisor.json', 'promoted': False}
        (HERE / 'native-build-proof.json').write_text(json.dumps(build_proof, indent=2) + '\n')
        if result.get('windows_gui'):
            binary = subprocess.check_output(remote_python('import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(' + repr(plan['artifact']) + ').read_bytes())'), timeout=120)
            (output / 'branchline.exe').write_bytes(binary)
            (output / 'branchline.exe').chmod(0o755)
            assert hashlib.sha256(binary).hexdigest() == result['windows_gui']['sha256']
        for name, expected in plan['snapshot_files'].items():
            assert sha(source / name) == expected, name
        assert state['supervisor_exit'] == 0, 'Native supervisor failed; evidence copied'
        state['status'] = 'single diagnostic Windows GUI built; no runtime evaluation'
    except BaseException:
        state.update(status='failed-no-automatic-retry', error=traceback.format_exc())
        raise
    finally:
        state['finished'] = time.time()
        save()


if __name__ == '__main__':
    main()
